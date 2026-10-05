"""Read-only FinTS adapter backed by the internal HBCI4Java gateway."""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.base import BaseAdapter, RawAccount, RawBalance, RawTransaction
from app.config import get_settings
from app.models.enums import AccountSource, AccountType
from app.services.sync_progress import set_sync_progress
from app.services.transaction_titles import fints_card_transaction_title

logger = logging.getLogger(__name__)

DEFAULT_TAN_TIMEOUT_SECONDS = 60
JOB_POLL_INTERVAL_SECONDS = 1


class FintsAdapter(BaseAdapter):
    """Translate the HBCI4Java gateway contract into the shared adapter model."""

    source = AccountSource.VOLKSBANK

    def __init__(self, credentials: dict[str, Any] | None = None, label: str = "FinTS") -> None:
        self._creds = credentials or {}
        self._label = label
        self._balance_cache: dict[str, RawBalance] = {}

    def is_configured(self) -> bool:
        credentials = self._creds
        return bool(
            credentials.get("blz")
            and credentials.get("user")
            and credentials.get("pin")
            and credentials.get("endpoint")
        )

    def _product_id(self) -> str:
        configured = str(self._creds.get("product_id") or "").strip()
        if configured:
            return configured
        configured = get_settings().fints_product_id.strip()
        if configured:
            return configured
        raise RuntimeError(
            "FinTS product_id is not configured. Set FINTS_PRODUCT_ID in .env "
            "or register it in the connection configuration."
        )

    def _tan_timeout(self) -> int:
        value = self._creds.get("tan_timeout_seconds")
        try:
            if value not in (None, ""):
                return max(30, int(value))
        except (TypeError, ValueError):
            pass
        configured = get_settings().sync_user_action_timeout_seconds
        return max(30, configured)

    def _gateway_credentials(self) -> dict[str, Any]:
        credentials = self._creds
        payload: dict[str, Any] = {
            "blz": str(credentials["blz"]).strip(),
            "user": str(credentials["user"]).strip(),
            "pin": str(credentials["pin"]),
            "endpoint": str(credentials["endpoint"]).strip(),
            "productId": self._product_id(),
        }
        optional_fields = {
            "customerId": credentials.get("customer_id"),
            "tanMedium": credentials.get("tan_medium"),
            "tanMechanism": credentials.get("tan_mechanism"),
        }
        payload.update(
            {
                key: str(value).strip()
                for key, value in optional_fields.items()
                if value is not None and str(value).strip()
            }
        )
        return payload

    def _run_gateway(
        self,
        operation: str,
        *,
        account: RawAccount | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> dict[str, Any]:
        base_url = get_settings().fints_gateway_url.rstrip("/")
        request: dict[str, Any] = {
            "operation": operation,
            "credentials": self._gateway_credentials(),
        }
        if account is not None:
            request["account"] = {
                "externalId": account.external_id,
                "iban": account.iban,
            }
        if since is not None:
            request["since"] = since.isoformat()
        if until is not None:
            request["until"] = until.isoformat()

        timeout_at = time.monotonic() + self._tan_timeout() + 15
        job_url: str | None = None
        try:
            with httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
                response = client.post(f"{base_url}/v1/jobs", json=request)
                response.raise_for_status()
                job = response.json()
                job_id = job.get("id")
                if not job_id:
                    raise RuntimeError("FinTS gateway returned no job id")
                job_url = f"{base_url}/v1/jobs/{job_id}"

                while True:
                    response = client.get(job_url)
                    response.raise_for_status()
                    job = response.json()
                    status = job.get("status")
                    message = str(job.get("message") or "Synchronizing FinTS account…")

                    if status == "completed":
                        result = job.get("result")
                        return result if isinstance(result, dict) else {}
                    if status == "failed":
                        error = job.get("error") or {}
                        detail = str(error.get("detail") or message or "FinTS synchronization failed")
                        raise RuntimeError(detail)

                    awaiting = status == "awaiting_user_action"
                    set_sync_progress(
                        phase="awaiting_user_action" if awaiting else "running",
                        message=message,
                        awaiting_user_action=awaiting,
                        source=self.source.value,
                    )
                    if time.monotonic() >= timeout_at:
                        raise RuntimeError(
                            "Timed out waiting for the FinTS bank. Approve a pending request "
                            "in the banking app and synchronize again."
                        )
                    time.sleep(JOB_POLL_INTERVAL_SECONDS)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"FinTS gateway is unavailable: {exc}") from exc
        finally:
            if job_url is not None:
                try:
                    httpx.delete(job_url, timeout=3.0)
                except httpx.HTTPError:
                    logger.debug("Could not remove completed FinTS gateway job", exc_info=True)

    def _allowed_account_ids(self) -> set[str] | None:
        raw = str(self._creds.get("product_ids") or "").strip()
        if raw:
            return {self._normalize_account_id(value) for value in raw.split(",") if value.strip()}
        iban = self._normalize_account_id(self._creds.get("iban"))
        return {iban} if iban else None

    @staticmethod
    def _normalize_account_id(value: Any) -> str:
        return str(value or "").replace(" ", "").upper()

    def accepts_account(self, external_id: str, iban: str | None = None) -> bool:
        allowed = self._allowed_account_ids()
        if allowed is None:
            return True
        return bool(
            {self._normalize_account_id(external_id), self._normalize_account_id(iban)} & allowed
        )

    @staticmethod
    def _account_type(value: str | None) -> AccountType:
        return AccountType.CARD if str(value or "").lower() == "card" else AccountType.CHECKING

    def _map_accounts(self, values: list[dict[str, Any]]) -> list[RawAccount]:
        allowed = self._allowed_account_ids()
        accounts: list[RawAccount] = []
        for value in values:
            external_id = str(value.get("externalId") or value.get("iban") or "").strip()
            iban = str(value.get("iban") or "").strip() or None
            identifiers = {
                self._normalize_account_id(external_id),
                self._normalize_account_id(iban),
                self._normalize_account_id(value.get("accountNumber")),
            }
            if not external_id or (allowed is not None and not identifiers & allowed):
                continue
            account_type = self._account_type(value.get("accountType"))
            default_name = "Karte" if account_type == AccountType.CARD else "Girokonto"
            accounts.append(
                RawAccount(
                    external_id=external_id,
                    name=str(value.get("name") or default_name),
                    currency=str(value.get("currency") or "EUR"),
                    account_type=account_type,
                    iban=iban,
                )
            )
        return accounts

    def list_accounts(self) -> list[RawAccount]:
        if not self.is_configured():
            logger.warning("FinTS connection is incomplete")
            return []
        result = self._run_gateway("ACCOUNTS")
        values = result.get("accounts")
        return self._map_accounts(values if isinstance(values, list) else [])

    def fetch_transactions(
        self, account: RawAccount, since: date, until: date
    ) -> list[RawTransaction]:
        if not self.is_configured():
            return []
        result = self._run_gateway(
            "TRANSACTIONS", account=account, since=since, until=until
        )
        mapped_balance = self._map_balance(result.get("balance"), account.currency)
        if mapped_balance is not None:
            self._balance_cache[account.external_id] = mapped_balance

        transactions: list[RawTransaction] = []
        values = result.get("transactions")
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict) or value.get("amount") is None:
                continue
            booking = self._parse_date(value.get("bookingDate"), since)
            amount = Decimal(str(value["amount"]))
            counterparty = str(value.get("counterparty") or "").strip()
            booking_text = str(value.get("bookingText") or "").strip()
            purpose = str(value.get("purpose") or "").strip()
            applicant = counterparty or booking_text
            raw_text = " ".join(part for part in (applicant, purpose) if part).strip()
            if account.account_type == AccountType.CARD and not counterparty:
                counterparty = fints_card_transaction_title(raw_text) or applicant
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            external_id = str(value.get("externalId") or "").strip()
            if not external_id:
                code = str(metadata.get("transactionCode") or "").strip()
                external_id = f"{booking}|{amount}|{raw_text}|{code}"[:255]

            transactions.append(
                RawTransaction(
                    external_id=external_id,
                    booking_date=booking,
                    amount=amount,
                    currency=str(value.get("currency") or account.currency),
                    raw_text=raw_text,
                    counterparty=counterparty or None,
                    raw_payload={
                        "hbcijava": {
                            "metadata": metadata,
                            "value_date": value.get("valueDate"),
                            "booking_text": booking_text or None,
                            "pending": bool(value.get("pending")),
                        }
                    },
                )
            )
        logger.info("FinTS %s: %s transactions", account.external_id, len(transactions))
        return transactions

    def fetch_balance(self, account: RawAccount) -> RawBalance | None:
        if not self.is_configured():
            return None
        cached = self._balance_cache.pop(account.external_id, None)
        if cached is not None:
            return cached
        result = self._run_gateway("BALANCE", account=account)
        return self._map_balance(result.get("balance"), account.currency)

    @staticmethod
    def _parse_date(value: Any, fallback: date) -> date:
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _map_balance(value: Any, fallback_currency: str) -> RawBalance | None:
        if not isinstance(value, dict) or value.get("booked") is None:
            return None
        captured_at = (
            datetime.fromisoformat(str(value["capturedAt"]).replace("Z", "+00:00"))
            if value.get("capturedAt")
            else datetime.now(timezone.utc)
        )
        return RawBalance(
            booked=Decimal(str(value["booked"])),
            available=Decimal(str(value["available"])) if value.get("available") is not None else None,
            currency=str(value.get("currency") or fallback_currency),
            captured_at=captured_at,
            raw_payload={"source": "hbcijava"},
        )
