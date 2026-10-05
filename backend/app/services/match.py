"""Provider-neutral candidate generation and local-LLM transaction matching."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Any, Literal

from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, col, select

from app.config import get_settings
from app.models import Account, Transaction, TransactionLink
from app.models.enums import (
    AccountType,
    LinkEvaluatedBy,
    LinkStatus,
    LinkType,
    TransactionKind,
)
from app.services.llm_categorize import probe_ollama, scrub_pii
from app.services.secure_accounts import AccountData, decode_account
from app.services.secure_transactions import (
    TransactionData,
    decode_transaction,
    update_transaction_payload,
)
from app.services.secure_links import insert_link_payload, update_link_payload
from app.services.vault_session import vault_session

logger = logging.getLogger(__name__)

_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
_match_agent_cache: dict[str, Any] = {"key": None, "agent": None}


class MatchPrediction(BaseModel):
    is_match: bool = Field(description="Whether both records describe one economic movement")
    relationship: Literal["internal_transfer", "account_funding", "not_related"]
    transfer_leg: Literal["a", "b", "both", "none"] = Field(
        description="Which record is only the transfer/funding leg"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(description="Short evidence-based reason without personal data")

    @model_validator(mode="after")
    def validate_relationship(self) -> "MatchPrediction":
        if not self.is_match and self.relationship != "not_related":
            raise ValueError("A non-match must use not_related")
        if self.relationship == "internal_transfer" and self.transfer_leg != "both":
            raise ValueError("Internal transfers must mark both legs")
        if self.relationship == "account_funding" and self.transfer_leg not in {"a", "b"}:
            raise ValueError("Account funding must identify exactly one funding leg")
        if self.relationship == "not_related" and self.transfer_leg != "none":
            raise ValueError("Unrelated records must not mark a transfer leg")
        return self


@dataclass(frozen=True)
class MatchCandidate:
    transaction_a: TransactionData
    transaction_b: TransactionData
    account_a: AccountData | Account
    account_b: AccountData | Account
    rule_score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class MatchRunResult:
    confirmed_links: int = 0
    suggested_links: int = 0
    rejected_candidates: int = 0
    candidates_evaluated: int = 0
    model_available: bool = False

    @property
    def created_links(self) -> int:
        return self.confirmed_links + self.suggested_links


def run_matching(session: Session) -> MatchRunResult:
    """Generate generic candidates and let the local model judge ambiguous pairs."""
    dek = vault_session.get_dek()
    if dek is None:
        return MatchRunResult()
    settings = get_settings()
    candidates = generate_candidates(session, limit=settings.match_max_candidates)
    model_available = settings.ollama_configured and probe_ollama()
    agent = _get_match_agent() if model_available else None
    confirmed = suggested = rejected = evaluated = 0
    reserved_ids = _reserved_transaction_ids(session)

    for candidate in candidates:
        tx_a = candidate.transaction_a
        tx_b = candidate.transaction_b
        if tx_a.id is None or tx_b.id is None:
            continue
        if tx_a.id in reserved_ids or tx_b.id in reserved_ids:
            continue

        prediction = _high_confidence_rule_prediction(candidate)
        evaluated_by = LinkEvaluatedBy.RULE
        if prediction is None:
            if agent is None:
                continue
            prediction = _predict(agent, candidate)
            evaluated_by = LinkEvaluatedBy.LLM
        if prediction is None:
            continue
        evaluated += 1

        if not prediction.is_match or prediction.relationship == "not_related":
            status = LinkStatus.REJECTED
            link_type = LinkType.INTERNAL_TRANSFER
            rejected += 1
        elif prediction.confidence >= settings.match_auto_confidence:
            status = LinkStatus.CONFIRMED
            link_type = LinkType(prediction.relationship)
            confirmed += 1
        elif prediction.confidence >= settings.match_suggest_confidence:
            status = LinkStatus.SUGGESTED
            link_type = LinkType(prediction.relationship)
            suggested += 1
        else:
            status = LinkStatus.REJECTED
            link_type = LinkType(prediction.relationship)
            rejected += 1

        link = insert_link_payload(
            session,
            dek,
            transaction_a_id=min(tx_a.id, tx_b.id),
            transaction_b_id=max(tx_a.id, tx_b.id),
            transfer_transaction_id=_transfer_transaction_id(prediction, tx_a, tx_b),
            link_type=link_type,
            status=status,
            evaluated_by=evaluated_by,
            confidence=Decimal(str(prediction.confidence)).quantize(Decimal("0.0001")),
            reason=prediction.reason[:1000],
        )
        if status == LinkStatus.CONFIRMED:
            stored_a = session.get(Transaction, tx_a.id)
            stored_b = session.get(Transaction, tx_b.id)
            if stored_a is not None and stored_b is not None:
                _apply_confirmed_kinds(session, link, stored_a, stored_b, dek)
            reserved_ids.update((tx_a.id, tx_b.id))
        elif status == LinkStatus.SUGGESTED:
            reserved_ids.update((tx_a.id, tx_b.id))

    session.commit()
    return MatchRunResult(
        confirmed_links=confirmed,
        suggested_links=suggested,
        rejected_candidates=rejected,
        candidates_evaluated=evaluated,
        model_available=model_available,
    )


def generate_candidates(session: Session, *, limit: int = 30) -> list[MatchCandidate]:
    """Preselect plausible cross-account pairs without provider-specific rules."""
    dek = vault_session.get_dek()
    if dek is None:
        return []
    stored_accounts = session.exec(
        select(Account).where(Account.is_active == True)  # noqa: E712
    ).all()
    accounts = {
        account.id: decode_account(account, dek)
        for account in stored_accounts
        if account.id is not None and account.encrypted_payload is not None
    }
    transactions = [
        decode_transaction(row, dek)
        for row in session.exec(select(Transaction).order_by(Transaction.id)).all()
        if row.encrypted_payload is not None
    ]
    reserved_ids = _reserved_transaction_ids(session)
    existing_pairs = {
        (link.transaction_a_id, link.transaction_b_id)
        for link in session.exec(select(TransactionLink)).all()
    }
    buckets: dict[tuple[str, Decimal], list[TransactionData]] = {}
    for tx in transactions:
        if (
            tx.id is None
            or tx.id in reserved_ids
            or tx.account_id not in accounts
            or tx.amount == 0
        ):
            continue
        key = (tx.currency.upper(), abs(tx.amount).quantize(Decimal("0.01")))
        buckets.setdefault(key, []).append(tx)

    candidates: list[MatchCandidate] = []
    for bucket in buckets.values():
        for first, second in combinations(bucket, 2):
            if first.account_id == second.account_id or first.id is None or second.id is None:
                continue
            lo, hi = min(first.id, second.id), max(first.id, second.id)
            if (lo, hi) in existing_pairs:
                continue
            candidate = _make_candidate(
                first,
                second,
                accounts[first.account_id],
                accounts[second.account_id],
            )
            if candidate is not None:
                candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item.rule_score,
            max(item.transaction_a.booking_date, item.transaction_b.booking_date),
        ),
        reverse=True,
    )
    return candidates[: max(0, limit)]


def _make_candidate(
    first: TransactionData,
    second: TransactionData,
    account_a: AccountData | Account,
    account_b: AccountData | Account,
) -> MatchCandidate | None:
    if first.id is not None and second.id is not None and first.id > second.id:
        first, second = second, first
        account_a, account_b = account_b, account_a
    settings = get_settings()
    day_gap = abs((first.booking_date - second.booking_date).days)
    if day_gap > settings.match_date_window_days:
        return None
    if first.currency.upper() != second.currency.upper():
        return None
    if abs(abs(first.amount) - abs(second.amount)) >= Decimal("0.02"):
        return None

    evidence = ["same_amount"]
    score = 0.40
    if day_gap == 0:
        score += 0.25
        evidence.append("same_day")
    elif day_gap == 1:
        score += 0.18
        evidence.append("one_day_apart")
    else:
        score += 0.08
        evidence.append(f"{day_gap}_days_apart")
    if first.amount * second.amount < 0:
        score += 0.17
        evidence.append("opposite_signs")
    else:
        score += 0.03
        evidence.append("same_sign")
    if _references_account(first, account_b):
        score += 0.18
        evidence.append("a_mentions_owned_account_b")
    if _references_account(second, account_a):
        score += 0.18
        evidence.append("b_mentions_owned_account_a")

    return MatchCandidate(
        transaction_a=first,
        transaction_b=second,
        account_a=account_a,
        account_b=account_b,
        rule_score=min(score, 1.0),
        evidence=tuple(evidence),
    )


def _references_account(tx: TransactionData, account: AccountData | Account) -> bool:
    text = _normalize_reference(f"{tx.counterparty or ''} {tx.raw_text}")
    iban = _normalize_reference(account.iban or "")
    if len(iban) >= 12 and iban in text:
        return True
    name = _normalize_reference(account.name)
    return len(name) >= 5 and name in text


def _normalize_reference(value: str) -> str:
    return _NON_ALNUM_RE.sub("", value.upper())


def _high_confidence_rule_prediction(
    candidate: MatchCandidate,
) -> MatchPrediction | None:
    evidence = set(candidate.evidence)
    references_owned_account = bool(
        {"a_mentions_owned_account_b", "b_mentions_owned_account_a"} & evidence
    )
    close_in_time = "same_day" in evidence or "one_day_apart" in evidence
    if references_owned_account and close_in_time and "opposite_signs" in evidence:
        return MatchPrediction(
            is_match=True,
            relationship="internal_transfer",
            transfer_leg="both",
            confidence=0.99,
            reason="Exact amount, close dates and explicit reference to another owned account",
        )
    return None


def _get_match_agent():
    settings = get_settings()
    key = f"{settings.ollama_base_url}|{settings.ollama_model}"
    if _match_agent_cache["key"] == key and _match_agent_cache["agent"] is not None:
        return _match_agent_cache["agent"]
    model = ChatOllama(
        base_url=settings.ollama_base_url.rstrip("/"),
        model=settings.ollama_model,
        temperature=0,
        num_predict=get_settings().ollama_output_tokens,
    )
    agent = create_agent(
        model,
        tools=[],
        system_prompt=_match_system_prompt(),
        response_format=MatchPrediction,
    )
    _match_agent_cache["key"] = key
    _match_agent_cache["agent"] = agent
    return agent


def _match_system_prompt() -> str:
    return (
        "You decide whether two records from different financial accounts owned by the same user "
        "represent one economic movement. Be conservative: an equal amount and nearby date alone "
        "are never sufficient. Use counterparty, purpose, account type, account references and event "
        "context as corroborating evidence. Choose internal_transfer when money moved between owned "
        "accounts, normally with opposite signs. Choose account_funding when one record is the funding "
        "or settlement leg of a wallet, card or investment record; same signs are possible but require "
        "clear textual or event evidence. Choose not_related for coincidental amounts, unrelated merchants "
        "or uncertainty. For internal_transfer use transfer_leg=both. For account_funding identify only "
        "the funding record as a or b. Never infer a relationship from provider identity alone. "
        "Write the reason in concise German."
    )


def _predict(agent: Any, candidate: MatchCandidate) -> MatchPrediction | None:
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": _candidate_message(candidate)}]}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local model failed while matching transactions: %s", exc)
        return None
    structured = result.get("structured_response") if isinstance(result, dict) else None
    if isinstance(structured, MatchPrediction):
        return structured
    if isinstance(structured, dict):
        try:
            return MatchPrediction.model_validate(structured)
        except Exception:  # noqa: BLE001
            return None
    return None


def _candidate_message(candidate: MatchCandidate) -> str:
    return (
        f"rule_score: {candidate.rule_score:.2f}\n"
        f"evidence: {', '.join(candidate.evidence)}\n\n"
        f"record_a:\n{_transaction_context(candidate.transaction_a, candidate.account_a)}\n\n"
        f"record_b:\n{_transaction_context(candidate.transaction_b, candidate.account_b)}"
    )


def _transaction_context(
    tx: TransactionData, account: AccountData | Account
) -> str:
    payload = scrub_pii(json.dumps(tx.raw_payload or {}, ensure_ascii=False))[:1200]
    return (
        f"account_name: {scrub_pii(account.name)}\n"
        f"account_source: {account.source.value}\n"
        f"account_type: {account.account_type.value}\n"
        f"booking_date: {tx.booking_date.isoformat()}\n"
        f"amount: {tx.amount} {tx.currency}\n"
        f"counterparty: {scrub_pii(tx.counterparty or '') or '(unknown)'}\n"
        f"purpose: {scrub_pii(tx.raw_text) or '(empty)'}\n"
        f"event_context: {payload or '(none)'}"
    )


def _transfer_transaction_id(
    prediction: MatchPrediction, tx_a: TransactionData, tx_b: TransactionData
) -> int | None:
    if prediction.transfer_leg == "a":
        return tx_a.id
    if prediction.transfer_leg == "b":
        return tx_b.id
    return None


def confirm_link(session: Session, link: TransactionLink, dek: bytes) -> None:
    first = session.get(Transaction, link.transaction_a_id)
    second = session.get(Transaction, link.transaction_b_id)
    if first is None or second is None:
        return
    update_link_payload(
        session, link, dek, status=LinkStatus.CONFIRMED,
        evaluated_by=LinkEvaluatedBy.MANUAL,
    )
    _apply_confirmed_kinds(session, link, first, second, dek)
    session.commit()


def reject_link(session: Session, link: TransactionLink, dek: bytes) -> None:
    update_link_payload(
        session, link, dek, status=LinkStatus.REJECTED,
        evaluated_by=LinkEvaluatedBy.MANUAL,
    )
    for transaction_id in (link.transaction_a_id, link.transaction_b_id):
        tx = session.get(Transaction, transaction_id)
        if tx is not None:
            private = decode_transaction(tx, dek)
            if private.kind == TransactionKind.TRANSFER:
                update_transaction_payload(
                    session, tx, dek, kind=_default_kind(private)
                )
    session.commit()


def _apply_confirmed_kinds(
    session: Session,
    link: TransactionLink,
    first: Transaction,
    second: Transaction,
    dek: bytes,
) -> None:
    first_private = decode_transaction(first, dek)
    second_private = decode_transaction(second, dek)
    if link.link_type == LinkType.INTERNAL_TRANSFER:
        update_transaction_payload(session, first, dek, kind=TransactionKind.TRANSFER)
        update_transaction_payload(session, second, dek, kind=TransactionKind.TRANSFER)
        return
    transfer_id = link.transfer_transaction_id
    if transfer_id is None:
        transfer_id = _infer_funding_leg(session, first_private, second_private)
        link.transfer_transaction_id = transfer_id
        session.add(link)
    for tx in (first, second):
        private = first_private if tx.id == first.id else second_private
        update_transaction_payload(
            session,
            tx,
            dek,
            kind=(
                TransactionKind.TRANSFER
                if tx.id == transfer_id
                else _default_kind(private)
            ),
        )


def _infer_funding_leg(
    session: Session, first: TransactionData, second: TransactionData
) -> int | None:
    if first.amount * second.amount < 0:
        return first.id if first.amount < 0 else second.id
    first_account = session.get(Account, first.account_id)
    second_account = session.get(Account, second.account_id)
    dek = vault_session.get_dek()
    if (
        first_account is None
        or second_account is None
        or dek is None
        or first_account.encrypted_payload is None
        or second_account.encrypted_payload is None
    ):
        return None
    first_private = decode_account(first_account, dek)
    second_private = decode_account(second_account, dek)
    first_is_checking = first_private.account_type == AccountType.CHECKING
    second_is_checking = second_private.account_type == AccountType.CHECKING
    if first_is_checking != second_is_checking:
        return first.id if first_is_checking else second.id
    return None


def _default_kind(tx: TransactionData) -> TransactionKind:
    if tx.amount > 0:
        return TransactionKind.INCOME
    if tx.amount < 0:
        return TransactionKind.EXPENSE
    return TransactionKind.IGNORE


def _reserved_transaction_ids(session: Session) -> set[int]:
    reserved: set[int] = set()
    links = session.exec(
        select(TransactionLink).where(
            col(TransactionLink.status).in_([LinkStatus.CONFIRMED, LinkStatus.SUGGESTED])
        )
    ).all()
    for link in links:
        reserved.update((link.transaction_a_id, link.transaction_b_id))
    return reserved
