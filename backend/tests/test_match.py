from datetime import date, datetime
from decimal import Decimal

from app.models.enums import AccountSource, AccountType, TransactionKind
from app.services.match import _high_confidence_rule_prediction, _make_candidate
from app.services.secure_accounts import AccountData
from app.services.secure_transactions import TransactionData


def _account(account_id: int, name: str, iban: str | None = None) -> AccountData:
    now = datetime(2026, 1, 1)
    return AccountData(
        id=account_id,
        connection_id=None,
        source=AccountSource.VOLKSBANK,
        external_id=str(account_id),
        name=name,
        currency="EUR",
        account_type=AccountType.CHECKING,
        iban=iban,
        is_active=True,
        current_balance=None,
        available_balance=None,
        balance_updated_at=None,
        created_at=now,
        updated_at=now,
    )


def _transaction(
    transaction_id: int,
    account_id: int,
    amount: str,
    booking_date: date,
    raw_text: str = "",
) -> TransactionData:
    now = datetime(2026, 1, 1)
    value = Decimal(amount)
    kind = (
        TransactionKind.INCOME
        if value > 0
        else TransactionKind.EXPENSE
        if value < 0
        else TransactionKind.IGNORE
    )
    return TransactionData(
        id=transaction_id,
        account_id=account_id,
        external_id=str(transaction_id),
        booking_date=booking_date,
        amount=value,
        currency="EUR",
        raw_text=raw_text,
        counterparty=None,
        kind=kind,
        category_id=None,
        categorized_by=None,
        raw_payload=None,
        created_at=now,
        updated_at=now,
    )


def test_generates_candidate_for_same_amount_across_accounts() -> None:
    first_account = _account(1, "Main account")
    second_account = _account(2, "Savings account")
    first = _transaction(1, 1, "-150", date(2026, 4, 1), "Card payment Adidas")
    second = _transaction(2, 2, "-150", date(2026, 4, 2), "Index fund")

    candidate = _make_candidate(first, second, first_account, second_account)

    assert candidate is not None
    assert "same_amount" in candidate.evidence
    assert _high_confidence_rule_prediction(candidate) is None


def test_rejects_candidate_outside_date_window() -> None:
    first_account = _account(1, "Main account")
    second_account = _account(2, "Savings account")
    first = _transaction(1, 1, "-150", date(2026, 4, 1))
    second = _transaction(2, 2, "150", date(2026, 4, 8))

    assert _make_candidate(first, second, first_account, second_account) is None


def test_rule_confirms_explicit_transfer_to_owned_iban() -> None:
    first_account = _account(1, "Main account", "DE00111111111111111111")
    second_account = _account(2, "Savings account", "DE00222222222222222222")
    first = _transaction(
        1,
        1,
        "-5000",
        date(2026, 4, 22),
        "Transfer to DE00222222222222222222",
    )
    second = _transaction(2, 2, "5000", date(2026, 4, 22))

    candidate = _make_candidate(first, second, first_account, second_account)
    prediction = _high_confidence_rule_prediction(candidate) if candidate else None

    assert prediction is not None
    assert prediction.relationship == "internal_transfer"
    assert prediction.confidence == 0.99


def test_equal_amount_without_account_reference_is_never_auto_confirmed() -> None:
    first_account = _account(1, "Main account")
    second_account = _account(2, "Savings account")
    first = _transaction(1, 1, "-200", date(2026, 4, 1))
    second = _transaction(2, 2, "200", date(2026, 4, 1))

    candidate = _make_candidate(first, second, first_account, second_account)
    assert candidate is not None
    assert _high_confidence_rule_prediction(candidate) is None
