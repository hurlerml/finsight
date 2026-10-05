"""Ciphertext-first account reads and blind-index lookups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, insert, or_, update
from sqlmodel import Session, select

from app.models.account import Account
from app.models.account_balance import AccountBalanceSnapshot
from app.models.enums import AccountSource, AccountType
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload, source_external_id_index
from app.services.secure_repository import decrypted_financial_payload


@dataclass(frozen=True)
class AccountData:
    id: int
    connection_id: int | None
    source: AccountSource
    external_id: str
    name: str
    currency: str
    account_type: AccountType
    iban: str | None
    is_active: bool
    current_balance: Decimal | None
    available_balance: Decimal | None
    balance_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _account_payload(
    *, external_id: str, name: str, currency: str, account_type: AccountType,
    iban: str | None, current_balance: Decimal | None = None,
    available_balance: Decimal | None = None,
    balance_updated_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "external_id": external_id, "name": name, "currency": currency,
        "account_type": account_type.value, "iban": iban,
        "current_balance": current_balance, "available_balance": available_balance,
        "balance_updated_at": balance_updated_at,
    }


def insert_account_payload(
    session: Session, dek: bytes, *, source: AccountSource, external_id: str,
    name: str, currency: str, account_type: AccountType, iban: str | None,
    connection_id: int | None = None, is_active: bool = True,
) -> Account:
    """Insert an account without persisting private values in plaintext."""
    account_id = session.execute(
        insert(Account).values(
            connection_id=connection_id,
            source=source,
            is_active=is_active,
        ).returning(Account.id)
    ).scalar_one()
    payload = _account_payload(
        external_id=external_id, name=name, currency=currency,
        account_type=account_type, iban=iban,
    )
    session.execute(
        update(Account).where(Account.id == account_id).values(
            encrypted_payload=encrypt_payload(
                dek, domain="account", record_id=account_id, payload=payload
            ),
            encryption_version=ENCRYPTION_VERSION,
            external_id_blind=source_external_id_index(
                dek, "account", source.value, external_id
            ),
        )
    )
    session.flush()
    account = session.get(Account, account_id)
    if account is None:
        raise RuntimeError("Ciphertext account insert failed")
    return account


def update_account_payload(
    session: Session, row: Account, dek: bytes, **changes: object,
) -> AccountData:
    """Update an account with its encrypted payload as the source of truth."""
    if row.id is None:
        raise ValueError("Persisted account is missing its id")
    payload = decrypted_financial_payload(row, dek)
    for key, value in changes.items():
        payload[key] = value.value if hasattr(value, "value") else value
    external_id = str(payload["external_id"])
    values: dict[str, object] = {
        "encrypted_payload": encrypt_payload(
            dek, domain="account", record_id=row.id, payload=payload
        ),
        "encryption_version": ENCRYPTION_VERSION,
        "external_id_blind": source_external_id_index(
            dek, "account", row.source.value, external_id
        ),
    }
    for key in ("connection_id", "is_active"):
        if key in changes:
            values[key] = changes[key]
    session.execute(update(Account).where(Account.id == row.id).values(**values))
    session.flush()
    session.expire(row)
    return decode_account(row, dek)


def insert_balance_payload(
    session: Session, dek: bytes, *, account_id: int, booked_balance: Decimal,
    available_balance: Decimal | None, currency: str, captured_at: datetime,
    raw_payload: dict | None,
) -> AccountBalanceSnapshot:
    payload = {"booked_balance": booked_balance,
               "available_balance": available_balance, "currency": currency,
               "raw_payload": raw_payload}
    snapshot_id = session.execute(
        insert(AccountBalanceSnapshot).values(
            account_id=account_id, captured_at=captured_at,
        ).returning(AccountBalanceSnapshot.id)
    ).scalar_one()
    session.execute(update(AccountBalanceSnapshot).where(
        AccountBalanceSnapshot.id == snapshot_id
    ).values(
        encrypted_payload=encrypt_payload(
            dek, domain="account-balance", record_id=snapshot_id, payload=payload
        ), encryption_version=ENCRYPTION_VERSION,
    ))
    session.flush()
    row = session.get(AccountBalanceSnapshot, snapshot_id)
    if row is None:
        raise RuntimeError("Ciphertext account balance insert failed")
    return row


def _optional_decimal(value: object) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def decode_account(row: Account, dek: bytes) -> AccountData:
    if row.id is None:
        raise ValueError("Persisted account is missing its id")
    payload = decrypted_financial_payload(row, dek)
    return AccountData(
        id=row.id,
        connection_id=row.connection_id,
        source=row.source,
        external_id=str(payload["external_id"]),
        name=str(payload["name"]),
        currency=str(payload.get("currency") or "EUR"),
        account_type=AccountType(str(payload.get("account_type") or AccountType.CHECKING.value)),
        iban=str(payload["iban"]) if payload.get("iban") is not None else None,
        is_active=row.is_active,
        current_balance=_optional_decimal(payload.get("current_balance")),
        available_balance=_optional_decimal(payload.get("available_balance")),
        balance_updated_at=_optional_datetime(payload.get("balance_updated_at")),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def load_accounts(
    session: Session,
    dek: bytes,
    *,
    active_only: bool = False,
) -> list[AccountData]:
    query = select(Account)
    if active_only:
        query = query.where(Account.is_active.is_(True))  # type: ignore[union-attr]
    rows = session.exec(query.order_by(Account.id)).all()
    return sorted((decode_account(row, dek) for row in rows), key=lambda item: item.name.casefold())


def find_account_by_external_id(
    session: Session,
    dek: bytes,
    *,
    source: AccountSource,
    external_id: str,
) -> Account | None:
    blind = source_external_id_index(dek, "account", source.value, external_id)
    return session.exec(select(Account).where(
        Account.source == source, Account.external_id_blind == blind,
    )).first()
