"""Typed ciphertext-first views for private portfolio records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, insert, or_, update
from sqlmodel import Session, select

from app.models.enums import AccountSource
from app.models.portfolio import (
    AssetPositionSnapshot,
    AssetTrade,
    Portfolio,
    PortfolioValuePoint,
)
from app.services.secure_repository import decrypted_financial_payload
from app.services.secure_data import (
    ENCRYPTION_VERSION,
    encrypt_payload,
    portfolio_trade_external_id_index,
    source_external_id_index,
)


def _insert_encrypted(
    session: Session, dek: bytes, model: type, domain: str,
    technical: dict, payload: dict, *, extra: dict | None = None,
):
    record_id = session.execute(
        insert(model).values(**technical).returning(model.id)
    ).scalar_one()
    values = {
        "encrypted_payload": encrypt_payload(
            dek, domain=domain, record_id=record_id, payload=payload
        ),
        "encryption_version": ENCRYPTION_VERSION,
        **(extra or {}),
    }
    session.execute(update(model).where(model.id == record_id).values(**values))
    session.flush()
    row = session.get(model, record_id)
    if row is None:
        raise RuntimeError(f"Ciphertext {domain} insert failed")
    return row


def insert_portfolio_payload(
    session: Session, dek: bytes, *, connection_id: int | None,
    source: AccountSource, external_id: str, name: str, currency: str,
    last_synced_at: datetime | None = None,
    asset_ledger_synced_at: datetime | None = None,
) -> Portfolio:
    payload = {
        "external_id": external_id, "name": name, "currency": currency,
        "last_synced_at": last_synced_at,
        "asset_ledger_synced_at": asset_ledger_synced_at,
    }
    return _insert_encrypted(
        session, dek, Portfolio, "portfolio",
        {"connection_id": connection_id, "source": source},
        payload,
        extra={"external_id_blind": source_external_id_index(
            dek, "portfolio", source.value, external_id
        )},
    )


def update_portfolio_payload(
    session: Session, row: Portfolio, dek: bytes, **changes: object,
) -> PortfolioData:
    if row.id is None:
        raise ValueError("Persisted portfolio is missing its id")
    payload = decrypted_financial_payload(row, dek)
    payload.update(changes)
    session.execute(update(Portfolio).where(Portfolio.id == row.id).values(
        connection_id=changes.get("connection_id", row.connection_id),
        encrypted_payload=encrypt_payload(
            dek, domain="portfolio", record_id=row.id, payload=payload
        ),
        encryption_version=ENCRYPTION_VERSION,
        external_id_blind=source_external_id_index(
            dek, "portfolio", row.source.value, str(payload["external_id"])
        ),
    ))
    session.flush()
    session.expire(row)
    return decode_portfolio(row, dek)


def insert_position_payload(
    session: Session, dek: bytes, *, portfolio_id: int, external_id: str,
    isin: str | None, name: str, asset_type: str | None, quantity: Decimal,
    average_buy_in: Decimal | None, current_price: Decimal | None,
    market_value: Decimal | None, currency: str, captured_at: datetime,
    raw_payload: dict | None,
) -> AssetPositionSnapshot:
    payload = {"external_id": external_id, "isin": isin, "name": name,
        "asset_type": asset_type, "quantity": quantity,
        "average_buy_in": average_buy_in, "current_price": current_price,
        "market_value": market_value, "currency": currency,
        "raw_payload": raw_payload}
    return _insert_encrypted(
        session, dek, AssetPositionSnapshot, "asset-position",
        {"portfolio_id": portfolio_id, "captured_at": captured_at}, payload,
    )


def insert_portfolio_value_payload(
    session: Session, dek: bytes, *, portfolio_id: int, timestamp: datetime,
    history_range: str, market_value: Decimal, currency: str,
    cash_balance: Decimal | None, raw_payload: dict | None,
) -> PortfolioValuePoint:
    payload = {"market_value": market_value, "currency": currency,
               "cash_balance": cash_balance, "raw_payload": raw_payload}
    return _insert_encrypted(
        session, dek, PortfolioValuePoint, "portfolio-value",
        {"portfolio_id": portfolio_id, "timestamp": timestamp,
         "history_range": history_range}, payload,
    )


def upsert_trade_payload(
    session: Session, dek: bytes, *, row: AssetTrade | None, portfolio_id: int,
    external_id: str, instrument_external_id: str, timestamp: datetime, side: str,
    quantity: Decimal, cash_amount: Decimal, fees: Decimal | None,
    taxes: Decimal | None, currency: str, raw_payload: dict | None,
) -> AssetTrade:
    payload = {"external_id": external_id,
        "instrument_external_id": instrument_external_id, "timestamp": timestamp,
        "side": side, "quantity": quantity, "cash_amount": cash_amount,
        "fees": fees, "taxes": taxes, "currency": currency,
        "raw_payload": raw_payload}
    blind = portfolio_trade_external_id_index(dek, portfolio_id, external_id)
    if row is None:
        return _insert_encrypted(
            session, dek, AssetTrade, "asset-trade",
            {"portfolio_id": portfolio_id, "timestamp": timestamp}, payload,
            extra={"external_id_blind": blind},
        )
    if row.id is None:
        raise ValueError("Persisted trade is missing its id")
    session.execute(update(AssetTrade).where(AssetTrade.id == row.id).values(
        timestamp=timestamp,
        encrypted_payload=encrypt_payload(
            dek, domain="asset-trade", record_id=row.id, payload=payload
        ), encryption_version=ENCRYPTION_VERSION, external_id_blind=blind,
    ))
    session.flush()
    session.expire(row)
    return row


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    return _decimal(value) if value is not None else None


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


@dataclass(frozen=True)
class PortfolioData:
    id: int
    connection_id: int | None
    source: AccountSource
    external_id: str
    name: str
    currency: str
    last_synced_at: datetime | None
    asset_ledger_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PositionData:
    id: int
    portfolio_id: int
    external_id: str
    isin: str | None
    name: str
    asset_type: str | None
    quantity: Decimal
    average_buy_in: Decimal | None
    current_price: Decimal | None
    market_value: Decimal | None
    currency: str
    captured_at: datetime
    raw_payload: dict | None
    created_at: datetime


@dataclass(frozen=True)
class PortfolioValueData:
    id: int
    portfolio_id: int
    timestamp: datetime
    history_range: str
    market_value: Decimal
    currency: str
    cash_balance: Decimal | None
    raw_payload: dict | None
    created_at: datetime


@dataclass(frozen=True)
class AssetTradeData:
    id: int
    portfolio_id: int
    external_id: str
    instrument_external_id: str
    timestamp: datetime
    side: str
    quantity: Decimal
    cash_amount: Decimal
    fees: Decimal | None
    taxes: Decimal | None
    currency: str
    raw_payload: dict | None
    created_at: datetime


def decode_portfolio(row: Portfolio, dek: bytes) -> PortfolioData:
    if row.id is None:
        raise ValueError("Persisted portfolio is missing its id")
    payload = decrypted_financial_payload(row, dek)
    return PortfolioData(
        id=row.id,
        connection_id=row.connection_id,
        source=row.source,
        external_id=str(payload.get("external_id") or ""),
        name=str(payload.get("name") or ""),
        currency=str(payload.get("currency") or "EUR"),
        last_synced_at=_optional_datetime(payload.get("last_synced_at")),
        asset_ledger_synced_at=_optional_datetime(payload.get("asset_ledger_synced_at")),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def decode_position(row: AssetPositionSnapshot, dek: bytes) -> PositionData:
    if row.id is None:
        raise ValueError("Persisted position is missing its id")
    payload = decrypted_financial_payload(row, dek)
    raw = payload.get("raw_payload")
    return PositionData(
        id=row.id,
        portfolio_id=row.portfolio_id,
        external_id=str(payload.get("external_id") or ""),
        isin=str(payload["isin"]) if payload.get("isin") is not None else None,
        name=str(payload.get("name") or ""),
        asset_type=str(payload["asset_type"]) if payload.get("asset_type") is not None else None,
        quantity=_decimal(payload.get("quantity") or "0"),
        average_buy_in=_optional_decimal(payload.get("average_buy_in")),
        current_price=_optional_decimal(payload.get("current_price")),
        market_value=_optional_decimal(payload.get("market_value")),
        currency=str(payload.get("currency") or "EUR"),
        captured_at=row.captured_at,
        raw_payload=raw if isinstance(raw, dict) else None,
        created_at=row.created_at,
    )


def decode_portfolio_value(row: PortfolioValuePoint, dek: bytes) -> PortfolioValueData:
    if row.id is None:
        raise ValueError("Persisted portfolio value is missing its id")
    payload = decrypted_financial_payload(row, dek)
    raw = payload.get("raw_payload")
    return PortfolioValueData(
        id=row.id,
        portfolio_id=row.portfolio_id,
        timestamp=row.timestamp,
        history_range=row.history_range,
        market_value=_decimal(payload.get("market_value") or "0"),
        currency=str(payload.get("currency") or "EUR"),
        cash_balance=_optional_decimal(payload.get("cash_balance")),
        raw_payload=raw if isinstance(raw, dict) else None,
        created_at=row.created_at,
    )


def decode_trade(row: AssetTrade, dek: bytes) -> AssetTradeData:
    if row.id is None:
        raise ValueError("Persisted trade is missing its id")
    payload = decrypted_financial_payload(row, dek)
    raw = payload.get("raw_payload")
    return AssetTradeData(
        id=row.id,
        portfolio_id=row.portfolio_id,
        external_id=str(payload.get("external_id") or ""),
        instrument_external_id=str(payload.get("instrument_external_id") or ""),
        timestamp=datetime.fromisoformat(str(payload["timestamp"])),
        side=str(payload.get("side") or ""),
        quantity=_decimal(payload.get("quantity") or "0"),
        cash_amount=_decimal(payload.get("cash_amount") or "0"),
        fees=_optional_decimal(payload.get("fees")),
        taxes=_optional_decimal(payload.get("taxes")),
        currency=str(payload.get("currency") or "EUR"),
        raw_payload=raw if isinstance(raw, dict) else None,
        created_at=row.created_at,
    )


def find_portfolio_by_external_id(
    session: Session,
    dek: bytes,
    *,
    source: AccountSource,
    external_id: str,
) -> Portfolio | None:
    blind = source_external_id_index(dek, "portfolio", source.value, external_id)
    return session.exec(select(Portfolio).where(
        Portfolio.source == source, Portfolio.external_id_blind == blind,
    )).first()


def find_trade_by_external_id(
    session: Session,
    dek: bytes,
    *,
    portfolio_id: int,
    external_id: str,
) -> AssetTrade | None:
    blind = portfolio_trade_external_id_index(dek, portfolio_id, external_id)
    return session.exec(select(AssetTrade).where(
        AssetTrade.portfolio_id == portfolio_id,
        AssetTrade.external_id_blind == blind,
    )).first()
