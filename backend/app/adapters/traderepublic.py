"""Read-only Trade Republic adapter.

This independent implementation talks to Trade Republic's undocumented web
protocol directly and does not import a Trade Republic client library at
runtime. Its protocol handling was informed by the MIT-licensed ``pytr``
project (https://github.com/pytr-org/pytr). See ``THIRD_PARTY_NOTICES.md`` and
``docs/licenses/pytr-MIT.txt`` for attribution and license terms.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

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
from app.adapters.trade_republic_waf import USER_AGENT, get_waf_token
from app.models.enums import AccountSource, AccountType
from app.services.sync_progress import set_sync_progress

logger = logging.getLogger(__name__)

TR_API = "https://api.traderepublic.com"
TR_ORIGIN = "https://app.traderepublic.com"
TR_WS = "wss://api.traderepublic.com"
LOGIN_PATH = "/api/v2/auth/web/login"
APP_VERSION = "2.2631.13"
APPROVAL_TIMEOUT_SECONDS = 120
PersistSecrets = Callable[[dict[str, Any]], None]


class TradeRepublicAdapter(BaseAdapter):
    source = AccountSource.TRADE_REPUBLIC

    def __init__(
        self,
        credentials: dict[str, Any] | None = None,
        label: str = "Trade Republic Cash",
        persist_secrets: PersistSecrets | None = None,
    ) -> None:
        self._creds = credentials or {}
        self._label = label
        self._persist_secrets = persist_secrets
        self._cached_balance_ready = False
        self._cached_balance: RawBalance | None = None
        self._cached_portfolios: list[RawPortfolio] | None = None
        self._cached_portfolio_error: Exception | None = None
        self._known_trade_external_ids: set[str] = set()
        self._known_history_external_ids: set[str] = set()
        self._has_asset_history = False
        self._has_complete_trade_history = False

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
        self._known_trade_external_ids = known_trade_external_ids
        self._known_history_external_ids = known_history_external_ids
        self._has_asset_history = has_history
        self._has_complete_trade_history = has_complete_trade_history

    def is_configured(self) -> bool:
        return bool(self._creds.get("phone") and self._creds.get("pin"))

    def list_accounts(self) -> list[RawAccount]:
        phone = str(self._creds.get("phone") or "cash")
        return [
            RawAccount(
                external_id=f"tr-cash-{phone[-4:]}",
                name=self._label,
                currency="EUR",
                account_type=AccountType.BROKER_CASH,
            )
        ]

    def fetch_transactions(
        self, account: RawAccount, since: date, until: date
    ) -> list[RawTransaction]:
        if not self.is_configured():
            return []
        cookies = self._authenticated_cookies()
        settings = self._account_settings(cookies)
        securities_account = str(settings.get("securitiesAccountNumber") or "").strip()
        if not securities_account:
            raise RuntimeError("Trade Republic returned no securities account number")
        items, cash_payload, positions, price_history, asset_trades, portfolio_error = asyncio.run(
            self._fetch_sync_bundle(cookies, since, securities_account)
        )
        self._cached_balance = self._map_cash(cash_payload, account.currency)
        self._cached_balance_ready = True
        self._cached_portfolio_error = portfolio_error
        if portfolio_error is None:
            value_history: list[RawPortfolioValuePoint] = []
            try:
                value_history = self._fetch_all_portfolio_value_histories(
                    cookies, securities_account, account.currency
                )
            except (httpx.HTTPError, RuntimeError, ValueError):
                logger.warning("Trade Republic portfolio history lookup failed", exc_info=True)
            self._cached_portfolios = [
                RawPortfolio(
                    external_id=f"tr-depot-{securities_account}",
                    name="Trade Republic Depot",
                    currency=account.currency,
                    positions=positions,
                    price_history=price_history,
                    value_history=value_history,
                    trades=asset_trades,
                    trades_complete=True,
                )
            ]
        results = [self._map_item(item, since, until) for item in items]
        mapped = [item for item in results if item is not None]
        if items and not mapped:
            missing_amount = sum(self._item_amount(item) is None for item in items)
            missing_date = sum(self._item_date(item) is None for item in items)
            outside_range = sum(
                booking is not None and (booking < since or booking > until)
                for booking in map(self._item_date, items)
            )
            logger.warning(
                "Trade Republic mapped no timeline items "
                "(raw=%s, missing_amount=%s, missing_date=%s, outside_range=%s)",
                len(items),
                missing_amount,
                missing_date,
                outside_range,
            )
        logger.info(
            "Trade Republic cash: %s transactions from %s timeline items",
            len(mapped),
            len(items),
        )
        return mapped

    def fetch_balance(self, account: RawAccount) -> RawBalance | None:
        if not self.is_configured():
            return None
        if self._cached_balance_ready:
            return self._cached_balance
        cookies = self._authenticated_cookies()
        payload = asyncio.run(self._fetch_cash(cookies))
        return self._map_cash(payload, account.currency)

    def fetch_portfolios(
        self,
        history_range: str = "5d",
        known_history_external_ids: set[str] | None = None,
    ) -> list[RawPortfolio]:
        if not self.is_configured():
            return []
        if self._cached_portfolio_error is not None:
            raise RuntimeError(str(self._cached_portfolio_error))
        if self._cached_portfolios is not None:
            return self._cached_portfolios
        cookies = self._authenticated_cookies()
        settings = self._account_settings(cookies)
        securities_account = str(settings.get("securitiesAccountNumber") or "").strip()
        if not securities_account:
            raise RuntimeError("Trade Republic returned no securities account number")
        positions, price_history = asyncio.run(
            self._fetch_portfolio_positions(
                cookies,
                securities_account,
                history_range=history_range,
                known_history_external_ids=known_history_external_ids,
            )
        )
        value_history = self._fetch_all_portfolio_value_histories(
            cookies, securities_account, "EUR"
        )
        return [
            RawPortfolio(
                external_id=f"tr-depot-{securities_account}",
                name="Trade Republic Depot",
                currency="EUR",
                positions=positions,
                price_history=price_history,
                value_history=value_history,
            )
        ]

    def _authenticated_cookies(self) -> dict[str, str]:
        stored = self._creds.get("session_cookies")
        cookies = (
            {str(key): str(value) for key, value in stored.items() if value}
            if isinstance(stored, dict)
            else {}
        )
        if cookies and self._session_is_valid(cookies):
            return cookies
        return self._login_v2()

    def _session_is_valid(self, cookies: dict[str, str]) -> bool:
        try:
            with httpx.Client(
                base_url=TR_API,
                headers=self._base_headers(),
                cookies=cookies,
                timeout=15,
            ) as client:
                response = client.get("/api/v2/auth/account")
                if response.status_code == 200:
                    self._persist_cookie_jar(client.cookies)
                    return True
                logger.info(
                    "Trade Republic stored session rejected (%s); starting login",
                    response.status_code,
                )
        except httpx.HTTPError as exc:
            logger.warning("Trade Republic session check failed: %s", type(exc).__name__)
        return False

    def _account_settings(self, cookies: dict[str, str]) -> dict[str, Any]:
        with httpx.Client(
            base_url=TR_API,
            headers=self._base_headers(),
            cookies=cookies,
            timeout=15,
        ) as client:
            response = client.get("/api/v2/auth/account")
            response.raise_for_status()
            self._persist_cookie_jar(client.cookies)
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Trade Republic returned invalid account metadata")
        return payload

    def _login_v2(self) -> dict[str, str]:
        device_id = str(self._creds.get("stable_device_id") or "")
        if not device_id:
            device_id = uuid.uuid4().hex + uuid.uuid4().hex
            self._persist({"stable_device_id": device_id})

        token = get_waf_token()
        with httpx.Client(
            base_url=TR_API,
            headers=self._login_headers(token, device_id),
            timeout=25,
        ) as client:
            client.cookies.set("aws-waf-token", token, domain=".traderepublic.com")
            response = self._initiate_login(client)
            if response.status_code == 405 and not response.content:
                token = get_waf_token(force_refresh=True)
                client.headers.update(self._login_headers(token, device_id))
                client.cookies.set("aws-waf-token", token, domain=".traderepublic.com")
                response = self._initiate_login(client)
            self._raise_login_error(response)
            process_id = response.json().get("processId")
            if not process_id:
                raise RuntimeError("Trade Republic login returned no process id")

            set_sync_progress(
                phase="awaiting_user_action",
                message="Approve the Trade Republic login in the app",
                awaiting_user_action=True,
                source="trade_republic",
            )
            logger.info("Trade Republic: waiting for app approval")
            deadline = time.monotonic() + APPROVAL_TIMEOUT_SECONDS
            poll_path = f"{LOGIN_PATH}/processes/{process_id}"
            while time.monotonic() < deadline:
                time.sleep(2)
                poll = client.get(poll_path)
                if poll.status_code in (401, 403, 404, 410):
                    raise RuntimeError(
                        "Trade Republic login approval expired; start the sync again"
                    )
                if poll.status_code != 200:
                    continue
                try:
                    payload = poll.json()
                except ValueError:
                    payload = {}
                state = str(payload.get("state") or payload.get("status") or "").upper()
                if state in {"REJECTED", "DECLINED", "FAILED", "EXPIRED"}:
                    raise RuntimeError(f"Trade Republic login was {state.lower()}")
                session_cookies = self._cookie_dict(client.cookies)
                approved = state in {"APPROVED", "COMPLETED", "SUCCESS", "OK", "DONE"}
                has_session = any(
                    session_cookies.get(name)
                    for name in ("tr_session", "tr_refresh")
                )
                if approved or has_session:
                    if not session_cookies:
                        raise RuntimeError(
                            "Trade Republic approved the login but returned no session cookies"
                        )
                    self._persist({"session_cookies": session_cookies})
                    set_sync_progress(
                        phase="running",
                        message="Connected to Trade Republic; loading transactions…",
                        awaiting_user_action=False,
                        source="trade_republic",
                    )
                    return session_cookies
            raise RuntimeError(
                "Trade Republic app approval timed out; start the sync again"
            )

    def _initiate_login(self, client: httpx.Client) -> httpx.Response:
        return client.post(
            LOGIN_PATH,
            json={"phoneNumber": self._creds["phone"], "pin": self._creds["pin"]},
        )

    @staticmethod
    def _base_headers() -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Origin": TR_ORIGIN,
            "Referer": f"{TR_ORIGIN}/",
        }

    def _login_headers(self, waf_token: str, device_id: str) -> dict[str, str]:
        headers = self._base_headers()
        device_info = {
            "stableDeviceId": device_id,
            "model": "Apple Macintosh",
            "browser": "Chrome",
            "browserVersion": "131.0.0.0",
            "os": "Mac OS",
            "osVersion": "10.15.7",
            "timezone": "Europe/Lisbon",
            "timezoneOffset": 0,
            "screen": "1440x900x24",
            "preferredLanguages": ["de", "en"],
            "numberOfCores": 8,
            "deviceMemory": 8,
        }
        encoded_device = base64.b64encode(
            json.dumps(device_info, separators=(",", ":")).encode()
        ).decode()
        headers.update(
            {
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "same-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "x-tr-platform": "web-pro",
                "x-tr-app-version": APP_VERSION,
                "x-tr-device-info": encoded_device,
                "x-aws-waf-token": waf_token,
            }
        )
        return headers

    @staticmethod
    def _raise_login_error(response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        try:
            body = response.json()
        except ValueError:
            body = None
        error_code = None
        if isinstance(body, dict) and isinstance(body.get("errors"), list) and body["errors"]:
            error_code = body["errors"][0].get("errorCode")
        if response.status_code == 429 or error_code == "TOO_MANY_REQUESTS":
            raise RuntimeError("Trade Republic login rate-limited; please try again later")
        if error_code in {"PIN_INVALID", "NUMBER_INVALID", "USER_NOT_FOUND"}:
            raise RuntimeError("Trade Republic rejected the phone number or PIN")
        if response.status_code == 405:
            raise RuntimeError(
                "Trade Republic blocked the login via AWS WAF; retry later"
            )
        if response.status_code == 426:
            raise RuntimeError("Trade Republic rejected the client version")
        raise RuntimeError(f"Trade Republic login failed (HTTP {response.status_code})")

    async def _fetch_timeline(
        self, cookies: dict[str, str], since: date
    ) -> list[dict[str, Any]]:
        async with self._websocket(cookies) as websocket:
            results, _ = await self._fetch_timeline_on_socket(websocket, since)
            return results

    async def _fetch_sync_bundle(
        self,
        cookies: dict[str, str],
        since: date,
        securities_account: str,
    ) -> tuple[
        list[dict[str, Any]],
        Any,
        list[RawAssetPosition],
        list[RawAssetPricePoint],
        list[RawAssetTrade],
        Exception | None,
    ]:
        """Fetch all WebSocket read models on the one authenticated socket."""
        async with self._websocket(cookies) as websocket:
            # Asset performance needs the complete execution ledger, not merely
            # the cash-sync overlap. The mapped cash transactions are still
            # filtered to ``since`` below.
            timeline, next_sub_id = await self._fetch_timeline_on_socket(
                websocket,
                since if self._has_complete_trade_history else date(1970, 1, 1),
            )
            asset_trades, next_sub_id = await self._fetch_asset_trades_on_socket(
                websocket, timeline, next_sub_id
            )
            cash_payload: Any = None
            try:
                cash_payload = await self._subscribe_once(
                    websocket, str(next_sub_id), {"type": "cash"}
                )
            except (RuntimeError, asyncio.TimeoutError):
                logger.warning("Trade Republic cash lookup failed", exc_info=True)
            next_sub_id += 1
            try:
                positions, history = await self._fetch_portfolio_positions_on_socket(
                    websocket,
                    securities_account,
                    history_range="5d" if self._has_asset_history else "max",
                    known_history_external_ids=self._known_history_external_ids,
                    first_sub_id=next_sub_id,
                    additional_history_external_ids={
                        trade.instrument_external_id for trade in asset_trades
                    },
                )
                portfolio_error = None
            except Exception as exc:
                logger.warning("Trade Republic portfolio lookup failed", exc_info=True)
                positions, history, portfolio_error = [], [], exc
            return timeline, cash_payload, positions, history, asset_trades, portfolio_error

    async def _fetch_asset_trades_on_socket(
        self, websocket: Any, timeline: list[dict[str, Any]], first_sub_id: int
    ) -> tuple[list[RawAssetTrade], int]:
        """Load structured details for executed orders and normalize a ledger."""
        result: list[RawAssetTrade] = []
        sub_index = first_sub_id
        candidates = [
            item
            for item in timeline
            if self._is_asset_trade_item(item)
            and str(item.get("id") or "") not in self._known_trade_external_ids
        ]
        for item in candidates:
            action = item.get("action") if isinstance(item.get("action"), dict) else {}
            event_id = str(action.get("payload") or item.get("id") or "").strip()
            if not event_id:
                continue
            sub_index += 1
            detail: Any = None
            try:
                detail = await self._subscribe_once(
                    websocket,
                    str(sub_index),
                    {"type": "timelineDetailV2", "id": event_id},
                )
            except (RuntimeError, asyncio.TimeoutError):
                logger.warning("Trade Republic trade detail failed for %s", event_id)
            trade = self._map_asset_trade(item, detail)
            if trade is not None:
                result.append(trade)
        logger.info(
            "Trade Republic mapped %s asset executions from %s candidates",
            len(result),
            len(candidates),
        )
        return result, sub_index + 1

    @staticmethod
    def _is_asset_trade_item(item: dict[str, Any]) -> bool:
        event_type = str(
            item.get("eventType") or item.get("type") or item.get("timelineEventType") or ""
        ).upper()
        return any(
            marker in event_type
            for marker in (
                "TRADING_TRADE_EXECUTED",
                "TRADING_SAVINGSPLAN_EXECUTED",
                "SSP_CORPORATE_ACTION_CASH",
            )
        )

    @classmethod
    def _map_asset_trade(
        cls, item: dict[str, Any], detail: Any
    ) -> RawAssetTrade | None:
        event_id = str(item.get("id") or "").strip()
        timestamp = cls._parse_timestamp(item.get("timestamp"))
        amount = cls._parse_amount(cls._item_amount(item))
        event_type = str(item.get("eventType") or "").upper()
        is_corporate_cash = "SSP_CORPORATE_ACTION_CASH" in event_type
        # Provider payloads contain localized field labels; preserve their exact spelling.
        quantity = cls._find_labeled_decimal(
            detail, {"aktien", "anteile", "shares", "quantity", "stück", "stueck"}
        )
        instrument_id = cls._find_isin(detail) or cls._find_isin(item)
        if not event_id or timestamp is None or amount is None:
            return None
        if not instrument_id or (not is_corporate_cash and (quantity is None or quantity <= 0)):
            return None
        currency = "EUR"
        amount_payload = item.get("cashChangeAmount") or item.get("amount")
        if isinstance(amount_payload, dict):
            currency = str(amount_payload.get("currency") or amount_payload.get("currencyId") or "EUR")
        fees = cls._find_labeled_decimal(detail, {"gebühr", "gebühren", "fee", "fees"})
        taxes = cls._find_labeled_decimal(
            detail, {"steuer", "steuern", "tax", "taxes"}
        )
        return RawAssetTrade(
            external_id=event_id,
            instrument_external_id=instrument_id,
            timestamp=timestamp,
            side=(
                "income" if amount >= 0 else "charge"
            ) if is_corporate_cash else ("buy" if amount < 0 else "sell"),
            quantity=quantity or Decimal("0"),
            cash_amount=abs(amount),
            fees=fees,
            taxes=taxes,
            currency=currency,
            raw_payload={"timeline": item, "detail": detail},
        )

    @classmethod
    def _find_isin(cls, payload: Any) -> str | None:
        for value in cls._walk_values(payload):
            match = re.search(r"(?<![A-Z0-9])[A-Z]{2}[A-Z0-9]{9}[0-9](?![A-Z0-9])", str(value).upper())
            if match and cls._valid_isin(match.group(0)):
                return match.group(0)
        return None

    @staticmethod
    def _valid_isin(value: str) -> bool:
        """Validate ISO 6166 identifiers and reject UUID fragments."""
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value):
            return False
        digits = "".join(
            str(ord(character) - 55) if character.isalpha() else character
            for character in value
        )
        total = 0
        for index, digit in enumerate(reversed(digits)):
            number = int(digit)
            if index % 2 == 1:
                number *= 2
            total += number // 10 + number % 10
        return total % 10 == 0

    @classmethod
    def _find_labeled_decimal(cls, payload: Any, labels: set[str]) -> Decimal | None:
        if isinstance(payload, dict):
            descriptors = [
                " ".join(str(payload.get(key) or "").lower().split())
                for key in ("title", "label", "name")
                if payload.get(key)
            ]
            # Exact labels (or prefixes such as "Anzahl Aktien") avoid reading
            # "Aktienkurs" as the number of shares.
            if any(
                descriptor == label or descriptor.endswith(f" {label}")
                for descriptor in descriptors
                for label in labels
            ):
                for key in ("value", "text", "detail", "amount"):
                    parsed = cls._decimal_from_display(payload.get(key))
                    if parsed is not None:
                        return abs(parsed)
            for value in payload.values():
                found = cls._find_labeled_decimal(value, labels)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = cls._find_labeled_decimal(value, labels)
                if found is not None:
                    return found
        return None

    @classmethod
    def _decimal_from_display(cls, value: Any) -> Decimal | None:
        direct = cls._decimal_or_none(value)
        if direct is not None:
            return direct
        if isinstance(value, dict):
            for nested in ("value", "text"):
                parsed = cls._decimal_from_display(value.get(nested))
                if parsed is not None:
                    return parsed
            return None
        if not isinstance(value, str):
            return None
        match = re.search(r"[-+]?\d[\d.\s]*(?:,\d+)?", value)
        if not match:
            return None
        normalized = match.group(0).replace(" ", "")
        if "," in normalized:
            normalized = normalized.replace(".", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None

    @classmethod
    def _walk_values(cls, payload: Any):
        if isinstance(payload, dict):
            for value in payload.values():
                yield value
                yield from cls._walk_values(value)
        elif isinstance(payload, list):
            for value in payload:
                yield value
                yield from cls._walk_values(value)

    async def _fetch_timeline_on_socket(
        self, websocket: Any, since: date
    ) -> tuple[list[dict[str, Any]], int]:
        results: list[dict[str, Any]] = []
        after: str | None = None
        next_sub_id = 1
        for page_number in range(1, 201):
            request: dict[str, Any] = {"type": "timelineTransactions"}
            if after:
                request["after"] = after
            sub_id = str(page_number)
            await websocket.send(f"sub {sub_id} {json.dumps(request)}")
            payload = await self._receive_answer(websocket, sub_id)
            await websocket.send(f"unsub {sub_id}")
            next_sub_id = page_number + 1
            items, cursors = self._timeline_page(payload)
            if page_number == 1:
                page_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
                item_keys = sorted(items[0].keys()) if items else []
                logger.info(
                    "Trade Republic timeline response "
                    "(type=%s, keys=%s, items=%s, item_keys=%s)",
                    type(payload).__name__,
                    page_keys,
                    len(items),
                    item_keys,
                )
            if not items:
                break
            results.extend(item for item in items if isinstance(item, dict))
            oldest = min(
                (item_date for item_date in map(self._item_date, items) if item_date),
                default=None,
            )
            next_after = cursors.get("after") if isinstance(cursors, dict) else None
            if oldest is not None and oldest < since:
                break
            if not next_after or next_after == after:
                break
            after = str(next_after)
        return results, next_sub_id

    async def _fetch_cash(self, cookies: dict[str, str]) -> Any:
        """Fetch only the broker cash account; portfolio positions live elsewhere."""
        async with self._websocket(cookies) as websocket:
            return await self._subscribe_once(websocket, "1", {"type": "cash"})

    async def _fetch_portfolio_positions(
        self,
        cookies: dict[str, str],
        securities_account: str,
        history_range: str = "5d",
        known_history_external_ids: set[str] | None = None,
    ) -> tuple[list[RawAssetPosition], list[RawAssetPricePoint]]:
        """Read current positions and enrich them with names and live prices."""
        async with self._websocket(cookies) as websocket:
            return await self._fetch_portfolio_positions_on_socket(
                websocket,
                securities_account,
                history_range=history_range,
                known_history_external_ids=known_history_external_ids,
                first_sub_id=1,
            )

    async def _fetch_portfolio_positions_on_socket(
        self,
        websocket: Any,
        securities_account: str,
        *,
        history_range: str,
        known_history_external_ids: set[str] | None,
        first_sub_id: int,
        additional_history_external_ids: set[str] | None = None,
    ) -> tuple[list[RawAssetPosition], list[RawAssetPricePoint]]:
        sub_index = first_sub_id
        compact = await self._subscribe_once(
            websocket,
            str(sub_index),
            {"type": "compactPortfolioByType", "secAccNo": securities_account},
        )
        if not isinstance(compact, dict) or not isinstance(compact.get("categories"), list):
            raise RuntimeError("Trade Republic returned an invalid portfolio snapshot")
        categories = compact["categories"]
        logger.info(
            "Trade Republic portfolio %s returned %s categories",
            securities_account,
            len(categories),
        )
        results: list[RawAssetPosition] = []
        history: list[RawAssetPricePoint] = []
        for category in categories:
            if not isinstance(category, dict):
                continue
            category_type = str(
                category.get("type")
                or category.get("name")
                or category.get("id")
                or "other"
            )
            raw_positions = category.get("positions")
            for position in raw_positions if isinstance(raw_positions, list) else []:
                if not isinstance(position, dict):
                    continue
                isin = str(position.get("isin") or position.get("instrumentId") or "").strip()
                quantity = self._decimal_or_none(position.get("netSize"))
                if not isin or quantity is None or quantity == 0:
                    continue

                instrument: dict[str, Any] = {}
                ticker: dict[str, Any] = {}
                sub_index += 1
                try:
                    response = await self._subscribe_once(
                        websocket, str(sub_index), {"type": "instrument", "id": isin}
                    )
                    if isinstance(response, dict):
                        instrument = response
                except (RuntimeError, asyncio.TimeoutError):
                    logger.warning("Trade Republic instrument lookup failed for %s", isin)

                exchange_candidates = self._exchange_candidates(instrument.get("exchangeIds"))
                exchange = exchange_candidates[0]
                sub_index += 1
                try:
                    response = await self._subscribe_once(
                        websocket,
                        str(sub_index),
                        {"type": "ticker", "id": f"{isin}.{exchange}"},
                    )
                    if isinstance(response, dict):
                        ticker = response
                except (RuntimeError, asyncio.TimeoutError):
                    logger.warning("Trade Republic ticker lookup failed for %s", isin)

                last = ticker.get("last") if isinstance(ticker.get("last"), dict) else {}
                price = self._decimal_or_none(last.get("price"))
                average_buy_in = self._decimal_or_none(position.get("averageBuyIn"))
                currency = str(
                    last.get("currencyId")
                    or ticker.get("currencyId")
                    or instrument.get("currencyId")
                    or "EUR"
                )
                results.append(
                    RawAssetPosition(
                        external_id=isin,
                        isin=isin,
                        name=str(instrument.get("shortName") or position.get("name") or isin),
                        asset_type=str(
                            instrument.get("type")
                            or instrument.get("instrumentType")
                            or category_type
                        ),
                        quantity=quantity,
                        average_buy_in=average_buy_in,
                        current_price=price,
                        market_value=price * quantity if price is not None else None,
                        currency=currency,
                        raw_payload={"category": category_type, "exchange": exchange},
                    )
                )

                instrument_history: list[RawAssetPricePoint] = []
                instrument_range = (
                    history_range
                    if isin in (known_history_external_ids or set())
                    else "max"
                )
                history_exchanges = exchange_candidates
                for history_exchange in history_exchanges:
                    sub_index += 1
                    try:
                        response = await self._subscribe_once(
                            websocket,
                            str(sub_index),
                            self._price_history_request(
                                isin,
                                history_exchange,
                                instrument_range,
                            ),
                        )
                        instrument_history = self._map_price_history(
                            response,
                            external_id=isin,
                            exchange=history_exchange,
                            currency=currency,
                        )
                    except (RuntimeError, asyncio.TimeoutError, ValueError):
                        logger.info(
                            "Trade Republic price history unavailable for %s on %s",
                            isin,
                            history_exchange,
                        )
                    if instrument_history:
                        break
                history.extend(instrument_history)
        # Sold positions no longer occur in compactPortfolioByType, but their
        # prices are necessary to calculate performance before the sale.
        current_ids = {position.external_id for position in results}
        for isin in sorted((additional_history_external_ids or set()) - current_ids):
            instrument: dict[str, Any] = {}
            sub_index += 1
            try:
                response = await self._subscribe_once(
                    websocket, str(sub_index), {"type": "instrument", "id": isin}
                )
                if isinstance(response, dict):
                    instrument = response
            except (RuntimeError, asyncio.TimeoutError):
                logger.warning("Trade Republic sold instrument lookup failed for %s", isin)
            for exchange in self._exchange_candidates(instrument.get("exchangeIds")):
                sub_index += 1
                try:
                    response = await self._subscribe_once(
                        websocket,
                        str(sub_index),
                        self._price_history_request(isin, exchange, "max"),
                    )
                    instrument_history = self._map_price_history(
                        response,
                        external_id=isin,
                        exchange=exchange,
                        currency=str(instrument.get("currencyId") or "EUR"),
                    )
                except (RuntimeError, asyncio.TimeoutError, ValueError):
                    instrument_history = []
                if instrument_history:
                    history.extend(instrument_history)
                    break
        logger.info(
            "Trade Republic portfolio %s mapped %s positions and %s price points",
            securities_account,
            len(results),
            len(history),
        )
        if results and not history:
            raise RuntimeError(
                "Trade Republic returned positions but no instrument price history"
            )
        return results, history

    @staticmethod
    def _price_history_request(
        isin: str, exchange: str, history_range: str
    ) -> dict[str, Any]:
        # The current web protocol exposes instrument candles through the
        # lightweight topic. Daily resolution keeps a five-year backfill small
        # while still being sufficient for the portfolio performance chart.
        return {
            "type": "aggregateHistoryLight",
            "id": f"{isin}.{exchange}",
            "range": "5y" if history_range == "max" else history_range,
            "resolution": 86_400_000,
        }

    def _fetch_portfolio_value_history(
        self,
        cookies: dict[str, str],
        securities_account: str,
        currency: str,
        history_range: str,
    ) -> list[RawPortfolioValuePoint]:
        headers = self._base_headers()
        headers.update({"x-tr-platform": "web-pro", "x-tr-app-version": APP_VERSION})
        waf_token = cookies.get("aws-waf-token")
        if waf_token:
            headers["x-aws-waf-token"] = waf_token
        with httpx.Client(
            base_url=TR_API,
            headers=headers,
            cookies=cookies,
            timeout=25,
        ) as client:
            response = client.get(
                "/api-gateway/portfolio-chart/v2/chart",
                params={
                    "secAccNo": securities_account,
                    "range": history_range,
                    "currency": currency,
                },
            )
            response.raise_for_status()
            self._persist_cookie_jar(client.cookies)
            payload = response.json()
        points = self._map_portfolio_history(payload, currency)
        for point in points:
            point.history_range = history_range
            point.raw_payload = {
                **point.raw_payload,
                "_history_range": history_range,
            }
        return points

    def _fetch_all_portfolio_value_histories(
        self,
        cookies: dict[str, str],
        securities_account: str,
        currency: str,
    ) -> list[RawPortfolioValuePoint]:
        try:
            return self._fetch_portfolio_value_history(
                cookies, securities_account, currency, "max"
            )
        except (httpx.HTTPError, RuntimeError, ValueError):
            logger.warning(
                "Trade Republic max portfolio history lookup failed",
                exc_info=True,
            )
            return []

    @staticmethod
    def _exchange_candidates(value: Any) -> list[str]:
        exchanges = [str(item) for item in value] if isinstance(value, list) else []
        ordered = [*exchanges, "LSX"]
        return list(dict.fromkeys(exchange for exchange in ordered if exchange))

    @classmethod
    def _map_price_history(
        cls,
        payload: Any,
        *,
        external_id: str,
        exchange: str,
        currency: str,
    ) -> list[RawAssetPricePoint]:
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        aggregates = payload.get("aggregates") if isinstance(payload, dict) else None
        if not isinstance(aggregates, list):
            return []
        result: list[RawAssetPricePoint] = []
        for aggregate in aggregates:
            if not isinstance(aggregate, dict):
                continue
            timestamp = cls._parse_timestamp(
                aggregate.get("time") or aggregate.get("timestamp")
            )
            close = cls._decimal_or_none(aggregate.get("close"))
            if timestamp is None or close is None:
                continue
            result.append(
                RawAssetPricePoint(
                    external_id=external_id,
                    exchange=exchange,
                    timestamp=timestamp,
                    open=cls._decimal_or_none(aggregate.get("open")),
                    high=cls._decimal_or_none(aggregate.get("high")),
                    low=cls._decimal_or_none(aggregate.get("low")),
                    close=close,
                    adjusted=cls._decimal_or_none(aggregate.get("adjValue")),
                    volume=cls._decimal_or_none(aggregate.get("volume")),
                    currency=currency,
                )
            )
        return result

    @classmethod
    def _map_portfolio_history(
        cls, payload: Any, fallback_currency: str
    ) -> list[RawPortfolioValuePoint]:
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        points = payload.get("points") if isinstance(payload, dict) else None
        if not isinstance(points, list):
            return []
        result: list[RawPortfolioValuePoint] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            timestamp = cls._parse_timestamp(
                point.get("time") or point.get("timestamp") or point.get("date")
            )
            market_value = cls._decimal_or_none(point.get("netValue"))
            if timestamp is None or market_value is None:
                continue
            result.append(
                RawPortfolioValuePoint(
                    timestamp=timestamp,
                    market_value=market_value,
                    cash_balance=cls._decimal_or_none(point.get("cashBalance")),
                    currency=str(point.get("currency") or fallback_currency),
                    raw_payload=point,
                )
            )
        return result

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                seconds = value / 1000 if value > 10_000_000_000 else value
                return datetime.fromtimestamp(seconds, tz=timezone.utc)
            normalized = str(value).strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except (ValueError, TypeError, OSError):
            return None

    @asynccontextmanager
    async def _websocket(self, cookies: dict[str, str]):
        """Open one authenticated, read-only protocol-31 WebSocket session."""
        import websockets

        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        additional_headers = {
            "Cookie": cookie_header,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Referer": f"{TR_ORIGIN}/",
            "x-tr-platform": "web",
        }
        waf_token = cookies.get("aws-waf-token")
        if waf_token:
            additional_headers["x-aws-waf-token"] = waf_token
        async with websockets.connect(
            TR_WS,
            additional_headers=additional_headers,
            user_agent_header=USER_AGENT,
            origin=TR_ORIGIN,
            max_size=2**24,
        ) as websocket:
            client_info = {
                "locale": "de",
                "platformId": "webtrading",
                "platformVersion": "chrome - 94.0.4606",
                "clientId": "app.traderepublic.com",
                "clientVersion": "5582",
            }
            await websocket.send(f"connect 31 {json.dumps(client_info)}")
            connected = await asyncio.wait_for(websocket.recv(), timeout=15)
            if connected != "connected":
                raise RuntimeError("Trade Republic WebSocket rejected the saved session")
            yield websocket

    async def _subscribe_once(
        self, websocket: Any, sub_id: str, request: dict[str, Any]
    ) -> Any:
        await websocket.send(f"sub {sub_id} {json.dumps(request)}")
        try:
            return await self._receive_answer(websocket, sub_id)
        finally:
            await websocket.send(f"unsub {sub_id}")

    @staticmethod
    def _decimal_or_none(value: Any) -> Decimal | None:
        try:
            return Decimal(str(value)) if value is not None else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    @classmethod
    def _map_cash(cls, payload: Any, fallback_currency: str = "EUR") -> RawBalance | None:
        # Current web responses are a list such as
        # [{"amount": "123.45", "currencyId": "EUR"}]. Accept a few older
        # wrappers as well, but never infer cash from portfolio positions.
        value = payload
        if isinstance(value, dict) and "data" in value:
            value = value["data"]
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, dict):
            return None
        amount_value: Any = value.get("amount")
        if amount_value is None:
            amount_value = value.get("cash") or value.get("value")
        amount = cls._parse_amount(amount_value)
        if amount is None:
            return None
        currency = (
            value.get("currencyId")
            or value.get("currency")
            or (
                amount_value.get("currency")
                if isinstance(amount_value, dict)
                else None
            )
            or fallback_currency
        )
        return RawBalance(
            booked=amount,
            currency=str(currency),
            raw_payload={"traderepublic_cash": value},
        )

    @staticmethod
    def _timeline_page(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Accept both the current page and older nested response shapes."""
        page = payload
        if isinstance(page, dict) and isinstance(page.get("data"), dict):
            nested = page["data"]
            if "items" in nested:
                page = nested
        if isinstance(page, list):
            return [item for item in page if isinstance(item, dict)], {}
        if not isinstance(page, dict):
            return [], {}
        raw_items = page.get("items") or page.get("transactions") or []
        items = (
            [item for item in raw_items if isinstance(item, dict)]
            if isinstance(raw_items, list)
            else []
        )
        cursors = page.get("cursors")
        return items, cursors if isinstance(cursors, dict) else {}

    @staticmethod
    async def _receive_answer(websocket: Any, sub_id: str) -> Any:
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=25)
            if not isinstance(raw, str):
                raw = raw.decode("utf-8", errors="replace")
            parts = raw.split(" ", 2)
            if len(parts) < 2 or parts[0] != sub_id:
                continue
            code = parts[1]
            body = parts[2] if len(parts) > 2 else ""
            if code == "A":
                return json.loads(body) if body else {}
            if code == "D":
                raise RuntimeError(
                    "Trade Republic sent a delta without an initial snapshot"
                )
            if code == "E":
                raise RuntimeError("Trade Republic rejected the read request")
            if code == "C":
                return {}

    def _map_item(
        self, item: dict[str, Any], since: date, until: date
    ) -> RawTransaction | None:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        amount_value = self._item_amount(item)
        amount = self._parse_amount(amount_value)
        booking = self._item_date(item)
        if amount is None or booking is None or booking < since or booking > until:
            return None
        title = item.get("title") or data.get("title") or "TR Event"
        body = item.get("body") or data.get("body") or ""
        ext = str(item.get("id") or data.get("id") or "")
        if not ext:
            ext = "tr-" + hashlib.sha1(
                f"{booking}:{amount}:{title}:{body}".encode()
            ).hexdigest()[:24]
        currency = (
            str(amount_value.get("currency"))
            if isinstance(amount_value, dict) and amount_value.get("currency")
            else "EUR"
        )
        return RawTransaction(
            external_id=ext[:255],
            booking_date=booking,
            amount=amount,
            currency=currency,
            raw_text=f"{title} {body}".strip(),
            counterparty=str(title),
            raw_payload={"traderepublic": item},
        )

    @staticmethod
    def _item_amount(item: dict[str, Any]) -> Any:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        for candidate in (
            item.get("cashChangeAmount"),
            item.get("amount"),
            data.get("cashChangeAmount"),
            data.get("amount"),
        ):
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _parse_amount(value: Any) -> Decimal | None:
        if isinstance(value, dict):
            raw = value.get("value")
            if raw is None:
                return None
            try:
                # Trade Republic already sends the value in the major currency
                # unit. fractionDigits is display metadata, not a cents scale.
                return Decimal(str(raw))
            except InvalidOperation:
                return None
        try:
            return Decimal(str(value)) if value is not None else None
        except InvalidOperation:
            return None

    @staticmethod
    def _item_date(item: dict[str, Any]) -> date | None:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        value = item.get("timestamp") or item.get("date") or data.get("timestamp")
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                seconds = value / 1000 if value > 1e12 else value
                return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
            normalized = str(value).strip().replace("Z", "+00:00")
            if len(normalized) >= 5 and normalized[-5] in "+-" and normalized[-3] != ":":
                normalized = f"{normalized[:-2]}:{normalized[-2:]}"
            return datetime.fromisoformat(normalized).date()
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _cookie_dict(cookies: httpx.Cookies) -> dict[str, str]:
        return {
            str(cookie.name): str(cookie.value)
            for cookie in cookies.jar
            if cookie.value and str(cookie.domain).endswith("traderepublic.com")
        }

    def _persist_cookie_jar(self, cookies: httpx.Cookies) -> None:
        values = self._cookie_dict(cookies)
        if values:
            self._persist({"session_cookies": values})

    def _persist(self, updates: dict[str, Any]) -> None:
        self._creds.update(updates)
        if self._persist_secrets is not None:
            self._persist_secrets(updates)
