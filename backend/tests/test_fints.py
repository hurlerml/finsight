from datetime import date
from decimal import Decimal

from app.adapters.base import RawAccount, RawBalance
from app.adapters.fints import FintsAdapter
from app.models.enums import AccountType
from app.services.transaction_titles import fints_card_transaction_title


def test_credit_card_title_parses_currency_before_amount() -> None:
    assert fints_card_transaction_title("Example Market EUR 12,34") == "Example Market"


def test_credit_card_title_parses_amount_before_currency() -> None:
    assert fints_card_transaction_title("Example Hotel 1.234,56 EUR") == "Example Hotel"


def test_credit_card_title_returns_none_without_amount_marker() -> None:
    assert fints_card_transaction_title("Card payment without merchant text") is None


def test_configured_iban_limits_discovered_accounts() -> None:
    adapter = FintsAdapter({"iban": "DE12 3456 7890"})

    assert adapter._allowed_account_ids() == {"DE1234567890"}
    assert adapter.accepts_account("DE1234567890")
    assert not adapter.accepts_account("DE9999999999")


def test_explicit_product_ids_override_iban_filter() -> None:
    adapter = FintsAdapter(
        {"iban": "DE1234567890", "product_ids": " 12345, DE98 7654 "}
    )

    assert adapter._allowed_account_ids() == {"12345", "DE987654"}


def test_account_mapping_keeps_only_configured_iban() -> None:
    adapter = FintsAdapter({"iban": "DE123"})
    accounts = adapter._map_accounts(
        [
            {
                "externalId": "DE123",
                "iban": "DE123",
                "accountNumber": "123",
                "name": "Girokonto",
                "currency": "EUR",
                "accountType": "checking",
            },
            {
                "externalId": "DE456",
                "iban": "DE456",
                "accountNumber": "456",
                "name": "Girokonto",
                "currency": "EUR",
                "accountType": "checking",
            },
        ]
    )

    assert [account.external_id for account in accounts] == ["DE123"]


def test_credit_card_connection_label_classifies_unnamed_account() -> None:
    adapter = FintsAdapter({}, label="Example Bank Kreditkarte")
    accounts = adapter._map_accounts(
        [
            {
                "externalId": "DE123",
                "iban": "DE123",
                "accountNumber": "123",
                "currency": "EUR",
                "accountType": "card",
            }
        ]
    )

    assert accounts[0].account_type == AccountType.CARD
    assert accounts[0].name == "Karte"


def test_balance_uses_bank_reported_amount(monkeypatch) -> None:
    adapter = FintsAdapter(
        {"blz": "12345678", "user": "user", "pin": "pin", "endpoint": "https://bank"}
    )
    monkeypatch.setattr(
        adapter,
        "_run_gateway",
        lambda *_args, **_kwargs: {
            "balance": {
                "booked": "987.65",
                "available": "900.00",
                "currency": "EUR",
                "capturedAt": "2026-10-04T10:00:00Z",
            }
        },
    )

    result = adapter.fetch_balance(
        RawAccount(
            external_id="DE123",
            name="Girokonto",
            currency="EUR",
            account_type=AccountType.CHECKING,
            iban="DE123",
        )
    )

    assert result is not None
    assert result.booked == Decimal("987.65")
    assert result.available == Decimal("900.00")
    assert result.currency == "EUR"


def test_balance_reuses_value_loaded_in_transaction_dialog(monkeypatch) -> None:
    adapter = FintsAdapter(
        {"blz": "12345678", "user": "user", "pin": "pin", "endpoint": "https://bank"}
    )
    account = RawAccount(
        external_id="DE123",
        name="Girokonto",
        currency="EUR",
        account_type=AccountType.CHECKING,
        iban="DE123",
    )
    adapter._balance_cache[account.external_id] = RawBalance(
        booked=Decimal("42.50"), currency="EUR"
    )
    monkeypatch.setattr(
        adapter,
        "_run_gateway",
        lambda: (_ for _ in ()).throw(AssertionError("must not open another dialog")),
    )

    result = adapter.fetch_balance(account)

    assert result is not None
    assert result.booked == Decimal("42.50")


def test_transaction_mapping_preserves_gateway_reference_and_balance(monkeypatch) -> None:
    adapter = FintsAdapter(
        {"blz": "12345678", "user": "user", "pin": "pin", "endpoint": "https://bank"}
    )
    monkeypatch.setattr(
        adapter,
        "_run_gateway",
        lambda *_args, **_kwargs: {
            "transactions": [
                {
                    "externalId": "BANK-REFERENCE-1",
                    "bookingDate": "2026-09-01",
                    "valueDate": "2026-09-01",
                    "amount": "-12.34",
                    "currency": "EUR",
                    "counterparty": "Example Store",
                    "purpose": "Purchase",
                    "bookingText": "Card payment",
                    "pending": False,
                    "metadata": {"transactionCode": "NMSC"},
                }
            ],
            "balance": {"booked": "100.00", "currency": "EUR"},
        },
    )
    account = RawAccount(
        external_id="DE123",
        name="Girokonto",
        currency="EUR",
        account_type=AccountType.CHECKING,
        iban="DE123",
    )

    transactions = adapter.fetch_transactions(
        account, date.fromisoformat("2026-09-01"), date.fromisoformat("2026-09-30")
    )

    assert len(transactions) == 1
    assert transactions[0].external_id == "BANK-REFERENCE-1"
    assert transactions[0].raw_text == "Example Store Purchase"
    assert adapter.fetch_balance(account).booked == Decimal("100.00")
