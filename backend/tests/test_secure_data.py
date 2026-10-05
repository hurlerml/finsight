from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from app.models import Account, AssetPositionSnapshot, Transaction
from app.models.enums import AccountSource
from app.services import crypto
from app.services.secure_data import (
    decrypt_payload,
    encrypt_payload,
    transaction_month_index,
)
from app.services.secure_repository import (
    decrypted_financial_payload,
    decrypted_transaction_payload,
    sealed_account_values,
    sealed_position_values,
    sealed_transaction_values,
)
from cryptography.exceptions import InvalidTag


def test_payload_round_trip_is_bound_to_domain_and_record() -> None:
    dek = crypto.new_dek()
    blob = encrypt_payload(
        dek,
        domain="transaction",
        record_id=42,
        payload={"amount": Decimal("12.34"), "date": date(2026, 8, 28)},
    )

    assert b"12.34" not in blob
    assert decrypt_payload(dek, domain="transaction", record_id=42, blob=blob) == {
        "amount": "12.34",
        "date": "2026-08-28",
    }
    with pytest.raises(InvalidTag):
        decrypt_payload(dek, domain="transaction", record_id=43, blob=blob)


def test_tampered_payload_is_rejected() -> None:
    dek = crypto.new_dek()
    blob = bytearray(
        encrypt_payload(dek, domain="agent-message", record_id=1, payload={"content": "private"})
    )
    blob[-1] ^= 1

    with pytest.raises(InvalidTag):
        decrypt_payload(dek, domain="agent-message", record_id=1, blob=bytes(blob))


def test_transaction_seal_contains_blind_indexes_and_full_payload() -> None:
    dek = crypto.new_dek()
    booking_date = date(2026, 8, 28)
    transaction = Transaction(
        id=7,
        account_id=3,
    )

    sealed = sealed_transaction_values(
        dek=dek,
        record_id=transaction.id,
        account_id=transaction.account_id,
        payload={
            "external_id": "bank-secret-id",
            "booking_date": booking_date,
            "amount": Decimal("-49.95"),
            "raw_text": "Sensitive purchase",
        },
    )
    transaction.encrypted_payload = sealed["encrypted_payload"]
    payload = decrypted_transaction_payload(transaction, dek)

    assert payload["amount"] == "-49.95"
    assert payload["raw_text"] == "Sensitive purchase"
    assert sealed["booking_month_blind"] == transaction_month_index(
        dek, transaction.account_id, booking_date
    )
    assert sealed["booking_month_blind"] != transaction_month_index(
        crypto.new_dek(), transaction.account_id, booking_date
    )


def test_account_and_position_financial_payloads_are_encrypted() -> None:
    dek = crypto.new_dek()
    account = Account(
        id=11,
        source=AccountSource.VOLKSBANK,
    )
    account_values = sealed_account_values(
        dek=dek,
        record_id=account.id,
        source=account.source.value,
        payload={
            "external_id": "private-account-id",
            "name": "Main account",
            "iban": "DE00123456780000000000",
            "current_balance": Decimal("4200.50"),
        },
    )
    account.encrypted_payload = account_values["encrypted_payload"]

    assert b"DE00123456780000000000" not in account.encrypted_payload
    assert decrypted_financial_payload(account, dek)["current_balance"] == "4200.50"
    assert account_values["external_id_blind"]

    position = AssetPositionSnapshot(
        id=12,
        portfolio_id=2,
    )
    position_values = sealed_position_values(
        dek=dek,
        record_id=position.id,
        payload={
            "external_id": "instrument-id",
            "name": "Private holding",
            "quantity": Decimal("1.25"),
            "average_buy_in": Decimal("123.45"),
            "captured_at": datetime(2026, 8, 28, tzinfo=timezone.utc),
        },
    )
    position.encrypted_payload = position_values["encrypted_payload"]

    assert b"Private holding" not in position.encrypted_payload
    assert decrypted_financial_payload(position, dek)["average_buy_in"] == "123.45"
