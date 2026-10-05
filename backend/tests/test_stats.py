from datetime import date, datetime
from decimal import Decimal

from app.api.stats import _is_savings_transaction
from app.models.enums import TransactionKind
from app.schemas.stats import FlowNode
from app.services.secure_transactions import TransactionData


def _transaction(kind: TransactionKind, category_id: int | None) -> TransactionData:
    now = datetime(2026, 1, 1)
    return TransactionData(
        id=1,
        account_id=1,
        external_id="test",
        booking_date=date(2026, 8, 23),
        amount=Decimal("-100"),
        currency="EUR",
        raw_text="",
        counterparty=None,
        kind=kind,
        category_id=category_id,
        categorized_by=None,
        raw_payload=None,
        created_at=now,
        updated_at=now,
    )


def test_savings_expense_is_classified_as_wealth_building() -> None:
    transaction = _transaction(TransactionKind.EXPENSE, 7)

    assert _is_savings_transaction(transaction, {7: "savings"}) is True


def test_regular_expense_and_income_are_not_savings() -> None:
    slugs = {7: "savings", 8: "shopping"}

    assert _is_savings_transaction(_transaction(TransactionKind.EXPENSE, 8), slugs) is False
    assert _is_savings_transaction(_transaction(TransactionKind.INCOME, 7), slugs) is False


def test_flow_node_exposes_category_metadata() -> None:
    node = FlowNode(name="Out · Shopping", role="expense", category_slug="shopping")

    assert node.role == "expense"
    assert node.category_slug == "shopping"
