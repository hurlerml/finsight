"""Read encrypted transaction payloads with blind-index preselection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, insert, or_, update
from sqlmodel import Session, select

from app.models import Transaction
from app.models.enums import CategorizedBy, TransactionKind
from app.services.secure_repository import decrypted_transaction_payload
from app.services.secure_data import (
    ENCRYPTION_VERSION,
    encrypt_payload,
    transaction_external_id_index,
    transaction_month_index,
)


@dataclass(frozen=True)
class TransactionData:
    id: int
    account_id: int
    external_id: str
    booking_date: date
    amount: Decimal
    currency: str
    raw_text: str
    counterparty: str | None
    kind: TransactionKind
    category_id: int | None
    categorized_by: CategorizedBy | None
    raw_payload: dict | None
    created_at: datetime
    updated_at: datetime
    categorization_reason: str | None = None


def insert_transaction_payload(
    session: Session,
    dek: bytes,
    *,
    account_id: int,
    external_id: str,
    booking_date: date,
    amount: Decimal,
    currency: str,
    raw_text: str,
    counterparty: str | None,
    kind: TransactionKind,
    raw_payload: dict | None,
) -> TransactionData:
    """Insert a transaction without ever persisting its private fields in plaintext."""
    transaction_id = session.execute(
        insert(Transaction)
        .values(account_id=account_id)
        .returning(Transaction.id)
    ).scalar_one()
    payload = {
        "account_id": account_id,
        "external_id": external_id,
        "booking_date": booking_date,
        "amount": amount,
        "currency": currency,
        "raw_text": raw_text,
        "counterparty": counterparty,
        "kind": kind,
        "category_id": None,
        "categorized_by": None,
        "categorization_reason": None,
        "raw_payload": raw_payload,
    }
    session.execute(
        update(Transaction)
        .where(Transaction.id == transaction_id)
        .values(
            encrypted_payload=encrypt_payload(
                dek,
                domain="transaction",
                record_id=transaction_id,
                payload=payload,
            ),
            encryption_version=ENCRYPTION_VERSION,
            booking_month_blind=transaction_month_index(
                dek, account_id, booking_date
            ),
            external_id_blind=transaction_external_id_index(
                dek, account_id, external_id
            ),
        )
    )
    session.flush()
    row = session.get(Transaction, transaction_id)
    if row is None:
        raise RuntimeError("Ciphertext transaction insert failed")
    return decode_transaction(row, dek)


def _months_between(start: date, end: date) -> list[date]:
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    result: list[date] = []
    while current <= last:
        result.append(current)
        current = date(
            current.year + (1 if current.month == 12 else 0),
            current.month % 12 + 1,
            1,
        )
    return result


def decode_transaction(row: Transaction, dek: bytes) -> TransactionData:
    if row.id is None:
        raise ValueError("Stored transaction has no id")
    payload = decrypted_transaction_payload(row, dek)
    categorized = payload.get("categorized_by")
    return TransactionData(
        id=row.id,
        account_id=int(payload["account_id"]),
        external_id=str(payload["external_id"]),
        booking_date=date.fromisoformat(str(payload["booking_date"])),
        amount=Decimal(str(payload["amount"])),
        currency=str(payload.get("currency") or "EUR"),
        raw_text=str(payload.get("raw_text") or ""),
        counterparty=(
            str(payload["counterparty"])
            if payload.get("counterparty") is not None
            else None
        ),
        kind=TransactionKind(str(payload["kind"])),
        category_id=(
            int(payload["category_id"])
            if payload.get("category_id") is not None
            else None
        ),
        categorized_by=CategorizedBy(str(categorized)) if categorized else None,
        categorization_reason=(
            str(payload["categorization_reason"])
            if payload.get("categorization_reason") is not None
            else None
        ),
        raw_payload=(
            payload.get("raw_payload")
            if isinstance(payload.get("raw_payload"), dict)
            else None
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def load_transactions(
    session: Session,
    dek: bytes,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    kind: TransactionKind | None = None,
    search: str | None = None,
) -> list[TransactionData]:
    """Load a bounded ciphertext candidate set, then filter and sort in memory."""
    if from_date and to_date and from_date > to_date:
        return []

    statement = select(Transaction)
    if account_id is not None:
        statement = statement.where(Transaction.account_id == account_id)

    # Exact dates stay encrypted. Equality-searchable month tokens keep the
    # candidate set small without exposing the booking date.
    if from_date is not None and to_date is not None:
        account_ids = [account_id] if account_id is not None else list(
            session.exec(select(Transaction.account_id).distinct()).all()
        )
        month_starts = _months_between(from_date, to_date)
        tokens = [
            transaction_month_index(dek, candidate_account_id, month)
            for candidate_account_id in account_ids
            for month in month_starts
        ]
        encrypted_match = (
            Transaction.booking_month_blind.in_(tokens)  # type: ignore[union-attr]
            if tokens
            else False
        )
        statement = statement.where(encrypted_match)

    decoded = [decode_transaction(row, dek) for row in session.exec(statement).all()]
    needle = str(search or "").strip().casefold()
    filtered = [
        row
        for row in decoded
        if (from_date is None or row.booking_date >= from_date)
        and (to_date is None or row.booking_date <= to_date)
        and (account_id is None or row.account_id == account_id)
        and (category_id is None or row.category_id == category_id)
        and (kind is None or row.kind == kind)
        and (
            not needle
            or needle in " ".join(
                (
                    row.counterparty or "",
                    row.raw_text or "",
                    str(row.amount),
                    row.currency or "",
                    row.booking_date.isoformat(),
                )
            ).casefold()
        )
    ]
    filtered.sort(key=lambda row: (row.booking_date, row.id), reverse=True)
    return filtered


def update_transaction_payload(
    session: Session,
    row: Transaction,
    dek: bytes,
    **changes: object,
) -> TransactionData:
    """Update ciphertext as the source of truth (no plaintext dual-write)."""
    if row.id is None:
        raise ValueError("Persisted transaction is missing its id")
    payload = decrypted_transaction_payload(row, dek)
    for key, value in changes.items():
        payload[key] = value.value if hasattr(value, "value") else value

    account_id = int(payload["account_id"])
    external_id = str(payload["external_id"])
    booking_date = date.fromisoformat(str(payload["booking_date"]))
    encrypted = encrypt_payload(
        dek,
        domain="transaction",
        record_id=row.id,
        payload=payload,
    )
    session.exec(
        update(Transaction)
        .where(Transaction.id == row.id)
        .values(
            encrypted_payload=encrypted,
            encryption_version=ENCRYPTION_VERSION,
            booking_month_blind=transaction_month_index(dek, account_id, booking_date),
            external_id_blind=transaction_external_id_index(dek, account_id, external_id),
        )
    )
    session.flush()
    session.expire(row)
    return decode_transaction(row, dek)
