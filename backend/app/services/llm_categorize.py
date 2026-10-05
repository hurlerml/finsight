"""Background LLM categorization via LangChain + local Ollama."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
from app.models import Account, Category, Transaction
from app.models.enums import AccountSource, CategorizedBy, TransactionKind
from app.services.secure_accounts import AccountData, decode_account
from app.services.secure_labels import CategoryData, load_categories as load_secure_categories
from app.services.secure_transactions import (
    TransactionData,
    decode_transaction,
    load_transactions,
    update_transaction_payload,
)
from app.services.vault_session import vault_session
from app.services.embeddings import schedule_transaction_embedding_backfill

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.55
WEB_RESEARCH_CONFIDENCE = 0.75
RECONNECT_SECONDS = 10.0
IDLE_SLEEP_SECONDS = 3.0
OLLAMA_PROBE_TIMEOUT = 5.0
LAST_DONE_MAX = 5

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)
_LONG_DIGITS_RE = re.compile(r"\b\d{6,}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.\w+\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,}[\s-]?\d{3,}\b")

Phase = Literal["idle", "running", "researching", "waiting_ollama"]


class CategoryPrediction(BaseModel):
    category_slug: str = Field(description="One of the allowed category slugs")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence between 0 and 1")
    # Some local models omit the explanatory field even when the category and
    # confidence are valid. Treat that as a valid classification instead of
    # dropping the booking on a schema error.
    reason: str = Field(default="", description="Short reason without personal data")


@dataclass
class StatusCurrent:
    id: int
    booking_date: str
    counterparty: str | None
    amount: str


@dataclass
class StatusDone:
    id: int
    slug: str
    confidence: float


@dataclass
class CategorizeStatus:
    ollama_configured: bool = False
    ollama_reachable: bool = False
    phase: Phase = "idle"
    queue_remaining: int = 0
    queue_total: int = 0
    queue_processed: int = 0
    current: StatusCurrent | None = None
    last_done: list[StatusDone] = field(default_factory=list)
    llm_applied_session: int = 0
    message: str | None = None


_status = CategorizeStatus()
_status_lock = threading.Lock()
_skip_ids: set[int] = set()
_agent_cache: dict[str, Any] = {"key": None, "agent": None, "slugs": None}
_classifier_cache: dict[str, Any] = {"key": None, "model": None}
_last_embedding_trigger = 0
_classification_revision = 0

CATEGORY_GUIDANCE = {
    "shopping": (
        "Purchase of physical goods such as clothing, electronics, furniture, household items, "
        "cosmetics or general online retail. The sales channel alone does not prove Shopping. "
        "Do not use it for admission, events, entertainment, hobbies, media access or travel."
    ),
    "leisure": (
        "Leisure experiences and culture: cinema, theatre, concerts, museums, event tickets, "
        "amusement venues, games, hobbies, sports activities, books and paid media. Use this only "
        "when the booking identifies an experience, activity or cultural/media purpose; a general "
        "retailer without item detail remains Shopping."
    ),
}


def get_categorize_status() -> CategorizeStatus:
    with _status_lock:
        return CategorizeStatus(
            ollama_configured=_status.ollama_configured,
            ollama_reachable=_status.ollama_reachable,
            phase=_status.phase,
            queue_remaining=_status.queue_remaining,
            queue_total=_status.queue_total,
            queue_processed=_status.queue_processed,
            current=_status.current,
            last_done=list(_status.last_done),
            llm_applied_session=_status.llm_applied_session,
            message=_status.message,
        )


def _update_status(**kwargs: Any) -> None:
    with _status_lock:
        for key, value in kwargs.items():
            setattr(_status, key, value)


def classification_revision() -> int:
    """Return the generation of the active model and category semantics."""
    with _status_lock:
        return _classification_revision


def invalidate_classification_context() -> int:
    """Invalidate in-flight results after model or category semantics change."""
    global _classification_revision
    with _status_lock:
        _classification_revision += 1
        return _classification_revision


def retry_transactions(transaction_ids: list[int]) -> None:
    """Make previously skipped transactions eligible for the background loop again."""
    with _status_lock:
        _skip_ids.difference_update(transaction_ids)
        _status.queue_total = len(transaction_ids)
        _status.queue_processed = 0


def scrub_pii(text: str) -> str:
    cleaned = _IBAN_RE.sub(" ", text)
    cleaned = _EMAIL_RE.sub(" ", cleaned)
    cleaned = _PHONE_RE.sub(" ", cleaned)
    cleaned = _LONG_DIGITS_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _debug_model_result(label: str, tx_id: int, started: float, result: Any) -> None:
    """Log bounded, scrubbed model diagnostics when explicitly enabled."""
    if not get_settings().debug_llm:
        return
    messages = result.get("messages", []) if isinstance(result, dict) else []
    tool_names: list[str] = []
    snippets: list[str] = []
    for message in messages:
        name = getattr(message, "name", None)
        if name:
            tool_names.append(str(name))
        calls = getattr(message, "tool_calls", None)
        if calls:
            tool_names.extend(
                str(call.get("name", "tool"))
                for call in calls
                if isinstance(call, dict)
            )
        content = getattr(message, "content", None)
        if isinstance(message, AIMessage) and isinstance(content, str) and content.strip():
            snippets.append(scrub_pii(content)[:800])
    structured = result.get("structured_response") if isinstance(result, dict) else None
    if structured is not None:
        snippets.append(scrub_pii(str(structured))[:800])
    logger.info(
        "LLM debug tx=%s step=%s duration_ms=%d tools=%s output=%s",
        tx_id,
        label,
        int((time.perf_counter() - started) * 1000),
        ",".join(tool_names) or "-",
        " | ".join(snippets[-2:]) or "<no text>",
    )


def search_web_safely(query: str) -> str:
    safe = scrub_pii(query)
    if not safe:
        return "no safe query"
    debug = get_settings().debug_llm
    started = time.perf_counter()
    if debug:
        logger.info("LLM debug web_search started query=%s", safe[:240])
    try:
        from ddgs import DDGS

        # Never let an optional merchant lookup block the categorization worker.
        # DDGS forwards this timeout to its HTTP client; a failed lookup simply
        # falls back to the model's local classification.
        with DDGS(timeout=8) as ddgs:
            hits = list(ddgs.text(safe, max_results=5))
    except Exception as exc:  # noqa: BLE001
        logger.warning("web_search failed: %s", exc)
        if debug:
            logger.info(
                "LLM debug web_search finished duration_ms=%d hits=0",
                int((time.perf_counter() - started) * 1000),
            )
        return f"search failed: {exc}"
    if not hits:
        if debug:
            logger.info(
                "LLM debug web_search finished duration_ms=%d hits=0",
                int((time.perf_counter() - started) * 1000),
            )
        return "no results"
    if debug:
        logger.info(
            "LLM debug web_search finished duration_ms=%d hits=%d",
            int((time.perf_counter() - started) * 1000),
            len(hits),
        )
    lines: list[str] = []
    for hit in hits:
        title = scrub_pii(str(hit.get("title") or ""))
        body = scrub_pii(str(hit.get("body") or hit.get("snippet") or ""))
        if title or body:
            lines.append(f"- {title}: {body}".strip(": "))
    return "\n".join(lines) if lines else "no results"


@tool
def web_search(query: str) -> str:
    """Search the web for a merchant or brand name when the booking text is unclear.
    Only pass merchant/brand/purpose keywords — never IBANs, account numbers, emails, phones, or person names.
    """
    return search_web_safely(query)


def _count_pending(session: Session) -> int:
    dek = vault_session.get_dek()
    if dek is None:
        return 0
    return sum(
        1
        for tx in load_transactions(session, dek)
        if tx.id not in _skip_ids
        and tx.category_id is None
        and tx.kind in (TransactionKind.EXPENSE, TransactionKind.INCOME)
    )


def _next_transaction(session: Session) -> Transaction | None:
    dek = vault_session.get_dek()
    if dek is None:
        return None
    pending = [
        tx
        for tx in load_transactions(session, dek)
        if tx.id not in _skip_ids
        and tx.category_id is None
        and tx.kind in (TransactionKind.EXPENSE, TransactionKind.INCOME)
    ]
    return session.get(Transaction, pending[0].id) if pending else None


def _load_categories(session: Session) -> list[CategoryData]:
    dek = vault_session.get_dek()
    if dek is None:
        return []
    return sorted(load_secure_categories(session, dek), key=lambda item: item.slug)


def _system_prompt(
    categories: list[CategoryData],
    *,
    web_search_enabled: bool = True,
) -> str:
    lines = [
        f"- {c.slug}: {c.name}"
        + (
            f" — {c.description}"
            if c.description
            else f" — {CATEGORY_GUIDANCE[c.slug]}"
            if c.slug in CATEGORY_GUIDANCE
            else ""
        )
        for c in categories
    ]
    allowed = "\n".join(lines)
    web_guidance = (
        "Use web search when the merchant's business or the purpose is unclear and that "
        "uncertainty could change the category. Before returning confidence below 0.75, choosing "
        "'other', or guessing between 'shopping' and 'leisure', research the merchant unless the "
        "booking text itself already identifies the purchased product or activity. Treat search "
        "results as evidence, not certainty. Search queries must contain only "
        "merchant/brand/purpose keywords — never IBANs, account numbers, emails, phones, or "
        "person names.\n"
        if web_search_enabled
        else "Web research is disabled. Categorize only from the supplied local context.\n"
    )
    return (
        "You categorize German bank booking texts into exactly one allowed category_slug.\n"
        "Allowed slugs:\n"
        f"{allowed}\n\n"
        f"{web_guidance}"
        "Prefer slug 'other' over inventing a new slug.\n"
        "Treat account metadata and event_type as authoritative context. For a "
        "Trade Republic broker-cash account, a company name in a TRADING_, SSP_, "
        "or INTEREST_ event describes an investment, corporate action, or interest "
        "payment and belongs to 'savings'; it is not a subscription or ordinary "
        "purchase. CARD_TRANSACTION events are ordinary card purchases and may be "
        "categorized by their merchant.\n"
        "Do not invent personal data. Return only a brief one-sentence rationale, not hidden chain-of-thought. "
        "Confidence must be between 0 and 1."
    )


def _used_web_search(result: dict[str, Any]) -> bool:
    return any(
        isinstance(message, ToolMessage) and message.name == "web_search"
        for message in result.get("messages", [])
    )


def _needs_web_research(
    prediction: CategoryPrediction | None,
    result: dict[str, Any] | None = None,
) -> bool:
    if prediction is None:
        # A missing structured result is itself uncertainty. Give the worker
        # one evidence-backed retry instead of permanently skipping the row.
        return True
    return (
        prediction.confidence < WEB_RESEARCH_CONFIDENCE
        or prediction.category_slug in {"shopping", "leisure", "other"}
    )


def _get_structured_classifier(categories: list[CategoryData | Category]):
    """Return a no-tool structured classifier for reliable final JSON output."""

    settings = get_settings()
    definitions = tuple(
        (
            c.slug,
            getattr(c, "name", ""),
            getattr(c, "description", ""),
        )
        for c in categories
    )
    slugs = tuple(item[0] for item in definitions)
    key = f"{settings.ollama_base_url}|{settings.ollama_model}|structured|{definitions}"
    if _classifier_cache["key"] == key and _classifier_cache["model"] is not None:
        return _classifier_cache["model"], set(slugs)
    model = ChatOllama(
        base_url=settings.ollama_base_url.rstrip("/"),
        model=settings.ollama_model,
        temperature=0,
        reasoning=False,
        num_predict=512,
    ).with_structured_output(CategoryPrediction, method="json_schema")
    _classifier_cache["key"] = key
    _classifier_cache["model"] = model
    return model, set(slugs)


def _get_agent(
    categories: list[CategoryData | Category],
    *,
    web_search_enabled: bool = True,
):
    settings = get_settings()
    definitions = tuple(
        (
            c.slug,
            getattr(c, "name", ""),
            getattr(c, "description", ""),
        )
        for c in categories
    )
    slugs = tuple(item[0] for item in definitions)
    key = (
        f"{settings.ollama_base_url}|{settings.ollama_model}|"
        f"web={web_search_enabled}|{definitions}"
    )
    if _agent_cache["key"] == key and _agent_cache["agent"] is not None:
        return _agent_cache["agent"], set(slugs)

    model = ChatOllama(
        base_url=settings.ollama_base_url.rstrip("/"),
        model=settings.ollama_model,
        temperature=0,
        # Categorization needs a short structured result. Gemma/Qwen thinking
        # models can otherwise spend the entire small output budget in their
        # hidden reasoning channel and return no category at all.
        reasoning=False,
        # Leave enough room for a structured answer and (when requested) a
        # short evidence-backed tool call. Reasoning is disabled above, so
        # this remains bounded without truncating the final JSON response.
        num_predict=512,
    )
    agent = create_agent(
        model,
        tools=[web_search] if web_search_enabled else [],
        system_prompt=_system_prompt(
            categories,
            web_search_enabled=web_search_enabled,
        ),
        response_format=CategoryPrediction,
    )
    _agent_cache["key"] = key
    _agent_cache["agent"] = agent
    _agent_cache["slugs"] = set(slugs)
    return agent, set(slugs)


def probe_ollama() -> bool:
    settings = get_settings()
    if not settings.ollama_configured:
        return False
    url = settings.ollama_base_url.rstrip("/") + "/api/tags"
    try:
        with httpx.Client(timeout=OLLAMA_PROBE_TIMEOUT) as client:
            res = client.get(url)
            if res.status_code >= 500:
                return False
            if res.status_code < 400:
                models = [
                    str(item.get("name"))
                    for item in res.json().get("models", [])
                    if item.get("name") and "embedding" not in (item.get("capabilities") or [])
                ]
                return bool(settings.ollama_model in models)
            return False
    except Exception:  # noqa: BLE001
        return False


def _is_connection_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, OSError)):
        return True
    return any(
        needle in text
        for needle in (
            "connection refused",
            "connect error",
            "failed to connect",
            "name or service not known",
            "nodename nor servname",
            "timed out",
            "connection reset",
        )
    )


def _is_model_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "model" in text and ("not found" in text or "404" in text or "does not exist" in text)


def _extract_prediction(result: dict[str, Any]) -> CategoryPrediction | None:
    structured = result.get("structured_response")
    if isinstance(structured, CategoryPrediction):
        return structured
    if isinstance(structured, dict):
        try:
            return CategoryPrediction.model_validate(structured)
        except Exception:  # noqa: BLE001
            return None
    return None


def _coerce_prediction(result: Any) -> CategoryPrediction | None:
    if isinstance(result, CategoryPrediction):
        return result
    if isinstance(result, dict):
        try:
            return CategoryPrediction.model_validate(result)
        except Exception:  # noqa: BLE001
            return _extract_prediction(result)
    return None


def _event_type(tx: TransactionData | Transaction) -> str:
    payload = tx.raw_payload or {}
    tr_payload = payload.get("traderepublic")
    if not isinstance(tr_payload, dict):
        return ""
    return scrub_pii(str(tr_payload.get("eventType") or ""))


def _merchant_search_query(tx: TransactionData) -> str:
    """Extract a compact merchant query from noisy card descriptors."""
    text = tx.counterparty or tx.raw_text or ""
    text = re.sub(r"\b(?:EUR|€)\s*[\d.,-]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[\d.,-]+\s*(?:EUR|€)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:Umsatz|vom|MC|Hauptkarte)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", " ", text)
    # Provider descriptors often append a country code (e.g. PRT) and repeat
    # the merchant. Keep the first occurrence of each meaningful token.
    ignored = {
        "PRT", "PT", "DEU", "DE", "ESP", "FRA", "ITA", "GBR", "USA",
        "IBAN", "SEPA", "KARTE", "CARD",
    }
    ignored_keys = {item.casefold() for item in ignored}
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-zÀ-ÿ0-9&'-]+", text):
        key = token.casefold()
        # Amount fragments, dates and transaction numbers are not useful for
        # merchant discovery. Require a meaningful alphabetic component.
        if (
            len(re.findall(r"[A-Za-zÀ-ÿ]", token)) < 2
            or key in ignored_keys
            or key in seen
        ):
            continue
        seen.add(key)
        tokens.append(token)
        if len(tokens) >= 8:
            break
    return scrub_pii(" ".join(tokens))[:160]


def _account_category_override(
    account: AccountData | Account | None, tx: TransactionData | Transaction
) -> str | None:
    """Protect unambiguous broker events from merchant-name misclassification."""
    if account is None or account.source != AccountSource.TRADE_REPUBLIC:
        return None
    event_type = _event_type(tx).upper()
    if event_type.startswith(("TRADING_", "SSP_", "INTEREST_")):
        return "savings"
    return None


def _user_message(
    tx: TransactionData | Transaction, account: AccountData | Account | None
) -> str:
    purpose = scrub_pii(tx.raw_text or "")
    counterparty = scrub_pii(tx.counterparty or "") if tx.counterparty else ""
    account_name = scrub_pii(account.name) if account else ""
    account_source = account.source.value if account else "unknown"
    account_type = account.account_type.value if account else "unknown"
    event_type = _event_type(tx)
    return (
        f"account_name: {account_name or '(unknown)'}\n"
        f"account_source: {account_source}\n"
        f"account_type: {account_type}\n"
        f"event_type: {event_type or '(unknown)'}\n"
        f"booking_date: {tx.booking_date.isoformat()}\n"
        f"amount: {tx.amount} {tx.currency}\n"
        f"counterparty: {counterparty or '(unknown)'}\n"
        f"purpose: {purpose or '(empty)'}\n"
        "Pick the best category_slug."
    )


def process_next() -> Literal["idle", "done", "retry", "skipped"]:
    """Process one uncategorized transaction. Safe to call from a worker thread."""
    settings = get_settings()
    if not settings.ollama_configured:
        _update_status(
            ollama_configured=False,
            ollama_reachable=False,
            phase="idle",
            queue_remaining=0,
            current=None,
            message=None,
        )
        return "idle"

    with Session(engine) as session:
        pending = _count_pending(session)
        with _status_lock:
            if pending > 0 and (
                _status.queue_total == 0
                or _status.queue_processed >= _status.queue_total
                or _status.queue_remaining == 0
            ):
                _status.queue_total = pending
                _status.queue_processed = 0
            _status.ollama_configured = True
            _status.queue_remaining = pending
        if pending == 0:
            _update_status(phase="idle", current=None, message=None, ollama_reachable=probe_ollama())
            return "idle"

        if not probe_ollama():
            _update_status(
                ollama_reachable=False,
                phase="waiting_ollama",
                current=None,
                message="Ollama unreachable — retrying every 10s",
            )
            return "retry"

        tx = _next_transaction(session)
        if tx is None or tx.id is None:
            _update_status(phase="idle", current=None, queue_remaining=0, message=None)
            return "idle"
        dek = vault_session.get_dek()
        if dek is None:
            return "retry"
        tx_view = decode_transaction(tx, dek)

        context_revision = classification_revision()
        categories = _load_categories(session)
        account = session.get(Account, tx.account_id)
        dek = vault_session.get_dek()
        account_view = (
            decode_account(account, dek)
            if account is not None
            and dek is not None
            and account.encrypted_payload is not None
            else account
        )
        slug_to_id = {c.slug: c.id for c in categories if c.id is not None}
        _update_status(
            ollama_reachable=True,
            phase="running",
            message=None,
            current=StatusCurrent(
                id=tx.id,
                booking_date=tx_view.booking_date.isoformat(),
                counterparty=tx_view.counterparty,
                amount=str(tx_view.amount),
            ),
        )

        try:
            allowed = set(slug_to_id)
            override = _account_category_override(account_view, tx_view)
            if override in allowed:
                prediction = CategoryPrediction(
                    category_slug=override,
                    confidence=1.0,
                    reason="Unambiguous broker event type and account context",
                )
            else:
                classifier, allowed = _get_structured_classifier(categories)
                user_message = _user_message(tx_view, account_view)
                model_started = time.perf_counter()
                if settings.debug_llm:
                    logger.info("LLM debug tx=%s step=classify input=%s", tx.id, scrub_pii(user_message)[:1200])
                web_search_enabled = settings.categorization_web_search_enabled
                result = classifier.invoke(
                    [
                        {
                            "role": "system",
                            "content": _system_prompt(
                                categories,
                                web_search_enabled=web_search_enabled,
                            ),
                        },
                        {"role": "user", "content": user_message},
                    ]
                )
                prediction = _coerce_prediction(result)
                if settings.debug_llm:
                    logger.info(
                        "LLM debug tx=%s step=classify duration_ms=%d output=%s",
                        tx.id,
                        int((time.perf_counter() - model_started) * 1000),
                        scrub_pii(str(result))[:800] if result is not None else "<none>",
                    )
                needs_research = (
                    web_search_enabled and _needs_web_research(prediction)
                )
                if settings.debug_llm:
                    logger.info(
                        "LLM debug tx=%s decision category=%s confidence=%s needs_web_research=%s",
                        tx.id,
                        prediction.category_slug if prediction else "<none>",
                        prediction.confidence if prediction else "<none>",
                        needs_research,
                    )
                # Re-read the mutable preference immediately before the only
                # outbound step, so disabling it also stops the next lookup in
                # a categorization that is already running.
                if (
                    needs_research
                    and settings.categorization_web_search_enabled
                ):
                    event_type = _event_type(tx_view)
                    # Never send personal transfer names to a public search
                    # provider. Merchant research is useful for card/trade
                    # descriptions, not for BANK_TRANSACTION person names.
                    search_query = "" if event_type.startswith(("BANK_TRANSACTION", "PAYMENT_INBOUND")) else _merchant_search_query(tx_view)
                    research_started = time.perf_counter()
                    if search_query:
                        _update_status(
                            phase="researching",
                            message="Web search in progress …",
                        )
                    search_result = web_search.invoke(search_query) if search_query else "no safe merchant query"
                    if settings.debug_llm:
                        logger.info(
                            "LLM debug tx=%s step=web_search duration_ms=%d query=%s result=%s",
                            tx.id,
                            int((time.perf_counter() - research_started) * 1000),
                            search_query,
                            scrub_pii(str(search_result))[:800],
                        )
                    researched_prediction = None
                    researched = None
                    if search_query:
                        researched = classifier.invoke(
                            [
                                {
                                    "role": "system",
                                    "content": _system_prompt(
                                        categories,
                                        web_search_enabled=web_search_enabled,
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        f"{user_message}\n\n"
                                        "A web search was requested because the first result was uncertain. "
                                        "Use the following search evidence, then return the final structured "
                                        "prediction. Treat it as evidence, not certainty.\n\n"
                                        f"Web search evidence:\n{str(search_result)[:4000]}"
                                    ),
                                },
                            ]
                        )
                        researched_prediction = _coerce_prediction(researched)
                        _update_status(phase="running", message=None)
                    if settings.debug_llm:
                        logger.info(
                            "LLM debug tx=%s step=research duration_ms=%d output=%s",
                            tx.id,
                            int((time.perf_counter() - research_started) * 1000),
                            scrub_pii(str(researched))[:800] if researched is not None else "<none>",
                        )
                    if researched_prediction is not None:
                        prediction = researched_prediction
        except Exception as exc:  # noqa: BLE001
            if _is_connection_error(exc) or _is_model_unavailable(exc):
                logger.warning("Ollama unavailable during categorize: %s", exc)
                _agent_cache["key"] = None
                _agent_cache["agent"] = None
                _classifier_cache["key"] = None
                _classifier_cache["model"] = None
                msg = (
                    f"Ollama model '{settings.ollama_model}' not found — retrying every 10s"
                    if _is_model_unavailable(exc)
                    else "Ollama unreachable — retrying every 10s"
                )
                _update_status(
                    ollama_reachable=False,
                    phase="waiting_ollama",
                    current=None,
                    message=msg,
                )
                return "retry"
            logger.exception("LLM categorize failed for tx %s", tx.id)
            _skip_ids.add(tx.id)
            _update_status(
                phase="running",
                message=None,
                current=None,
                queue_remaining=_count_pending(session),
                queue_processed=min(_status.queue_processed + 1, _status.queue_total),
            )
            return "skipped"

        if (
            prediction is None
            or prediction.category_slug not in allowed
            or prediction.confidence < MIN_CONFIDENCE
        ):
            logger.info(
                "Skipping tx %s: prediction=%s",
                tx.id,
                prediction.model_dump() if prediction else None,
            )
            _skip_ids.add(tx.id)
            _update_status(
                current=None,
                queue_remaining=_count_pending(session),
                queue_processed=min(_status.queue_processed + 1, _status.queue_total),
            )
            return "skipped"

        category_id = slug_to_id.get(prediction.category_slug)
        if category_id is None:
            _skip_ids.add(tx.id)
            _update_status(
                current=None,
                queue_remaining=_count_pending(session),
                queue_processed=min(_status.queue_processed + 1, _status.queue_total),
            )
            return "skipped"

        if classification_revision() != context_revision:
            _update_status(
                current=None,
                message=None,
                queue_remaining=_count_pending(session),
            )
            return "stale"

        update_transaction_payload(
            session,
            tx,
            dek,
            category_id=category_id,
            categorized_by=CategorizedBy.LLM,
            categorization_reason=(
                scrub_pii(prediction.reason or "").strip()[:600] or None
            ),
        )
        session.commit()

        # A mutation can land between the generation check and commit. Remove
        # that stale decision so the next pass uses the new model/category context.
        if classification_revision() != context_revision:
            update_transaction_payload(
                session,
                tx,
                dek,
                category_id=None,
                categorized_by=None,
                categorization_reason=None,
            )
            session.commit()
            # Preserve rule precedence if the context mutation completed while
            # this older model call was still in flight.
            from app.services.categorize import apply_rules

            apply_rules(session, [tx.id])
            with _status_lock:
                _skip_ids.discard(tx.id)
            _update_status(
                current=None,
                message=None,
                queue_remaining=_count_pending(session),
            )
            return "stale"

        with _status_lock:
            _status.llm_applied_session += 1
            _status.queue_processed = min(
                _status.queue_processed + 1, _status.queue_total
            )
            _status.last_done = (
                [StatusDone(id=tx.id, slug=prediction.category_slug, confidence=prediction.confidence)]
                + _status.last_done
            )[:LAST_DONE_MAX]
            _status.current = None
            _status.queue_remaining = _count_pending(session)
            _status.phase = "running" if _status.queue_remaining else "idle"
            _status.message = None

            global _last_embedding_trigger
            if _status.queue_remaining == 0 and _status.llm_applied_session > _last_embedding_trigger:
                _last_embedding_trigger = _status.llm_applied_session
                schedule_transaction_embedding_backfill(dek)

        return "done"


async def llm_loop() -> None:
    logger.info("LLM categorize loop started")
    while True:
        try:
            outcome = await asyncio.to_thread(process_next)
            if outcome == "retry":
                await asyncio.sleep(RECONNECT_SECONDS)
            elif outcome == "idle":
                await asyncio.sleep(IDLE_SLEEP_SECONDS)
            elif outcome == "skipped":
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            logger.info("LLM categorize loop stopped")
            raise
        except Exception:
            logger.exception("LLM categorize loop error")
            await asyncio.sleep(RECONNECT_SECONDS)
