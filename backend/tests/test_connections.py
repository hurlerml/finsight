from app.models.enums import AccountSource
from app.adapters.bank_profiles import validate_provider
import pytest

from app.services.connections import normalize_identifiers, public_fields_from_secrets
from app.services.vault import VaultError

SYNTHETIC_IBAN = "DE17123456780000000001"


def test_generic_fints_normalizes_iban_and_preserves_selected_endpoint() -> None:
    secrets = normalize_identifiers(
        AccountSource.VOLKSBANK,
        "generic_fints",
        {
            "iban": "DE17 1234 5678 0000 0000 01",
            "user": "example-user",
            "pin": "secret",
            "endpoint": "https://bank.example/fints",
        },
    )

    assert secrets["iban"] == SYNTHETIC_IBAN
    assert secrets["blz"] == "12345678"
    assert secrets["endpoint"] == "https://bank.example/fints"


def test_generic_fints_keeps_endpoint_private_and_exposes_bank_identity() -> None:
    secrets = normalize_identifiers(
        AccountSource.VOLKSBANK,
        "generic_fints",
        {
            "iban": "DE17 1234 5678 0000 0000 01",
            "user": "bank-user",
            "pin": "secret",
            "endpoint": "https://bank.example/fints",
            "bank_name": "Example Bank",
            "bank_bic": "EXAMPLE1XXX",
            "bank_brand": "example-bank",
        },
    )

    assert secrets["endpoint"] == "https://bank.example/fints"
    assert public_fields_from_secrets(
        AccountSource.VOLKSBANK, "generic_fints", secrets
    ) == {
        "iban": SYNTHETIC_IBAN,
        "user": "bank-user",
        "bank_name": "Example Bank",
        "bank_bic": "EXAMPLE1XXX",
        "bank_brand": "example-bank",
    }


def test_generic_fints_rejects_bank_that_does_not_match_iban() -> None:
    with pytest.raises(VaultError, match="selected bank does not match"):
        normalize_identifiers(
            AccountSource.VOLKSBANK,
            "generic_fints",
            {
                "iban": "DE17 1234 5678 0000 0000 01",
                "blz": "87654321",
                "user": "bank-user",
                "pin": "secret",
                "endpoint": "https://bank.example/fints",
            },
        )


def test_provider_validation_keeps_adapter_and_bank_profile_separate() -> None:
    assert validate_provider(AccountSource.VOLKSBANK, None) == "generic_fints"
    assert validate_provider(AccountSource.VOLKSBANK, "generic_fints") == "generic_fints"
    assert validate_provider(AccountSource.VOLKSBANK, "volksbank") == "volksbank"


def test_binance_credentials_are_never_returned_as_public_fields() -> None:
    assert public_fields_from_secrets(
        AccountSource.BINANCE,
        "binance",
        {"api_key": "key", "api_secret": "secret"},
    ) == {}
    assert validate_provider(AccountSource.BINANCE, None) == "binance"


@pytest.mark.parametrize("source", [AccountSource.TRADING_212, AccountSource.COINBASE])
def test_new_broker_credentials_are_never_public(source: AccountSource) -> None:
    assert public_fields_from_secrets(
        source,
        source.value,
        {"api_key": "key", "api_secret": "secret"},
    ) == {}
    assert validate_provider(source, None) == source.value
