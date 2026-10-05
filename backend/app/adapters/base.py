"""Shared adapter interface for all sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.models.enums import AccountSource, AccountType


@dataclass
class RawAccount:
    external_id: str
    name: str
    currency: str
    account_type: AccountType
    iban: str | None = None


@dataclass
class RawTransaction:
    external_id: str
    booking_date: date
    amount: Decimal
    currency: str
    raw_text: str
    counterparty: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawBalance:
    """Provider balance as reported by the source, never derived from transactions."""

    booked: Decimal
    currency: str
    available: Decimal | None = None
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawAssetPosition:
    external_id: str
    name: str
    quantity: Decimal
    currency: str
    asset_type: str | None = None
    isin: str | None = None
    average_buy_in: Decimal | None = None
    current_price: Decimal | None = None
    market_value: Decimal | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawAssetPricePoint:
    external_id: str
    exchange: str
    timestamp: datetime
    close: Decimal
    currency: str
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    adjusted: Decimal | None = None
    volume: Decimal | None = None


@dataclass
class RawPortfolioValuePoint:
    timestamp: datetime
    market_value: Decimal
    currency: str
    cash_balance: Decimal | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    history_range: str = "max"


@dataclass
class RawAssetTrade:
    """One executed asset order, normalized independently of cash transactions."""

    external_id: str
    instrument_external_id: str
    timestamp: datetime
    side: str
    quantity: Decimal
    cash_amount: Decimal
    currency: str
    fees: Decimal | None = None
    taxes: Decimal | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawPortfolio:
    external_id: str
    name: str
    currency: str
    positions: list[RawAssetPosition] = field(default_factory=list)
    price_history: list[RawAssetPricePoint] = field(default_factory=list)
    value_history: list[RawPortfolioValuePoint] = field(default_factory=list)
    trades: list[RawAssetTrade] = field(default_factory=list)
    trades_complete: bool = False
    # Spot symbols for which the adapter completed a full ``myTrades`` query.
    # This lets the persistence layer reconcile stale rows for those symbols
    # without deleting unrelated, partially available ledger sources.
    completed_trade_symbols: set[str] = field(default_factory=set)
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseAdapter(ABC):
    source: AccountSource
    connection_id: int | None = None
    provider: str | None = None

    def prepare_asset_sync(
        self,
        *,
        known_trade_external_ids: set[str],
        known_history_external_ids: set[str],
        has_history: bool,
        has_complete_trade_history: bool,
        known_trade_instruments: set[str] | None = None,
        known_trade_symbols: set[str] | None = None,
    ) -> None:
        """Provide persisted read-model state so adapters can perform deltas."""
        return None

    def accepts_account(self, external_id: str, iban: str | None = None) -> bool:
        """Return whether this connection is responsible for an existing account."""
        return True

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when required credentials are present."""

    @abstractmethod
    def list_accounts(self) -> list[RawAccount]:
        ...

    @abstractmethod
    def fetch_transactions(
        self, account: RawAccount, since: date, until: date
    ) -> list[RawTransaction]:
        ...

    def fetch_balance(self, account: RawAccount) -> RawBalance | None:
        """Return a source-reported balance when the provider supports it."""
        return None

    def fetch_portfolios(
        self,
        history_range: str = "5d",
        known_history_external_ids: set[str] | None = None,
    ) -> list[RawPortfolio]:
        """Return read-only investment positions, excluding cash accounts."""
        return []


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[BaseAdapter] = []

    def register(self, adapter: BaseAdapter) -> None:
        self._adapters.append(adapter)

    def get(self, source: AccountSource) -> list[BaseAdapter]:
        return [a for a in self._adapters if a.source == source]

    def configured(self) -> list[BaseAdapter]:
        return [a for a in self._adapters if a.is_configured()]

    def all(self) -> list[BaseAdapter]:
        return list(self._adapters)
