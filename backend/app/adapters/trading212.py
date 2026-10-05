"""Read-only adapter for the official Trading 212 Public API."""

from __future__ import annotations

import base64
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.adapters.base import (
    BaseAdapter,
    RawAccount,
    RawAssetPosition,
    RawAssetTrade,
    RawBalance,
    RawPortfolio,
    RawPortfolioValuePoint,
    RawTransaction,
)
from app.models.enums import AccountSource, AccountType


ZERO = Decimal("0")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class Trading212Adapter(BaseAdapter):
    """Import cash, positions and executions without trading permissions."""

    source = AccountSource.TRADING_212

    def __init__(
        self,
        credentials: dict[str, Any] | None = None,
        label: str = "Trading 212",
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._creds = credentials or {}
        self._label = label
        self._base_url = "https://live.trading212.com"
        self._client = client
        self._summary: dict[str, Any] | None = None

    def is_configured(self) -> bool:
        return bool(self._creds.get("api_key") and self._creds.get("api_secret"))

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
        self._summary = None

    def list_accounts(self) -> list[RawAccount]:
        if not self.is_configured():
            return []
        summary = self._account_summary()
        return [
            RawAccount(
                external_id=f"trading212-cash-{summary['id']}",
                name=f"{self._label} Cash",
                currency=str(summary.get("currency") or "EUR"),
                account_type=AccountType.BROKER_CASH,
            )
        ]

    def fetch_transactions(
        self, account: RawAccount, since: date, until: date
    ) -> list[RawTransaction]:
        if not self.is_configured():
            return []
        start = datetime.combine(since, time.min, tzinfo=timezone.utc)
        rows = self._all_pages(
            "/api/v0/equity/history/transactions",
            params={"limit": 50, "time": start.isoformat().replace("+00:00", "Z")},
        )
        result: list[RawTransaction] = []
        for row in rows:
            booked_at = _datetime(row.get("dateTime"))
            if not since <= booked_at.date() <= until:
                continue
            kind = str(row.get("type") or "TRANSACTION").upper()
            amount = _decimal(row.get("amount"))
            if kind in {"WITHDRAW", "FEE"}:
                amount = -abs(amount)
            elif kind in {"DEPOSIT", "INTEREST_ON_FREE_CASH", "LENDING_INTEREST"}:
                amount = abs(amount)
            reference = str(row.get("reference") or f"{booked_at.isoformat()}:{kind}:{amount}")
            result.append(
                RawTransaction(
                    external_id=f"trading212:{reference}",
                    booking_date=booked_at.date(),
                    amount=amount,
                    currency=str(row.get("currency") or account.currency),
                    raw_text=kind.replace("_", " ").title(),
                    counterparty="Trading 212",
                    raw_payload=row,
                )
            )
        return result

    def fetch_balance(self, account: RawAccount) -> RawBalance | None:
        if not self.is_configured():
            return None
        summary = self._account_summary()
        cash = summary.get("cash") if isinstance(summary.get("cash"), dict) else {}
        available = _decimal(cash.get("availableToTrade"))
        booked = available + _decimal(cash.get("inPies")) + _decimal(
            cash.get("reservedForOrders")
        )
        return RawBalance(
            booked=booked,
            available=available,
            currency=str(summary.get("currency") or account.currency),
            raw_payload={"cash": cash},
        )

    def fetch_portfolios(
        self,
        history_range: str = "5d",
        known_history_external_ids: set[str] | None = None,
    ) -> list[RawPortfolio]:
        if not self.is_configured():
            return []
        summary = self._account_summary()
        positions_payload = self._get("/api/v0/equity/positions")
        position_rows = positions_payload if isinstance(positions_payload, list) else []
        positions = [self._map_position(row) for row in position_rows]
        positions = [position for position in positions if position is not None]
        order_rows = self._all_pages(
            "/api/v0/equity/history/orders", params={"limit": 50}
        )
        trades = [self._map_trade(row) for row in order_rows]
        trades = [trade for trade in trades if trade is not None]

        investments = (
            summary.get("investments")
            if isinstance(summary.get("investments"), dict)
            else {}
        )
        cash = summary.get("cash") if isinstance(summary.get("cash"), dict) else {}
        currency = str(summary.get("currency") or "EUR")
        cash_total = (
            _decimal(cash.get("availableToTrade"))
            + _decimal(cash.get("inPies"))
            + _decimal(cash.get("reservedForOrders"))
        )
        current_value = _decimal(investments.get("currentValue"))
        now = datetime.now(timezone.utc)
        value_point = RawPortfolioValuePoint(
            timestamp=now,
            market_value=current_value,
            cash_balance=cash_total,
            currency=currency,
            raw_payload={
                "performance": {
                    "absoluteValue": str(_decimal(investments.get("unrealizedProfitLoss"))),
                    "realizedValue": str(_decimal(investments.get("realizedProfitLoss"))),
                    "costValue": str(_decimal(investments.get("totalCost"))),
                },
                "provider": "trading212",
            },
            history_range="max",
        )
        return [
            RawPortfolio(
                external_id=f"trading212-invest-{summary['id']}",
                name=self._label,
                currency=currency,
                positions=positions,
                value_history=[value_point],
                trades=trades,
                trades_complete=True,
                captured_at=now,
            )
        ]

    def _map_position(self, row: dict[str, Any]) -> RawAssetPosition | None:
        instrument = row.get("instrument") if isinstance(row.get("instrument"), dict) else {}
        wallet = row.get("walletImpact") if isinstance(row.get("walletImpact"), dict) else {}
        ticker = str(instrument.get("ticker") or "").strip()
        quantity = _decimal(row.get("quantity"))
        if not ticker or quantity <= ZERO:
            return None
        total_cost = _decimal(wallet.get("totalCost"))
        current_value = _decimal(wallet.get("currentValue"))
        currency = str(wallet.get("currency") or instrument.get("currency") or "EUR")
        return RawAssetPosition(
            external_id=ticker,
            isin=str(instrument.get("isin") or "") or None,
            name=str(instrument.get("name") or ticker),
            asset_type="security",
            quantity=quantity,
            currency=currency,
            average_buy_in=total_cost / quantity if total_cost else None,
            current_price=current_value / quantity if current_value else None,
            market_value=current_value,
            raw_payload={"position": row},
        )

    def _map_trade(self, row: dict[str, Any]) -> RawAssetTrade | None:
        order = row.get("order") if isinstance(row.get("order"), dict) else {}
        fill = row.get("fill") if isinstance(row.get("fill"), dict) else {}
        instrument = order.get("instrument") if isinstance(order.get("instrument"), dict) else {}
        wallet = fill.get("walletImpact") if isinstance(fill.get("walletImpact"), dict) else {}
        ticker = str(instrument.get("ticker") or order.get("ticker") or "").strip()
        fill_id = fill.get("id")
        filled_at = fill.get("filledAt")
        quantity = abs(_decimal(fill.get("quantity")))
        if not ticker or fill_id is None or not filled_at or quantity <= ZERO:
            return None
        taxes = wallet.get("taxes") if isinstance(wallet.get("taxes"), list) else []
        currency = str(wallet.get("currency") or order.get("currency") or "EUR")
        tax_total = sum(
            (
                abs(_decimal(tax.get("quantity")))
                for tax in taxes
                if isinstance(tax, dict) and str(tax.get("currency") or currency) == currency
            ),
            ZERO,
        )
        return RawAssetTrade(
            external_id=f"trading212:fill:{fill_id}",
            instrument_external_id=ticker,
            timestamp=_datetime(filled_at),
            side=str(order.get("side") or "").lower(),
            quantity=quantity,
            cash_amount=abs(_decimal(wallet.get("netValue"))),
            fees=tax_total or None,
            taxes=tax_total or None,
            currency=currency,
            raw_payload=row,
        )

    def _account_summary(self) -> dict[str, Any]:
        if self._summary is None:
            payload = self._get("/api/v0/equity/account/summary")
            if not isinstance(payload, dict) or payload.get("id") is None:
                raise RuntimeError("Trading 212 returned an invalid account summary")
            self._summary = payload
        return self._summary

    def _all_pages(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        next_path: str | None = path
        next_params = params
        while next_path:
            payload = self._get(next_path, params=next_params)
            if not isinstance(payload, dict):
                raise RuntimeError("Trading 212 returned an invalid paginated response")
            result.extend(item for item in payload.get("items") or [] if isinstance(item, dict))
            raw_next = payload.get("nextPagePath")
            next_path = str(raw_next) if raw_next else None
            next_params = None
        return result

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        token = base64.b64encode(
            f"{self._creds.get('api_key', '')}:{self._creds.get('api_secret', '')}".encode()
        ).decode()
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        try:
            response = client.get(
                url,
                params=params,
                headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()
        finally:
            if owns_client:
                client.close()
