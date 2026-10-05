"""Rule-based categorization (keyword / regex)."""

from __future__ import annotations

import re

from sqlmodel import Session, col, select

from app.models import Transaction
from app.models.enums import CategorizedBy, TransactionKind
from app.services.secure_labels import load_rules
from app.services.secure_transactions import decode_transaction, update_transaction_payload
from app.services.vault_session import vault_session


def category_impact(
    session: Session,
    dek: bytes,
    *,
    category_id: int | None = None,
) -> dict[str, int]:
    """Count category assignments after decrypting them in the unlocked backend."""
    assigned = 0
    automatic = 0
    manual = 0
    uncategorized = 0
    for row in session.exec(select(Transaction).order_by(Transaction.id)).all():
        private = decode_transaction(row, dek)
        if private.kind not in (TransactionKind.EXPENSE, TransactionKind.INCOME):
            continue
        if private.category_id is None:
            uncategorized += 1
        if category_id is not None and private.category_id != category_id:
            continue
        if private.category_id is not None:
            assigned += 1
        if private.categorized_by == CategorizedBy.MANUAL:
            manual += 1
        elif private.category_id is not None:
            automatic += 1
    return {
        "assigned": assigned,
        "automatic": automatic,
        "manual": manual,
        "uncategorized": uncategorized,
    }


def apply_rules(session: Session, transaction_ids: list[int] | None = None) -> int:
    if transaction_ids == []:
        return 0
    dek = vault_session.get_dek()
    if dek is None:
        return 0
    rules = load_rules(session, dek, active_only=True)
    if not rules:
        return 0

    stmt = select(Transaction)
    if transaction_ids is not None:
        stmt = stmt.where(col(Transaction.id).in_(transaction_ids))

    stored_txs = session.exec(stmt).all()
    updated = 0
    for tx in stored_txs:
        private = decode_transaction(tx, dek)
        if private.categorized_by == CategorizedBy.MANUAL or private.kind not in (
            TransactionKind.EXPENSE,
            TransactionKind.INCOME,
        ):
            continue
        hay = f"{private.raw_text} {private.counterparty or ''}"
        for rule in rules:
            if _matches(rule.pattern, hay, rule.is_regex):
                if (
                    private.category_id != rule.category_id
                    or private.categorized_by != CategorizedBy.RULE
                ):
                    update_transaction_payload(
                        session,
                        tx,
                        dek,
                        category_id=rule.category_id,
                        categorized_by=CategorizedBy.RULE,
                        categorization_reason=None,
                    )
                    updated += 1
                break
    session.commit()
    return updated


def reset_automatic_categories(
    session: Session,
    account_id: int | None = None,
    category_id: int | None = None,
    include_manual: bool = False,
) -> tuple[int, int, list[int]]:
    """Reset selected decisions, reapply rules, and return the LLM queue IDs.

    category_id filters by the category currently assigned to a transaction. It
    deliberately runs before assignments are cleared, so only that category is
    reconsidered while every unrelated decision remains untouched.
    """
    dek = vault_session.get_dek()
    if dek is None:
        return 0, 0, []
    stored = session.exec(select(Transaction).order_by(Transaction.id)).all()
    transactions = [
        (row, decode_transaction(row, dek))
        for row in stored
    ]
    transactions = [
        (row, private)
        for row, private in transactions
        if private.kind in (TransactionKind.EXPENSE, TransactionKind.INCOME)
        and (include_manual or private.categorized_by != CategorizedBy.MANUAL)
        and (account_id is None or private.account_id == account_id)
        and (category_id is None or private.category_id == category_id)
    ]
    transaction_ids = [private.id for _row, private in transactions]
    reset_count = 0
    for row, private in transactions:
        if private.category_id is not None or private.categorized_by is not None:
            update_transaction_payload(
                session,
                row,
                dek,
                category_id=None,
                categorized_by=None,
                categorization_reason=None,
            )
            reset_count += 1
    session.commit()

    rules_applied = apply_rules(session, transaction_ids)
    queued_ids = (
        [
            private.id
            for row in session.exec(
                select(Transaction).where(col(Transaction.id).in_(transaction_ids))
            ).all()
            if (private := decode_transaction(row, dek)).category_id is None
        ]
        if transaction_ids
        else []
    )
    return reset_count, rules_applied, queued_ids


def _matches(pattern: str, text: str, is_regex: bool) -> bool:
    if is_regex:
        try:
            return re.search(pattern, text, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return pattern.lower() in text.lower()
