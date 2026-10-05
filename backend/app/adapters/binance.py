"""Official Binance REST API adapter for read-only asset synchronisation."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

from app.adapters.base import (
    BaseAdapter,
    RawAccount,
    RawAssetPosition,
    RawAssetPricePoint,
    RawAssetTrade,
    RawBalance,
    RawPortfolio,
    RawTransaction,
)
from app.models.enums import AccountSource, AccountType

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
EUR_EQUIVALENTS = {"EUR", "EURI"}
FIAT_ASSETS = {
    "AUD", "BRL", "CAD", "CHF", "CZK", "EUR", "GBP", "HKD", "HUF",
    "JPY", "MXN", "NGN", "NZD", "PLN", "RON", "RUB", "TRY", "UAH",
    "USD", "ZAR",
}
QUOTE_PRIORITY = ("EUR", "EURI", "USDT", "USDC", "BTC")
TRADE_QUOTE_ASSETS = (*QUOTE_PRIORITY, "BUSD", "FDUSD", "TUSD", "ETH", "BNB")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return ZERO


class BinanceAdapter(BaseAdapter):
    """Read balances, trades and prices from Binance's documented API.

    This adapter intentionally implements no order, transfer, or withdrawal
    operation. It only uses signed USER_DATA queries; Binance exposes some
    read-only wallet queries as POST endpoints.
    """

    source = AccountSource.BINANCE

    def __init__(
        self,
        credentials: dict[str, Any] | None = None,
        label: str = "Binance",
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._creds = credentials or {}
        self._label = label
        self._base_url = str(self._creds.get("base_url") or "https://api.binance.com").rstrip("/")
        self._client = client
        self._server_offset_ms: int | None = None
        self._cached_balances: list[tuple[str, Decimal, dict[str, Any]]] | None = None
        self._known_trade_external_ids: set[str] = set()
        self._known_trade_instruments: set[str] = set()
        self._known_trade_symbols: set[str] = set()
        self._has_complete_trade_history = False
        self._ledger_backfill_ok = True
        self._historical_eur_cache: dict[tuple[str, int], Decimal | None] = {}

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
        # A registry instance can serve more than one sync job. Never reuse a
        # previous job's account snapshot, but do reuse one snapshot inside the
        # same job for Accounts and Assets.
        self._cached_balances = None
        self._known_trade_external_ids = set(known_trade_external_ids)
        self._has_complete_trade_history = has_complete_trade_history
        self._known_trade_instruments = set(known_trade_instruments or set())
        self._known_trade_symbols = set(known_trade_symbols or set())
        self._historical_eur_cache = {}
        self._ledger_backfill_ok = True

    def list_accounts(self) -> list[RawAccount]:
        # Fiat belongs in Accounts, not in the investment portfolio. Return one
        # provider balance per positive fiat currency; crypto and stablecoins
        # remain portfolio positions.
        if not self.is_configured():
            return []
        balances = self._load_current_balances()
        return [
            RawAccount(
                external_id=f"binance-cash-{asset}",
                name=f"Binance {asset}",
                currency=asset,
                account_type=AccountType.BROKER_CASH,
            )
            for asset, quantity, _raw in balances
            if asset in FIAT_ASSETS and quantity > ZERO
        ]

    def fetch_transactions(
        self, account: RawAccount, since: date, until: date
    ) -> list[RawTransaction]:
        return []

    def fetch_balance(self, account: RawAccount) -> RawBalance | None:
        prefix = "binance-cash-"
        if not account.external_id.startswith(prefix):
            return None
        asset = account.external_id[len(prefix):]
        for balance_asset, quantity, raw in self._load_current_balances():
            if balance_asset == asset:
                return RawBalance(
                    booked=quantity,
                    available=self._available_cash(raw),
                    currency=asset,
                    raw_payload={"locations": raw},
                )
        return RawBalance(booked=ZERO, available=ZERO, currency=asset)

    @staticmethod
    def _available_cash(raw: dict[str, Any]) -> Decimal:
        """Return immediately available fiat, excluding locked and Earn funds."""
        available = ZERO
        spot = raw.get("spot")
        if isinstance(spot, dict):
            available += _decimal(spot.get("free"))
        for funding in raw.get("funding") or []:
            if isinstance(funding, dict):
                available += _decimal(funding.get("free"))
        return available

    def fetch_portfolios(
        self,
        history_range: str = "5d",
        known_history_external_ids: set[str] | None = None,
    ) -> list[RawPortfolio]:
        if not self.is_configured():
            return []

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            # Existing short-range candles must not prevent a first complete
            # backfill for assets that were discovered only on a later sync.
            effective_history_range = (
                history_range if self._has_complete_trade_history else "max"
            )
            tickers = self._ticker_map(client)
            symbols = self._symbol_map(client)
            balances = self._load_current_balances(client)
            positions: list[RawAssetPosition] = []
            history: list[RawAssetPricePoint] = []
            asset_trades: list[RawAssetTrade] = []
            completed_trade_symbols: set[str] = set()

            balance_assets = {asset for asset, _quantity, _raw in balances}
            for asset in sorted(self._known_trade_instruments - balance_assets):
                balances.append((asset, ZERO, {"historical_only": True}))
            for asset, quantity, raw_balance in balances:
                # Fiat is cash, not an investment position. Stablecoins remain
                # visible as crypto assets, but actual fiat belongs in Accounts.
                if asset in FIAT_ASSETS:
                    continue
                quote = self._pick_quote(asset, symbols, tickers)
                eur_price = self._price_in_eur(asset, tickers)
                market_value = quantity * eur_price if eur_price is not None else None
                average_buy_in = None
                trade_symbols: list[str] = []
                trade_summary: dict[str, Any] = {}
                historical_trade_symbols = self._trade_symbols_for_asset(
                    asset, symbols, tickers
                )

                if historical_trade_symbols and asset not in EUR_EQUIVALENTS:
                    try:
                        normalized_trades: list[dict[str, Any]] = []
                        for trade_symbol in historical_trade_symbols:
                            try:
                                rows = self._all_spot_trades(client, trade_symbol)
                            except httpx.HTTPStatusError as exc:
                                # Historical pairs may be delisted while
                                # remaining valid in the account's old ledger.
                                # Binance answers those symbols with -1121;
                                # skip that pair but preserve real API errors.
                                if exc.response.status_code == 400:
                                    logger.info(
                                        "Binance historical pair unavailable: %s",
                                        trade_symbol,
                                    )
                                    continue
                                raise
                            completed_trade_symbols.add(trade_symbol)
                            if rows:
                                trade_symbols.append(trade_symbol)
                                trade_quote = trade_symbol[len(asset):]
                                asset_trades.extend(
                                    self._map_spot_trade_ledger(
                                        client,
                                        rows,
                                        base_asset=asset,
                                        quote_asset=trade_quote,
                                    )
                                )
                                normalized_trades.extend(
                                    self._normalize_trades_to_historical_eur(
                                        client,
                                        rows,
                                        base_asset=asset,
                                        quote_asset=trade_quote,
                                    )
                                )
                        average_eur, trade_summary = self._open_average_cost(
                            normalized_trades, asset, "EUR"
                        )
                        trade_summary["method"] = "moving_average_spot_trades_eur"
                        trade_summary["trade_symbols"] = trade_symbols
                        for cost_point in trade_summary.get("history") or []:
                            cost_point["open_cost_eur"] = cost_point["open_cost"]
                        tracked_quantity = _decimal(
                            trade_summary.get("open_trade_quantity")
                        )
                        tolerance = max(Decimal("0.00000001"), quantity * Decimal("0.001"))
                        quantities_match = abs(tracked_quantity - quantity) <= tolerance
                        trade_summary["matches_total_quantity"] = quantities_match
                        # Transfers, Earn rewards and dust conversions can make
                        # the current quantity differ from Spot executions. The
                        # trade-derived unit cost is still the best independent
                        # basis; the mismatch remains explicit in raw metadata.
                        if average_eur is not None:
                            average_buy_in = average_eur
                    except httpx.HTTPStatusError as exc:
                        # A balance can originate from deposits, distributions,
                        # Convert or Earn and therefore have no Spot trade pair.
                        logger.info("No Spot trade history for %s: %s", asset, exc)
                        self._mark_retryable_history_error(exc)

                positions.append(
                    RawAssetPosition(
                        external_id=asset,
                        name=asset,
                        asset_type="crypto",
                        quantity=quantity,
                        currency="EUR",
                        average_buy_in=average_buy_in,
                        current_price=eur_price,
                        market_value=market_value,
                        raw_payload={
                            "balance": raw_balance,
                            "pricing_symbol": f"{asset}{quote}" if quote else None,
                            "trade_symbols": trade_symbols,
                            "cost_basis": trade_summary or None,
                        },
                    )
                )

                if quote is not None and asset not in EUR_EQUIVALENTS:
                    history.extend(
                        self._price_history(
                            client,
                            asset=asset,
                            quote=quote,
                            history_range=effective_history_range,
                            tickers=tickers,
                        )
                    )

            asset_trades = self._deduplicate_trades(
                asset_trades + self._fetch_capital_history(client)
            )
            priced_assets = {point.external_id for point in history}
            for traded_asset in {
                trade.instrument_external_id for trade in asset_trades
            } - priced_assets - FIAT_ASSETS:
                quote = self._pick_quote(traded_asset, symbols, tickers)
                if quote is not None:
                    history.extend(
                        self._price_history(
                            client,
                            asset=traded_asset,
                            quote=quote,
                            history_range=effective_history_range,
                            tickers=tickers,
                        )
                    )

            positions = [position for position in positions if position.quantity > ZERO]
            return [
                RawPortfolio(
                    external_id="binance-spot",
                    name=self._label,
                    currency="EUR",
                    positions=positions,
                    price_history=history,
                    trades=asset_trades,
                    trades_complete=self._ledger_backfill_ok,
                    completed_trade_symbols=completed_trade_symbols,
                )
            ]
        finally:
            if owns_client:
                client.close()

    def _signed_get(
        self, client: httpx.Client, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        return self._signed_request(client, "GET", path, params)

    def _signed_post(
        self, client: httpx.Client, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        return self._signed_request(client, "POST", path, params)

    def _signed_request(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if self._server_offset_ms is None:
            server = client.get(f"{self._base_url}/api/v3/time")
            server.raise_for_status()
            self._server_offset_ms = int(server.json()["serverTime"]) - int(time.time() * 1000)

        payload = dict(params or {})
        payload["recvWindow"] = 5000
        payload["timestamp"] = int(time.time() * 1000) + self._server_offset_ms
        encoded = urlencode(payload)
        signature = hmac.new(
            str(self._creds["api_secret"]).encode(),
            encoded.encode(),
            hashlib.sha256,
        ).hexdigest()
        signed = f"{encoded}&signature={signature}"
        request_kwargs: dict[str, Any] = {
            "headers": {"X-MBX-APIKEY": str(self._creds["api_key"])},
        }
        if method == "POST":
            request_kwargs["content"] = signed
            request_kwargs["headers"]["Content-Type"] = (
                "application/x-www-form-urlencoded"
            )
        else:
            request_kwargs["params"] = signed
        response = client.request(method, f"{self._base_url}{path}", **request_kwargs)
        response.raise_for_status()
        return response.json()

    def _load_current_balances(
        self, client: httpx.Client | None = None
    ) -> list[tuple[str, Decimal, dict[str, Any]]]:
        if self._cached_balances is not None:
            return self._cached_balances
        owns_client = client is None
        current_client = client or self._client or httpx.Client(timeout=30.0)
        owns_client = owns_client and self._client is None
        try:
            account = self._signed_get(
                current_client,
                "/api/v3/account",
                {"omitZeroBalances": "true"},
            )
            balances = self._positive_balances(account)
            balances = self._merge_funding_balances(current_client, balances)
            balances = self._merge_earn_balances(current_client, balances)
            self._cached_balances = balances
            return balances
        finally:
            if owns_client:
                current_client.close()

    def _merge_funding_balances(
        self,
        client: httpx.Client,
        spot: list[tuple[str, Decimal, dict[str, Any]]],
    ) -> list[tuple[str, Decimal, dict[str, Any]]]:
        merged: dict[str, tuple[Decimal, dict[str, Any]]] = {
            asset: (quantity, {"spot": raw}) for asset, quantity, raw in spot
        }
        try:
            payload = self._signed_post(
                client,
                "/sapi/v1/asset/get-funding-asset",
                {"needBtcValuation": "true"},
            )
        except httpx.HTTPStatusError as exc:
            logger.info("Binance funding wallet unavailable: %s", exc)
            return [(asset, quantity, raw) for asset, (quantity, raw) in merged.items()]
        rows = payload if isinstance(payload, list) else []
        for row in rows:
            asset = str(row.get("asset") or "")
            amount = (
                _decimal(row.get("free"))
                + _decimal(row.get("locked"))
                + _decimal(row.get("freeze"))
                + _decimal(row.get("withdrawing"))
            )
            if not asset or amount <= ZERO:
                continue
            current, raw = merged.get(asset, (ZERO, {}))
            entries = list(raw.get("funding") or [])
            entries.append(row)
            raw["funding"] = entries
            merged[asset] = (current + amount, raw)
        return [(asset, quantity, raw) for asset, (quantity, raw) in merged.items()]

    def _all_spot_trades(
        self, client: httpx.Client, symbol: str
    ) -> list[dict[str, Any]]:
        """Page complete Spot history; cost basis must never depend on the sync window."""
        params: dict[str, Any] = {
            "symbol": symbol,
            "startTime": int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
            "limit": 1000,
        }
        result: list[dict[str, Any]] = []
        while True:
            rows = self._signed_get(client, "/api/v3/myTrades", params)
            if not isinstance(rows, list) or not rows:
                break
            result.extend(rows)
            if len(rows) < 1000 or rows[-1].get("id") is None:
                break
            params = {
                "symbol": symbol,
                "fromId": int(rows[-1]["id"]) + 1,
                "limit": 1000,
            }
        return result

    def _map_spot_trade_ledger(
        self,
        client: httpx.Client,
        rows: list[dict[str, Any]],
        *,
        base_asset: str,
        quote_asset: str,
    ) -> list[RawAssetTrade]:
        """Represent both legs of every Spot execution in EUR."""
        result: list[RawAssetTrade] = []
        for row in rows:
            timestamp_ms = int(row.get("time") or 0)
            trade_id = row.get("id")
            if timestamp_ms <= 0 or trade_id is None:
                continue
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            quantity = _decimal(row.get("qty"))
            quote_quantity = _decimal(row.get("quoteQty"))
            commission = _decimal(row.get("commission"))
            commission_asset = str(row.get("commissionAsset") or "")
            quote_eur = self._historical_eur_price(client, quote_asset, timestamp_ms)
            if quote_eur is None:
                continue
            eur_value = quote_quantity * quote_eur
            is_buyer = bool(row.get("isBuyer"))
            base_quantity = quantity
            quote_leg_quantity = quote_quantity
            if commission_asset == base_asset:
                base_quantity = quantity - commission if is_buyer else quantity + commission
            elif commission_asset == quote_asset:
                quote_leg_quantity = (
                    quote_quantity + commission if is_buyer else quote_quantity - commission
                )
                # ``quoteQty`` is the executed notional.  The commission is
                # already represented by ``fees`` on the base leg below; do
                # not add it to ``eur_value`` as well or a quote-currency fee
                # is charged twice to the base cost basis.
            symbol = f"{base_asset}{quote_asset}"
            raw = {"kind": "spot_trade", "symbol": symbol, "trade": row}
            commission_eur = (
                commission
                * self._historical_eur_price(client, commission_asset, timestamp_ms)
                if commission > ZERO and commission_asset
                else None
            )
            # A base-currency fee is an additional acquisition cost on a buy,
            # but on a sell it is already represented by the extra base units
            # leaving the wallet. A quote-currency fee reduces the cash
            # proceeds on a sell; on a buy it is an additional cash outflow.
            base_fees = (
                commission_eur
                if is_buyer or commission_asset == quote_asset
                else None
            )
            result.append(
                RawAssetTrade(
                    external_id=f"binance:spot:{symbol}:{trade_id}:base",
                    instrument_external_id=base_asset,
                    timestamp=timestamp,
                    side="buy" if is_buyer else "sell",
                    quantity=max(base_quantity, ZERO),
                    cash_amount=eur_value,
                    fees=base_fees,
                    currency="EUR",
                    raw_payload=raw,
                )
            )
            if quote_asset not in FIAT_ASSETS:
                result.append(
                    RawAssetTrade(
                        external_id=f"binance:spot:{symbol}:{trade_id}:quote",
                        instrument_external_id=quote_asset,
                        timestamp=timestamp,
                        side="sell" if is_buyer else "buy",
                        quantity=max(quote_leg_quantity, ZERO),
                        # When a quote-currency fee is charged on a sell,
                        # quoteQty is the gross received amount while the
                        # position only receives the net amount. Keep the
                        # quote leg's cash and quantity aligned so its cost
                        # basis is not overstated on later conversions.
                        cash_amount=(
                            max(quote_quantity - commission, ZERO) * quote_eur
                            if not is_buyer and commission_asset == quote_asset
                            else eur_value
                        ),
                        currency="EUR",
                        raw_payload=raw,
                    )
                )
            if (
                commission > ZERO
                and commission_asset
                and commission_asset not in {base_asset, quote_asset}
                and commission_asset not in FIAT_ASSETS
            ):
                result.append(
                    RawAssetTrade(
                        external_id=f"binance:spot:{symbol}:{trade_id}:fee",
                        instrument_external_id=commission_asset,
                        timestamp=timestamp,
                        side="sell",
                        quantity=commission,
                        cash_amount=ZERO,
                        fees=commission
                        * (self._historical_eur_price(client, commission_asset, timestamp_ms) or ZERO),
                        currency="EUR",
                        raw_payload=raw,
                    )
                )
        return result

    def _fetch_capital_history(self, client: httpx.Client) -> list[RawAssetTrade]:
        """Load deposits, withdrawals and asset distributions as ledger events."""
        start = (
            datetime.now(timezone.utc) - timedelta(days=8)
            if self._has_complete_trade_history
            else datetime(2017, 1, 1, tzinfo=timezone.utc)
        )
        end = datetime.now(timezone.utc)
        result: list[RawAssetTrade] = []
        cursor = start
        while cursor < end:
            window_end = min(cursor + timedelta(days=89), end)
            params = {
                "startTime": int(cursor.timestamp() * 1000),
                "endTime": int(window_end.timestamp() * 1000),
                "limit": 1000,
            }
            for path, kind in (
                ("/sapi/v1/capital/deposit/hisrec", "deposit"),
                ("/sapi/v1/capital/withdraw/history", "withdrawal"),
            ):
                try:
                    rows = self._signed_get(client, path, params)
                except httpx.HTTPStatusError as exc:
                    logger.info("Binance %s history unavailable: %s", kind, exc)
                    self._mark_retryable_history_error(exc)
                    continue
                for row in rows if isinstance(rows, list) else []:
                    mapped = self._map_capital_event(client, row, kind)
                    if mapped is not None:
                        result.append(mapped)
            cursor = window_end + timedelta(milliseconds=1)
        result.extend(self._fetch_asset_dividends(client, start, end))
        result.extend(self._fetch_convert_history(client, start, end))
        result.extend(self._fetch_earn_rewards(client, start, end))
        result.extend(self._fetch_dust_history(client))
        return result

    def _fetch_convert_history(
        self, client: httpx.Client, start: datetime, end: datetime
    ) -> list[RawAssetTrade]:
        # Binance exposes Convert only for a bounded recent history. Starting at
        # account inception creates hundreds of guaranteed-empty requests and
        # can exhaust the UID rate limit before current records are reached.
        start = max(start, end - timedelta(days=179))
        result: list[RawAssetTrade] = []
        cursor = start
        while cursor < end:
            window_end = min(cursor + timedelta(days=29), end)
            page = 1
            while True:
                try:
                    payload = self._signed_get(
                        client,
                        "/sapi/v1/convert/tradeFlow",
                        {
                            "startTime": int(cursor.timestamp() * 1000),
                            "endTime": int(window_end.timestamp() * 1000),
                            "limit": 1000,
                            "page": page,
                        },
                    )
                except httpx.HTTPStatusError as exc:
                    logger.info("Binance Convert history unavailable: %s", exc)
                    self._mark_retryable_history_error(exc)
                    return result
                rows = payload.get("list") if isinstance(payload, dict) else []
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:
                    result.extend(self._map_convert_event(client, row))
                if not payload.get("moreData"):
                    break
                page += 1
            cursor = window_end + timedelta(milliseconds=1)
        return result

    def _map_convert_event(
        self, client: httpx.Client, row: dict[str, Any]
    ) -> list[RawAssetTrade]:
        if str(row.get("orderStatus") or "SUCCESS").upper() != "SUCCESS":
            return []
        from_asset = str(row.get("fromAsset") or "")
        to_asset = str(row.get("toAsset") or "")
        from_amount = _decimal(row.get("fromAmount"))
        to_amount = _decimal(row.get("toAmount"))
        timestamp_ms = self._timestamp_ms(row.get("createTime"))
        event_id = str(row.get("orderId") or row.get("quoteId") or "")
        if (
            not from_asset
            or not to_asset
            or from_amount <= ZERO
            or to_amount <= ZERO
            or timestamp_ms is None
            or not event_id
        ):
            return []
        from_price = self._historical_eur_price(client, from_asset, timestamp_ms)
        to_price = self._historical_eur_price(client, to_asset, timestamp_ms)
        eur_value = (
            from_amount * from_price
            if from_price is not None
            else to_amount * to_price if to_price is not None else None
        )
        if eur_value is None:
            return []
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        raw = {"kind": "convert", "event": row}
        result: list[RawAssetTrade] = []
        if from_asset not in FIAT_ASSETS:
            result.append(
                RawAssetTrade(
                    external_id=f"binance:convert:{event_id}:from",
                    instrument_external_id=from_asset,
                    timestamp=timestamp,
                    side="sell",
                    quantity=from_amount,
                    cash_amount=eur_value,
                    currency="EUR",
                    raw_payload=raw,
                )
            )
        if to_asset not in FIAT_ASSETS:
            result.append(
                RawAssetTrade(
                    external_id=f"binance:convert:{event_id}:to",
                    instrument_external_id=to_asset,
                    timestamp=timestamp,
                    side="buy",
                    quantity=to_amount,
                    cash_amount=eur_value,
                    currency="EUR",
                    raw_payload=raw,
                )
            )
        return result

    def _fetch_earn_rewards(
        self, client: httpx.Client, start: datetime, end: datetime
    ) -> list[RawAssetTrade]:
        # The rewards endpoints reject old windows instead of returning an empty
        # result. Query their supported recent window and persist it incrementally.
        start = max(start, end - timedelta(days=29))
        result: list[RawAssetTrade] = []
        paths = (
            "/sapi/v1/simple-earn/flexible/history/rewardsRecord",
            "/sapi/v1/simple-earn/locked/history/rewardsRecord",
        )
        for path in paths:
            window_start = start
            while window_start < end:
                window_end = min(window_start + timedelta(days=29), end)
                current = 1
                while True:
                    try:
                        payload = self._signed_get(
                            client,
                            path,
                            {
                                "startTime": int(window_start.timestamp() * 1000),
                                "endTime": int(window_end.timestamp() * 1000),
                                "current": current,
                                "size": 100,
                            },
                        )
                    except httpx.HTTPStatusError as exc:
                        logger.info("Binance Earn reward history unavailable: %s", exc)
                        self._mark_retryable_history_error(exc)
                        return result
                    rows = payload.get("rows") if isinstance(payload, dict) else []
                    if not isinstance(rows, list) or not rows:
                        break
                    for row in rows:
                        asset = str(row.get("asset") or "")
                        amount = _decimal(
                            row.get("rewards")
                            or row.get("amount")
                            or row.get("rewardAmt")
                        )
                        timestamp_ms = self._timestamp_ms(
                            row.get("time") or row.get("createTime")
                        )
                        event_id = str(
                            row.get("id")
                            or row.get("tranId")
                            or f"{asset}:{timestamp_ms}:{amount}"
                        )
                        if asset and amount > ZERO and timestamp_ms is not None:
                            result.append(
                                RawAssetTrade(
                                    external_id=f"binance:earn:{path.split('/')[-3]}:{event_id}",
                                    instrument_external_id=asset,
                                    timestamp=datetime.fromtimestamp(
                                        timestamp_ms / 1000, tz=timezone.utc
                                    ),
                                    side="buy",
                                    quantity=amount,
                                    cash_amount=ZERO,
                                    currency="EUR",
                                    raw_payload={"kind": "earn_reward", "event": row},
                                )
                            )
                    total = int(payload.get("total") or len(rows))
                    if current * 100 >= total or len(rows) < 100:
                        break
                    current += 1
                window_start = window_end + timedelta(milliseconds=1)
        return result

    def _fetch_dust_history(self, client: httpx.Client) -> list[RawAssetTrade]:
        try:
            payload = self._signed_get(client, "/sapi/v1/asset/dribblet")
        except httpx.HTTPStatusError as exc:
            logger.info("Binance dust history unavailable: %s", exc)
            self._mark_retryable_history_error(exc)
            return []
        result: list[RawAssetTrade] = []
        for group in payload.get("userAssetDribblets") if isinstance(payload, dict) else []:
            timestamp_ms = self._timestamp_ms(group.get("operateTime"))
            if timestamp_ms is None:
                continue
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
            for row in group.get("userAssetDribbletDetails") or []:
                event_id = str(row.get("transId") or group.get("transId") or "")
                from_asset = str(row.get("fromAsset") or "")
                amount = _decimal(row.get("amount"))
                received = _decimal(row.get("transferedAmount"))
                fee = _decimal(row.get("serviceChargeAmount"))
                price = self._historical_eur_price(client, from_asset, timestamp_ms)
                if not event_id or not from_asset or amount <= ZERO or price is None:
                    continue
                eur_value = amount * price
                raw = {"kind": "dust", "event": row}
                result.append(
                    RawAssetTrade(
                        external_id=f"binance:dust:{event_id}:from",
                        instrument_external_id=from_asset,
                        timestamp=timestamp,
                        side="sell",
                        quantity=amount,
                        cash_amount=eur_value,
                        currency="EUR",
                        raw_payload=raw,
                    )
                )
                if received > ZERO:
                    result.append(
                        RawAssetTrade(
                            external_id=f"binance:dust:{event_id}:bnb",
                            instrument_external_id="BNB",
                            timestamp=timestamp,
                            side="buy",
                            quantity=max(ZERO, received - fee),
                            cash_amount=eur_value,
                            fees=(
                                fee
                                * (self._historical_eur_price(client, "BNB", timestamp_ms) or ZERO)
                                if fee > ZERO
                                else None
                            ),
                            currency="EUR",
                            raw_payload=raw,
                        )
                    )
        return result

    def _map_capital_event(
        self, client: httpx.Client, row: dict[str, Any], kind: str
    ) -> RawAssetTrade | None:
        status = row.get("status")
        if kind == "deposit" and status not in (1, 6, "1", "6"):
            return None
        if kind == "withdrawal" and status not in (6, "6"):
            return None
        asset = str(row.get("coin") or "")
        amount = _decimal(row.get("amount"))
        timestamp_value = row.get("insertTime") if kind == "deposit" else row.get("completeTime")
        timestamp_ms = self._timestamp_ms(timestamp_value or row.get("applyTime"))
        event_id = str(row.get("id") or row.get("txId") or "")
        if not asset or amount <= ZERO or timestamp_ms is None or not event_id:
            return None
        price = self._historical_eur_price(client, asset, timestamp_ms)
        if price is None:
            return None
        fee = _decimal(row.get("transactionFee")) if kind == "withdrawal" else ZERO
        quantity = amount + fee if kind == "withdrawal" else amount
        return RawAssetTrade(
            external_id=f"binance:{kind}:{event_id}",
            instrument_external_id=asset,
            timestamp=datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc),
            side="sell" if kind == "withdrawal" else "buy",
            quantity=quantity,
            cash_amount=quantity * price,
            fees=fee * price if fee > ZERO else None,
            currency="EUR",
            raw_payload={"kind": kind, "event": row, "external_flow": True},
        )

    def _fetch_asset_dividends(
        self, client: httpx.Client, start: datetime, end: datetime
    ) -> list[RawAssetTrade]:
        result: list[RawAssetTrade] = []
        cursor = start
        while cursor < end:
            window_end = min(cursor + timedelta(days=179), end)
            try:
                payload = self._signed_get(
                    client,
                    "/sapi/v1/asset/assetDividend",
                    {
                        "startTime": int(cursor.timestamp() * 1000),
                        "endTime": int(window_end.timestamp() * 1000),
                        "limit": 500,
                    },
                )
            except httpx.HTTPStatusError as exc:
                logger.info("Binance dividend history unavailable: %s", exc)
                self._mark_retryable_history_error(exc)
                return result
            rows = payload.get("rows") if isinstance(payload, dict) else []
            for row in rows if isinstance(rows, list) else []:
                asset = str(row.get("asset") or "")
                amount = _decimal(row.get("amount"))
                timestamp_ms = self._timestamp_ms(row.get("divTime"))
                event_id = str(row.get("id") or row.get("tranId") or "")
                if asset and amount > ZERO and timestamp_ms is not None and event_id:
                    result.append(
                        RawAssetTrade(
                            external_id=f"binance:dividend:{event_id}",
                            instrument_external_id=asset,
                            timestamp=datetime.fromtimestamp(
                                timestamp_ms / 1000, tz=timezone.utc
                            ),
                            side="buy",
                            quantity=amount,
                            cash_amount=ZERO,
                            currency="EUR",
                            raw_payload={"kind": "dividend", "event": row},
                        )
                    )
            cursor = window_end + timedelta(milliseconds=1)
        return result

    def _historical_eur_price(
        self, client: httpx.Client, asset: str, timestamp_ms: int
    ) -> Decimal | None:
        if not asset:
            return None
        if asset in EUR_EQUIVALENTS:
            return Decimal("1")
        bucket = timestamp_ms // 60_000
        cache_key = (asset, bucket)
        if cache_key in self._historical_eur_cache:
            return self._historical_eur_cache[cache_key]
        candidates = ((f"{asset}EUR", False), (f"EUR{asset}", True))
        for symbol, invert in candidates:
            price = self._kline_close_at(client, symbol, timestamp_ms)
            if price is not None and price > ZERO:
                value = Decimal("1") / price if invert else price
                self._historical_eur_cache[cache_key] = value
                return value
        if asset not in {"USDT", "USDC"}:
            asset_usdt = self._kline_close_at(client, f"{asset}USDT", timestamp_ms)
            usdt_eur = self._historical_eur_price(client, "USDT", timestamp_ms)
            if asset_usdt is not None and usdt_eur is not None:
                value = asset_usdt * usdt_eur
                self._historical_eur_cache[cache_key] = value
                return value
        self._historical_eur_cache[cache_key] = None
        return None

    def _kline_close_at(
        self, client: httpx.Client, symbol: str, timestamp_ms: int
    ) -> Decimal | None:
        response = client.get(
            f"{self._base_url}/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": "1m",
                "startTime": timestamp_ms - 60_000,
                "endTime": timestamp_ms + 60_000,
                "limit": 2,
            },
        )
        if response.status_code >= 400:
            return None
        rows = response.json()
        return _decimal(rows[-1][4]) if isinstance(rows, list) and rows else None

    @staticmethod
    def _timestamp_ms(value: Any) -> int | None:
        if isinstance(value, (int, float)):
            return int(value)
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            return None

    @staticmethod
    def _deduplicate_trades(trades: list[RawAssetTrade]) -> list[RawAssetTrade]:
        return list({trade.external_id: trade for trade in trades}.values())

    def _mark_retryable_history_error(self, exc: httpx.HTTPStatusError) -> None:
        if exc.response.status_code == 429 or exc.response.status_code >= 500:
            self._ledger_backfill_ok = False

    def _ticker_map(self, client: httpx.Client) -> dict[str, Decimal]:
        response = client.get(f"{self._base_url}/api/v3/ticker/price")
        response.raise_for_status()
        return {
            str(row["symbol"]): _decimal(row["price"])
            for row in response.json()
            if row.get("symbol") and _decimal(row.get("price")) > ZERO
        }

    def _symbol_map(self, client: httpx.Client) -> set[str]:
        response = client.get(f"{self._base_url}/api/v3/exchangeInfo")
        response.raise_for_status()
        return {
            str(row["symbol"])
            for row in response.json().get("symbols", [])
            if row.get("status") == "TRADING" and row.get("symbol")
        }

    @staticmethod
    def _positive_balances(account: dict[str, Any]) -> list[tuple[str, Decimal, dict[str, Any]]]:
        result = []
        for row in account.get("balances") or []:
            quantity = _decimal(row.get("free")) + _decimal(row.get("locked"))
            if row.get("asset") and quantity > ZERO:
                result.append((str(row["asset"]), quantity, row))
        return result

    def _merge_earn_balances(
        self,
        client: httpx.Client,
        spot: list[tuple[str, Decimal, dict[str, Any]]],
    ) -> list[tuple[str, Decimal, dict[str, Any]]]:
        """Add official Simple Earn positions to Spot without treating them as cash."""
        merged: dict[str, tuple[Decimal, dict[str, Any]]] = {
            asset: (quantity, dict(raw)) for asset, quantity, raw in spot
        }
        endpoints = (
            ("flexible_earn", "/sapi/v1/simple-earn/flexible/position", "totalAmount"),
            ("locked_earn", "/sapi/v1/simple-earn/locked/position", "amount"),
        )
        for bucket, path, amount_key in endpoints:
            try:
                rows = self._paged_earn_positions(client, path)
            except httpx.HTTPStatusError as exc:
                # Availability varies by account type and region. Spot remains
                # useful even if Simple Earn is not enabled for this API key.
                logger.info("Binance %s unavailable: %s", bucket, exc)
                continue
            for row in rows:
                asset = str(row.get("asset") or "")
                amount = _decimal(row.get(amount_key))
                if not asset or amount <= ZERO:
                    continue
                current, raw = merged.get(asset, (ZERO, {}))
                entries = list(raw.get(bucket) or [])
                entries.append(row)
                raw[bucket] = entries
                merged[asset] = (current + amount, raw)
        return [(asset, quantity, raw) for asset, (quantity, raw) in merged.items()]

    def _paged_earn_positions(
        self, client: httpx.Client, path: str
    ) -> list[dict[str, Any]]:
        current = 1
        size = 100
        result: list[dict[str, Any]] = []
        while True:
            payload = self._signed_get(
                client, path, {"current": current, "size": size}
            )
            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            result.extend(rows)
            total = int(payload.get("total") or len(result))
            if len(result) >= total or len(rows) < size:
                break
            current += 1
        return result

    @staticmethod
    def _pick_quote(asset: str, symbols: set[str], tickers: dict[str, Decimal]) -> str | None:
        for quote in QUOTE_PRIORITY:
            symbol = f"{asset}{quote}"
            if symbol in symbols and symbol in tickers:
                return quote
        return None

    @classmethod
    def _trade_quotes(
        cls, asset: str, symbols: set[str], tickers: dict[str, Decimal]
    ) -> list[str]:
        return [
            quote
            for quote in TRADE_QUOTE_ASSETS
            if quote != asset
            and f"{asset}{quote}" in symbols
            and cls._price_in_eur(quote, tickers) is not None
        ]

    def _trade_symbols_for_asset(
        self, asset: str, symbols: set[str], tickers: dict[str, Decimal]
    ) -> list[str]:
        """Return current and previously observed pairs for an asset.

        Binance's exchange-info endpoint omits delisted pairs.  A current
        balance can nevertheless be the remainder of trades executed through
        one of those pairs (VET/BTC is a typical example).  Keep the symbols
        seen in the encrypted ledger and ask ``myTrades`` for them as well;
        invalid/delisted symbols are skipped by the caller.
        """
        result = {
            f"{asset}{quote}"
            for quote in self._trade_quotes(asset, symbols, tickers)
        }
        for symbol in self._known_trade_symbols:
            if not symbol.startswith(asset):
                continue
            quote = symbol[len(asset):]
            if quote and quote != asset and quote in TRADE_QUOTE_ASSETS:
                result.add(symbol)
        return sorted(result)

    @classmethod
    def _normalize_trades_to_eur(
        cls,
        trades: list[dict[str, Any]],
        *,
        base_asset: str,
        quote_asset: str,
        tickers: dict[str, Decimal],
    ) -> list[dict[str, Any]]:
        quote_eur = cls._price_in_eur(quote_asset, tickers)
        if quote_eur is None:
            return []
        result: list[dict[str, Any]] = []
        for trade in trades:
            normalized = dict(trade)
            normalized["quoteQty"] = str(_decimal(trade.get("quoteQty")) * quote_eur)
            commission_asset = str(trade.get("commissionAsset") or "")
            if commission_asset and commission_asset != base_asset:
                commission_eur = cls._price_in_eur(commission_asset, tickers)
                if commission_eur is not None:
                    normalized["commission"] = str(
                        _decimal(trade.get("commission")) * commission_eur
                    )
                    normalized["commissionAsset"] = "EUR"
            result.append(normalized)
        return result

    def _normalize_trades_to_historical_eur(
        self,
        client: httpx.Client,
        trades: list[dict[str, Any]],
        *,
        base_asset: str,
        quote_asset: str,
    ) -> list[dict[str, Any]]:
        """Normalize each execution with the exchange rate at execution time."""
        result: list[dict[str, Any]] = []
        for trade in trades:
            timestamp_ms = int(trade.get("time") or 0)
            quote_eur = self._historical_eur_price(client, quote_asset, timestamp_ms)
            if timestamp_ms <= 0 or quote_eur is None:
                continue
            normalized = dict(trade)
            normalized["quoteQty"] = str(_decimal(trade.get("quoteQty")) * quote_eur)
            commission_asset = str(trade.get("commissionAsset") or "")
            if commission_asset and commission_asset != base_asset:
                commission_eur = self._historical_eur_price(
                    client, commission_asset, timestamp_ms
                )
                if commission_eur is not None:
                    normalized["commission"] = str(
                        _decimal(trade.get("commission")) * commission_eur
                    )
                    normalized["commissionAsset"] = "EUR"
            result.append(normalized)
        return result

    @staticmethod
    def _price_in_eur(asset: str, tickers: dict[str, Decimal]) -> Decimal | None:
        if asset in EUR_EQUIVALENTS:
            return Decimal("1")
        direct = tickers.get(f"{asset}EUR") or tickers.get(f"{asset}EURI")
        if direct is not None:
            return direct
        for bridge in ("USDT", "USDC", "BTC"):
            asset_bridge = Decimal("1") if asset == bridge else tickers.get(f"{asset}{bridge}")
            bridge_eur = tickers.get(f"{bridge}EUR") or tickers.get(f"{bridge}EURI")
            if asset_bridge is not None and bridge_eur is not None:
                return asset_bridge * bridge_eur
        return None

    @staticmethod
    def _open_average_cost(
        trades: list[dict[str, Any]], base_asset: str, quote_asset: str
    ) -> tuple[Decimal | None, dict[str, Any]]:
        """Moving-average cost for the currently open Spot-traded quantity."""
        quantity = ZERO
        cost = ZERO
        buys = 0
        sells = 0
        history: list[dict[str, str]] = []
        for trade in sorted(trades, key=lambda row: int(row.get("time") or 0)):
            traded = _decimal(trade.get("qty"))
            quote = _decimal(trade.get("quoteQty"))
            commission = _decimal(trade.get("commission"))
            commission_asset = str(trade.get("commissionAsset") or "")
            if trade.get("isBuyer"):
                buys += 1
                if commission_asset == base_asset:
                    # The fee is charged in the received asset.  Convert it
                    # at the execution price so the average buy-in uses the
                    # same EUR cost as the persisted ledger.
                    if traded > ZERO:
                        quote += commission * quote / traded
                    traded -= commission
                # Historical normalization converts a fee paid in a third
                # asset into EUR.  It is an additional acquisition outflow
                # for a buy and must be part of the displayed average cost,
                # just like a fee paid directly in the quote currency.
                if commission_asset == quote_asset or commission_asset == "EUR":
                    quote += commission
                if traded > ZERO:
                    quantity += traded
                    cost += quote
            else:
                sells += 1
                if quantity <= ZERO:
                    continue
                # A sell-side fee paid in the base asset is an additional
                # quantity leaving the wallet. Include it in the moving
                # average release; otherwise the remaining position keeps a
                # small phantom cost that compounds across many executions.
                if commission_asset == base_asset:
                    traded += commission
                sold = min(traded, quantity)
                average = cost / quantity
                cost -= average * sold
                quantity -= sold

            timestamp = trade.get("time")
            if timestamp is not None:
                history.append(
                    {
                        "timestamp": str(timestamp),
                        "open_cost": str(max(cost, ZERO)),
                        "open_quantity": str(max(quantity, ZERO)),
                    }
                )

        average = cost / quantity if quantity > ZERO and cost > ZERO else None
        return average, {
            "method": "moving_average_spot_trades",
            "open_trade_quantity": str(quantity),
            "buy_count": buys,
            "sell_count": sells,
            "quote_asset": quote_asset,
            "history": history,
        }

    def _price_history(
        self,
        client: httpx.Client,
        *,
        asset: str,
        quote: str,
        history_range: str,
        tickers: dict[str, Decimal],
    ) -> list[RawAssetPricePoint]:
        now = datetime.now(timezone.utc)
        if history_range == "max":
            start = datetime(2017, 1, 1, tzinfo=timezone.utc)
            interval = "1d"
        else:
            start = now - timedelta(days=6)
            interval = "1h"

        symbol = f"{asset}{quote}"
        start_ms = int(start.timestamp() * 1000)
        end = int(now.timestamp() * 1000)
        rows = self._public_klines(client, symbol, interval, start_ms, end)
        conversion = self._quote_eur_series(client, quote, interval, start_ms, end)
        fallback_quote_eur = self._price_in_eur(quote, tickers)
        if quote not in EUR_EQUIVALENTS and not conversion and fallback_quote_eur is None:
            return []
        result: list[RawAssetPricePoint] = []
        conversion_index = 0
        latest_conversion: Decimal | None = (
            Decimal("1") if quote in EUR_EQUIVALENTS else None
        )
        for row in rows:
            row_time = int(row[0])
            while (
                conversion_index < len(conversion)
                and conversion[conversion_index][0] <= row_time
            ):
                latest_conversion = conversion[conversion_index][1]
                conversion_index += 1
            quote_eur = latest_conversion or fallback_quote_eur
            if quote_eur is None:
                continue
            result.append(
                RawAssetPricePoint(
                    external_id=asset,
                    exchange="BINANCE",
                    timestamp=datetime.fromtimestamp(row_time / 1000, tz=timezone.utc),
                    open=_decimal(row[1]) * quote_eur,
                    high=_decimal(row[2]) * quote_eur,
                    low=_decimal(row[3]) * quote_eur,
                    close=_decimal(row[4]) * quote_eur,
                    volume=_decimal(row[5]),
                    currency="EUR",
                )
            )
        return result

    def _public_klines(
        self,
        client: httpx.Client,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[list[Any]]:
        cursor = start_ms
        result: list[list[Any]] = []
        while cursor < end_ms:
            response = client.get(
                f"{self._base_url}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            if response.status_code >= 400:
                return []
            rows = response.json()
            if not rows:
                break
            result.extend(row for row in rows if isinstance(row, list))
            next_cursor = int(rows[-1][0]) + 1
            if next_cursor <= cursor or len(rows) < 1000:
                break
            cursor = next_cursor
        return result

    def _quote_eur_series(
        self,
        client: httpx.Client,
        quote: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[tuple[int, Decimal]]:
        if quote in EUR_EQUIVALENTS:
            return []
        for symbol, invert in ((f"{quote}EUR", False), (f"EUR{quote}", True)):
            rows = self._public_klines(client, symbol, interval, start_ms, end_ms)
            if not rows:
                continue
            result: list[tuple[int, Decimal]] = []
            for row in rows:
                close = _decimal(row[4])
                if close > ZERO:
                    result.append(
                        (int(row[0]), Decimal("1") / close if invert else close)
                    )
            return result
        return []
