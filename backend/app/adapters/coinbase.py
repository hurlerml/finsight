"""Read-only adapter for the official Coinbase Advanced Trade REST API."""

from __future__ import annotations

import logging
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization

from app.adapters.base import (
    BaseAdapter,
    RawAccount,
    RawAssetPosition,
    RawAssetPricePoint,
    RawAssetTrade,
    RawBalance,
    RawPortfolio,
    RawPortfolioValuePoint,
    RawTransaction,
)
from app.models.enums import AccountSource, AccountType


logger = logging.getLogger(__name__)
ZERO = Decimal("0")
FIAT_ASSETS = {
    "AUD", "BRL", "CAD", "CHF", "CZK", "EUR", "GBP", "HKD", "HUF",
    "JPY", "MXN", "NZD", "PLN", "RON", "SEK", "SGD", "TRY", "USD", "ZAR",
}
COINBASE_API_URL = "https://api.coinbase.com"


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return ZERO


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return converted if isinstance(converted, dict) else {}
    return dict(getattr(value, "__dict__", {}) or {})


def _amount(value: Any) -> tuple[Decimal, str | None]:
    if value is None:
        return ZERO, None
    return _decimal(_value(value, "value")), _value(value, "currency")


def _datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class CoinbaseHttpClient:
    """Small read-only client using Coinbase's documented CDP JWT flow."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        client: httpx.Client | None = None,
        base_url: str = COINBASE_API_URL,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret.replace("\\n", "\n")
        self._client = client or httpx.Client(timeout=30.0)
        self._base_url = base_url.rstrip("/")

    def get_accounts(self, **params: Any) -> dict[str, Any]:
        return self._get("/api/v3/brokerage/accounts", params)

    def get_portfolios(self) -> dict[str, Any]:
        return self._get("/api/v3/brokerage/portfolios")

    def get_portfolio_breakdown(
        self, portfolio_uuid: str, *, currency: str
    ) -> dict[str, Any]:
        return self._get(
            f"/api/v3/brokerage/portfolios/{portfolio_uuid}",
            {"currency": currency},
        )

    def get_fills(self, **params: Any) -> dict[str, Any]:
        return self._get("/api/v3/brokerage/orders/historical/fills", params)

    def get_public_candles(self, *, product_id: str, **params: Any) -> dict[str, Any]:
        return self._get(
            f"/api/v3/brokerage/market/products/{product_id}/candles",
            params,
        )

    def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._client.get(
            f"{self._base_url}{path}",
            params={key: value for key, value in (params or {}).items() if value is not None},
            headers={
                "Authorization": f"Bearer {self._bearer_token('GET', path)}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Coinbase returned an invalid JSON response")
        return payload

    def _bearer_token(self, method: str, path: str) -> str:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - installation failure
            raise RuntimeError("PyJWT is not installed") from exc
        try:
            private_key = serialization.load_pem_private_key(
                self._api_secret.encode("utf-8"), password=None
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Coinbase API secret is not a valid ECDSA private key") from exc
        now = int(time.time())
        return jwt.encode(
            {
                "sub": self._api_key,
                "iss": "cdp",
                "nbf": now,
                "exp": now + 120,
                "uri": f"{method} api.coinbase.com{path}",
            },
            private_key,
            algorithm="ES256",
            headers={"kid": self._api_key, "nonce": secrets.token_hex()},
        )


class CoinbaseAdapter(BaseAdapter):
    """Import Coinbase balances, spot positions, fills and public EUR candles."""

    source = AccountSource.COINBASE

    def __init__(
        self,
        credentials: dict[str, Any] | None = None,
        label: str = "Coinbase",
        *,
        client: Any | None = None,
    ) -> None:
        self._creds = credentials or {}
        self._label = label
        self._client = client
        self._accounts: list[Any] | None = None

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
        self._accounts = None

    def list_accounts(self) -> list[RawAccount]:
        if not self.is_configured():
            return []
        result: list[RawAccount] = []
        for row in self._load_accounts():
            currency = str(_value(row, "currency") or "").upper()
            available, _ = _amount(_value(row, "available_balance"))
            hold, _ = _amount(_value(row, "hold"))
            if currency not in FIAT_ASSETS or available + hold <= ZERO:
                continue
            uuid = str(_value(row, "uuid") or currency)
            result.append(
                RawAccount(
                    external_id=f"coinbase-cash-{uuid}",
                    name=f"{self._label} {currency}",
                    currency=currency,
                    account_type=AccountType.BROKER_CASH,
                )
            )
        return result

    def fetch_transactions(
        self, account: RawAccount, since: date, until: date
    ) -> list[RawTransaction]:
        # Coinbase Advanced Trade exposes spot fills separately. They are
        # imported into the asset ledger rather than duplicated as cash rows.
        return []

    def fetch_balance(self, account: RawAccount) -> RawBalance | None:
        prefix = "coinbase-cash-"
        if not account.external_id.startswith(prefix):
            return None
        uuid = account.external_id[len(prefix):]
        for row in self._load_accounts():
            if str(_value(row, "uuid") or "") != uuid:
                continue
            available, currency = _amount(_value(row, "available_balance"))
            hold, _ = _amount(_value(row, "hold"))
            return RawBalance(
                booked=available + hold,
                available=available,
                currency=str(currency or account.currency),
                raw_payload={"account": _payload(row)},
            )
        return None

    def fetch_portfolios(
        self,
        history_range: str = "5d",
        known_history_external_ids: set[str] | None = None,
    ) -> list[RawPortfolio]:
        if not self.is_configured():
            return []
        client = self._api()
        response = client.get_portfolios()
        portfolio_rows = list(_value(response, "portfolios", []) or [])
        result: list[RawPortfolio] = []
        for portfolio_row in portfolio_rows:
            uuid = str(_value(portfolio_row, "uuid") or "").strip()
            if not uuid:
                continue
            breakdown_response = client.get_portfolio_breakdown(uuid, currency="EUR")
            breakdown = _value(breakdown_response, "breakdown")
            if breakdown is None:
                continue
            trades, trades_complete = self._fills(client, uuid)
            earliest_by_asset: dict[str, datetime] = {}
            for trade in trades:
                earliest_by_asset[trade.instrument_external_id] = min(
                    trade.timestamp,
                    earliest_by_asset.get(trade.instrument_external_id, trade.timestamp),
                )
            positions = self._positions(breakdown)
            price_history: list[RawAssetPricePoint] = []
            for position in positions:
                price_history.extend(
                    self._eur_price_history(
                        client,
                        position.external_id,
                        history_range,
                        earliest_by_asset.get(position.external_id),
                    )
                )

            balances = _value(breakdown, "portfolio_balances")
            crypto_total, _ = _amount(_value(balances, "total_crypto_balance"))
            cash_total, _ = _amount(_value(balances, "total_cash_equivalent_balance"))
            total_cost = sum(
                (
                    position.average_buy_in * position.quantity
                    for position in positions
                    if position.average_buy_in is not None
                ),
                ZERO,
            )
            now = datetime.now(timezone.utc)
            result.append(
                RawPortfolio(
                    external_id=f"coinbase:{uuid}",
                    name=str(_value(portfolio_row, "name") or self._label),
                    currency="EUR",
                    positions=positions,
                    price_history=price_history,
                    value_history=[
                        RawPortfolioValuePoint(
                            timestamp=now,
                            market_value=crypto_total,
                            cash_balance=cash_total,
                            currency="EUR",
                            history_range="max",
                            raw_payload={
                                "performance": {
                                    "absoluteValue": str(crypto_total - total_cost),
                                    "costValue": str(total_cost),
                                },
                                "provider": "coinbase",
                            },
                        )
                    ],
                    trades=trades,
                    trades_complete=trades_complete,
                    captured_at=now,
                )
            )
        return result

    def _positions(self, breakdown: Any) -> list[RawAssetPosition]:
        result: list[RawAssetPosition] = []
        for row in _value(breakdown, "spot_positions", []) or []:
            asset = str(_value(row, "asset") or "").upper()
            quantity = _decimal(_value(row, "total_balance_crypto"))
            market_value = _decimal(_value(row, "total_balance_fiat"))
            if not asset or asset in FIAT_ASSETS or quantity <= ZERO:
                continue
            cost_basis, cost_currency = _amount(_value(row, "cost_basis"))
            result.append(
                RawAssetPosition(
                    external_id=asset,
                    name=asset,
                    asset_type="crypto",
                    quantity=quantity,
                    currency=str(cost_currency or "EUR"),
                    average_buy_in=cost_basis / quantity if cost_basis else None,
                    current_price=market_value / quantity if market_value else None,
                    market_value=market_value,
                    raw_payload={"position": _payload(row)},
                )
            )
        return result

    def _fills(self, client: Any, portfolio_uuid: str) -> tuple[list[RawAssetTrade], bool]:
        cursor: str | None = None
        seen: set[str] = set()
        result: list[RawAssetTrade] = []
        complete = True
        while True:
            response = client.get_fills(
                retail_portfolio_id=portfolio_uuid,
                limit=100,
                cursor=cursor,
                sort_by="TRADE_TIME_ASC",
            )
            rows = list(_value(response, "fills", []) or [])
            for row in rows:
                product_id = str(_value(row, "product_id") or "")
                if "-" not in product_id:
                    complete = False
                    continue
                asset, quote = product_id.rsplit("-", 1)
                # The performance engine currently uses one portfolio currency.
                # Keep non-EUR fills out rather than silently treating USD as EUR.
                if quote != "EUR":
                    complete = False
                    continue
                trade_id = str(_value(row, "entry_id") or _value(row, "trade_id") or "")
                trade_time = _value(row, "trade_time")
                quantity = abs(_decimal(_value(row, "size")))
                if not trade_id or not trade_time or quantity <= ZERO:
                    continue
                price = _decimal(_value(row, "price"))
                result.append(
                    RawAssetTrade(
                        external_id=f"coinbase:fill:{trade_id}",
                        instrument_external_id=asset,
                        timestamp=_datetime(trade_time),
                        side=str(_value(row, "side") or "").lower(),
                        quantity=quantity,
                        cash_amount=abs(
                            _decimal(_value(row, "size_in_quote")) or price * quantity
                        ),
                        fees=abs(_decimal(_value(row, "commission"))) or None,
                        currency="EUR",
                        raw_payload={"fill": _payload(row)},
                    )
                )
            next_cursor = str(_value(response, "cursor") or "")
            if not rows or not next_cursor or next_cursor in seen:
                break
            seen.add(next_cursor)
            cursor = next_cursor
        return result, complete

    def _eur_price_history(
        self,
        client: Any,
        asset: str,
        history_range: str,
        first_trade: datetime | None,
    ) -> list[RawAssetPricePoint]:
        now = datetime.now(timezone.utc)
        range_days = {"1d": 2, "5d": 7, "1m": 35, "1y": 370}
        start = first_trade if history_range == "max" and first_trade else now - timedelta(
            days=range_days.get(history_range, 370)
        )
        cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
        product_id = f"{asset}-EUR"
        result: list[RawAssetPricePoint] = []
        while cursor < now:
            window_end = min(cursor + timedelta(days=299), now)
            try:
                response = client.get_public_candles(
                    product_id=product_id,
                    start=str(int(cursor.timestamp())),
                    end=str(int(window_end.timestamp())),
                    granularity="ONE_DAY",
                    limit=300,
                )
            except Exception as exc:  # public price gaps must not block account sync
                logger.info("Coinbase has no EUR candle history for %s: %s", asset, exc)
                return result
            for candle in _value(response, "candles", []) or []:
                timestamp = datetime.fromtimestamp(
                    int(_value(candle, "start") or 0), tz=timezone.utc
                )
                result.append(
                    RawAssetPricePoint(
                        external_id=asset,
                        exchange="COINBASE",
                        timestamp=timestamp,
                        open=_decimal(_value(candle, "open")),
                        high=_decimal(_value(candle, "high")),
                        low=_decimal(_value(candle, "low")),
                        close=_decimal(_value(candle, "close")),
                        volume=_decimal(_value(candle, "volume")),
                        currency="EUR",
                    )
                )
            cursor = window_end + timedelta(seconds=1)
        return result

    def _load_accounts(self) -> list[Any]:
        if self._accounts is not None:
            return self._accounts
        client = self._api()
        cursor: str | None = None
        result: list[Any] = []
        seen: set[str] = set()
        while True:
            response = client.get_accounts(limit=250, cursor=cursor)
            rows = list(_value(response, "accounts", []) or [])
            result.extend(rows)
            next_cursor = str(_value(response, "cursor") or "")
            if not bool(_value(response, "has_next", False)) or not next_cursor or next_cursor in seen:
                break
            seen.add(next_cursor)
            cursor = next_cursor
        self._accounts = result
        return result

    def _api(self) -> Any:
        if self._client is not None:
            return self._client
        secret = str(self._creds.get("api_secret") or "").replace("\\n", "\n")
        self._client = CoinbaseHttpClient(
            str(self._creds.get("api_key") or ""),
            secret,
        )
        return self._client
