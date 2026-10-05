"""Ciphertext helpers for private records: seal, decrypt, status, and unlock audit.

Canonical private data lives only in `encrypted_payload`. Unlock audits
authenticate decryption — missing ciphertext fails closed.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, insert, update
from sqlmodel import Session, select

from app.models.account import Account
from app.models.account_balance import AccountBalanceSnapshot
from app.models.agent import AgentConversation, AgentConversationMessage
from app.models.app_setting import AppSetting
from app.models.category import Category, CategoryRule
from app.models.job import Job
from app.models.portfolio import (
    AssetPositionSnapshot,
    AssetTrade,
    Portfolio,
    PortfolioValuePoint,
)
from app.models.sync_state import SyncState
from app.models.tag import Tag, TransactionTag
from app.models.transaction import Transaction, TransactionLink
from app.models.vault import Connection
from app.services.secure_data import (
    ENCRYPTION_VERSION,
    decrypt_payload,
    encrypt_payload,
    portfolio_trade_external_id_index,
    private_name_index,
    source_external_id_index,
    transaction_external_id_index,
    transaction_month_index,
)

PrivateRecord = (
    Account
    | AccountBalanceSnapshot
    | AgentConversation
    | AgentConversationMessage
    | AssetPositionSnapshot
    | AssetTrade
    | AppSetting
    | Category
    | CategoryRule
    | Connection
    | Job
    | Portfolio
    | PortfolioValuePoint
    | SyncState
    | Tag
    | Transaction
    | TransactionLink
    | TransactionTag
)

_DOMAIN_BY_TYPE: dict[type, str] = {
    Account: "account",
    AccountBalanceSnapshot: "account-balance",
    Portfolio: "portfolio",
    AssetPositionSnapshot: "asset-position",
    PortfolioValuePoint: "portfolio-value",
    AssetTrade: "asset-trade",
    Tag: "tag",
    TransactionTag: "transaction-tag",
    Category: "category",
    CategoryRule: "category-rule",
    TransactionLink: "transaction-link",
    Connection: "connection",
    SyncState: "sync-state",
    Job: "job",
    AppSetting: "app-setting",
}


def sealed_transaction_values(
    *,
    dek: bytes,
    record_id: int,
    account_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    booking_date = payload["booking_date"]
    if isinstance(booking_date, str):
        booking_date = date.fromisoformat(booking_date)
    return {
        "encrypted_payload": encrypt_payload(
            dek,
            domain="transaction",
            record_id=record_id,
            payload=payload,
        ),
        "encryption_version": ENCRYPTION_VERSION,
        "booking_month_blind": transaction_month_index(
            dek, account_id, booking_date  # type: ignore[arg-type]
        ),
        "external_id_blind": transaction_external_id_index(
            dek, account_id, str(payload["external_id"])
        ),
    }


def decrypted_transaction_payload(transaction: Transaction, dek: bytes) -> dict[str, Any]:
    if transaction.id is None or transaction.encrypted_payload is None:
        raise ValueError("Transaction has no encrypted payload")
    return decrypt_payload(
        dek,
        domain="transaction",
        record_id=transaction.id,
        blob=transaction.encrypted_payload,
    )


def sealed_conversation_values(
    *,
    dek: bytes,
    record_id: int,
    title: str,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "encrypted_payload": encrypt_payload(
            dek,
            domain="agent-conversation",
            record_id=record_id,
            payload={"title": title, "context": context or []},
        ),
        "encryption_version": ENCRYPTION_VERSION,
    }


def decrypted_conversation_payload(
    conversation: AgentConversation, dek: bytes
) -> dict[str, Any]:
    if conversation.id is None or conversation.encrypted_payload is None:
        raise ValueError("Conversation has no encrypted payload")
    return decrypt_payload(
        dek,
        domain="agent-conversation",
        record_id=conversation.id,
        blob=conversation.encrypted_payload,
    )


def sealed_message_values(
    *,
    dek: bytes,
    record_id: int,
    role: str,
    content: str,
) -> dict[str, Any]:
    return {
        "encrypted_payload": encrypt_payload(
            dek,
            domain="agent-message",
            record_id=record_id,
            payload={"role": role, "content": content},
        ),
        "encryption_version": ENCRYPTION_VERSION,
    }


def decrypted_message_payload(
    message: AgentConversationMessage, dek: bytes
) -> dict[str, Any]:
    if message.id is None or message.encrypted_payload is None:
        raise ValueError("Message has no encrypted payload")
    return decrypt_payload(
        dek,
        domain="agent-message",
        record_id=message.id,
        blob=message.encrypted_payload,
    )


def insert_conversation_payload(
    session: Session,
    dek: bytes,
    *,
    title: str,
    context: list[dict[str, Any]] | None = None,
) -> AgentConversation:
    record_id = session.execute(
        insert(AgentConversation).returning(AgentConversation.id)
    ).scalar_one()
    session.execute(
        update(AgentConversation)
        .where(AgentConversation.id == record_id)
        .values(
            **sealed_conversation_values(
                dek=dek,
                record_id=record_id,
                title=title,
                context=context or [],
            )
        )
    )
    session.flush()
    row = session.get(AgentConversation, record_id)
    if row is None:
        raise RuntimeError("Ciphertext conversation insert failed")
    return row


def update_conversation_payload(
    session: Session,
    row: AgentConversation,
    dek: bytes,
    *,
    title: str | None = None,
    context: list[dict[str, Any]] | None = None,
    updated_at: object | None = None,
) -> None:
    if row.id is None:
        raise ValueError("Persisted conversation is missing its id")
    payload = decrypted_conversation_payload(row, dek)
    if title is not None:
        payload["title"] = title
    if context is not None:
        payload["context"] = context
    values: dict[str, Any] = {
        "encrypted_payload": encrypt_payload(
            dek,
            domain="agent-conversation",
            record_id=row.id,
            payload=payload,
        ),
        "encryption_version": ENCRYPTION_VERSION,
    }
    if updated_at is not None:
        values["updated_at"] = updated_at
    session.execute(
        update(AgentConversation).where(AgentConversation.id == row.id).values(**values)
    )
    session.flush()
    session.expire(row)


def insert_message_payload(
    session: Session,
    dek: bytes,
    *,
    conversation_id: int,
    role: str,
    content: str,
) -> AgentConversationMessage:
    record_id = session.execute(
        insert(AgentConversationMessage)
        .values(conversation_id=conversation_id)
        .returning(AgentConversationMessage.id)
    ).scalar_one()
    session.execute(
        update(AgentConversationMessage)
        .where(AgentConversationMessage.id == record_id)
        .values(
            **sealed_message_values(
                dek=dek,
                record_id=record_id,
                role=role,
                content=content,
            )
        )
    )
    session.flush()
    row = session.get(AgentConversationMessage, record_id)
    if row is None:
        raise RuntimeError("Ciphertext message insert failed")
    return row


def sealed_financial_values(
    *,
    dek: bytes,
    domain: str,
    record_id: int,
    payload: dict[str, Any],
    external_id_blind: bytes | None = None,
    name_blind: bytes | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "encrypted_payload": encrypt_payload(
            dek, domain=domain, record_id=record_id, payload=payload
        ),
        "encryption_version": ENCRYPTION_VERSION,
    }
    if external_id_blind is not None:
        values["external_id_blind"] = external_id_blind
    if name_blind is not None:
        values["name_blind"] = name_blind
    return values


def sealed_account_values(
    *,
    dek: bytes,
    record_id: int,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return sealed_financial_values(
        dek=dek,
        domain="account",
        record_id=record_id,
        payload=payload,
        external_id_blind=source_external_id_index(
            dek, "account", source, str(payload["external_id"])
        ),
    )


def sealed_position_values(
    *,
    dek: bytes,
    record_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return sealed_financial_values(
        dek=dek,
        domain="asset-position",
        record_id=record_id,
        payload=payload,
    )


def decrypted_financial_payload(record: PrivateRecord, dek: bytes) -> dict[str, Any]:
    domain = _DOMAIN_BY_TYPE[type(record)]
    if record.id is None or record.encrypted_payload is None:
        raise ValueError(f"{type(record).__name__} has no encrypted payload")
    return decrypt_payload(
        dek,
        domain=domain,
        record_id=record.id,
        blob=record.encrypted_payload,
    )


def private_payload_status(session: Session) -> dict[str, dict[str, int]]:
    collections: dict[str, type] = {
        "transactions": Transaction,
        "conversations": AgentConversation,
        "messages": AgentConversationMessage,
        "accounts": Account,
        "account_balances": AccountBalanceSnapshot,
        "portfolios": Portfolio,
        "asset_positions": AssetPositionSnapshot,
        "portfolio_values": PortfolioValuePoint,
        "asset_trades": AssetTrade,
        "tags": Tag,
        "transaction_tags": TransactionTag,
        "categories": Category,
        "category_rules": CategoryRule,
        "transaction_links": TransactionLink,
        "connections": Connection,
        "sync_states": SyncState,
        "jobs": Job,
        "app_settings": AppSetting,
    }
    out: dict[str, dict[str, int]] = {}
    for name, model in collections.items():
        total = int(session.exec(select(func.count()).select_from(model)).one())
        encrypted = int(
            session.exec(
                select(func.count())
                .select_from(model)
                .where(model.encrypted_payload.is_not(None))  # type: ignore[attr-defined]
            ).one()
        )
        out[name] = {
            "total": total,
            "encrypted": encrypted,
            "pending": total - encrypted,
        }
    return out


def audit_private_payloads(session: Session, dek: bytes) -> dict[str, dict[str, int]]:
    """Authenticate every encrypted payload. No plaintext comparison."""
    collections: list[tuple[str, type, Any]] = [
        ("transactions", Transaction, decrypted_transaction_payload),
        ("conversations", AgentConversation, decrypted_conversation_payload),
        ("messages", AgentConversationMessage, decrypted_message_payload),
        ("accounts", Account, decrypted_financial_payload),
        ("account_balances", AccountBalanceSnapshot, decrypted_financial_payload),
        ("portfolios", Portfolio, decrypted_financial_payload),
        ("asset_positions", AssetPositionSnapshot, decrypted_financial_payload),
        ("portfolio_values", PortfolioValuePoint, decrypted_financial_payload),
        ("asset_trades", AssetTrade, decrypted_financial_payload),
        ("tags", Tag, decrypted_financial_payload),
        ("transaction_tags", TransactionTag, decrypted_financial_payload),
        ("categories", Category, decrypted_financial_payload),
        ("category_rules", CategoryRule, decrypted_financial_payload),
        ("transaction_links", TransactionLink, decrypted_financial_payload),
        ("connections", Connection, decrypted_financial_payload),
        ("sync_states", SyncState, decrypted_financial_payload),
        ("jobs", Job, decrypted_financial_payload),
        ("app_settings", AppSetting, decrypted_financial_payload),
    ]
    out: dict[str, dict[str, int]] = {}
    for name, model, decrypt_fn in collections:
        rows = list(session.exec(select(model)).all())
        verified = 0
        pending = 0
        unreadable = 0
        for row in rows:
            if getattr(row, "encrypted_payload", None) is None:
                pending += 1
                continue
            try:
                decrypt_fn(row, dek)
                verified += 1
            except Exception:
                unreadable += 1
        out[name] = {
            "total": len(rows),
            "verified": verified,
            "pending": pending,
            "unreadable": unreadable,
        }
    connection_rows = list(session.exec(select(Connection)).all())
    credential_verified = 0
    credential_pending = 0
    credential_unreadable = 0
    # Connection credentials use a dedicated ciphertext because adapters need
    # to load them independently from the connection's display metadata.
    # Authenticate that ciphertext as part of the same vault audit.
    from app.services.vault import decrypt_secrets

    for connection in connection_rows:
        if not connection.secrets_encrypted:
            credential_pending += 1
            continue
        try:
            decrypt_secrets(dek, connection.secrets_encrypted)
            credential_verified += 1
        except Exception:
            credential_unreadable += 1
    out["connection_credentials"] = {
        "total": len(connection_rows),
        "verified": credential_verified,
        "pending": credential_pending,
        "unreadable": credential_unreadable,
    }
    return out


# Re-export blind helpers used by tests / callers that previously went through sealing.
__all__ = [
    "PrivateRecord",
    "audit_private_payloads",
    "decrypted_conversation_payload",
    "decrypted_financial_payload",
    "decrypted_message_payload",
    "decrypted_transaction_payload",
    "insert_conversation_payload",
    "insert_message_payload",
    "private_payload_status",
    "private_name_index",
    "portfolio_trade_external_id_index",
    "sealed_account_values",
    "sealed_conversation_values",
    "sealed_financial_values",
    "sealed_message_values",
    "sealed_position_values",
    "sealed_transaction_values",
    "source_external_id_index",
    "update_conversation_payload",
]
