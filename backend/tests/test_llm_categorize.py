from datetime import date, datetime
from decimal import Decimal

from app.models.enums import AccountSource, AccountType, TransactionKind
from app.services.llm_categorize import (
    CategoryPrediction,
    _account_category_override,
    _merchant_search_query,
    _needs_web_research,
    _system_prompt,
    _user_message,
)
from app.services.secure_accounts import AccountData
from app.services.secure_labels import CategoryData
from app.services.secure_transactions import TransactionData


def _trade_republic_account() -> AccountData:
    now = datetime(2026, 1, 1)
    return AccountData(
        id=3,
        connection_id=None,
        source=AccountSource.TRADE_REPUBLIC,
        external_id="tr-cash-test",
        name="Trade Republic",
        currency="EUR",
        account_type=AccountType.BROKER_CASH,
        iban=None,
        is_active=True,
        current_balance=None,
        available_balance=None,
        balance_updated_at=None,
        created_at=now,
        updated_at=now,
    )


def _tx(raw_text: str, amount: str, event_type: str) -> TransactionData:
    now = datetime(2026, 1, 1)
    return TransactionData(
        id=1,
        account_id=3,
        external_id="event-id",
        booking_date=date(2026, 8, 20),
        amount=Decimal(amount),
        currency="EUR",
        raw_text=raw_text,
        counterparty=None,
        kind=TransactionKind.EXPENSE,
        category_id=None,
        categorized_by=None,
        raw_payload={"traderepublic": {"eventType": event_type}},
        created_at=now,
        updated_at=now,
    )


def test_user_message_contains_account_and_event_context() -> None:
    tx = _tx("Microsoft", "-100", "TRADING_SAVINGSPLAN_EXECUTED")

    message = _user_message(tx, _trade_republic_account())

    assert "account_source: trade_republic" in message
    assert "account_type: broker_cash" in message
    assert "event_type: TRADING_SAVINGSPLAN_EXECUTED" in message


def test_broker_event_overrides_merchant_name_category_guess() -> None:
    tx = _tx("Microsoft", "-100", "SSP_CORPORATE_ACTION_CASH")

    assert _account_category_override(_trade_republic_account(), tx) == "savings"


def test_card_transaction_is_left_to_merchant_categorization() -> None:
    tx = _tx("Restaurant", "-12.50", "CARD_TRANSACTION")

    assert _account_category_override(_trade_republic_account(), tx) is None


def test_category_prompt_distinguishes_goods_from_experiences() -> None:
    now = datetime(2026, 1, 1)
    prompt = _system_prompt(
        [
            CategoryData(
                id=1, name="Shopping", slug="shopping", color="#fff",
                is_system=True, created_at=now,
            ),
            CategoryData(
                id=2, name="Leisure & Culture", slug="leisure", color="#fff",
                is_system=True, created_at=now,
            ),
        ]
    )

    assert "Purchase of physical goods" in prompt
    assert "cinema, theatre, concerts" in prompt
    assert "guessing between 'shopping' and 'leisure'" in prompt


def test_category_prompt_respects_disabled_web_research() -> None:
    prompt = _system_prompt([], web_search_enabled=False)

    assert "Web research is disabled" in prompt
    assert "Use web search" not in prompt


def test_ambiguous_shopping_or_low_confidence_requires_web_research() -> None:
    shopping = CategoryPrediction(category_slug="shopping", confidence=0.92, reason="retailer")
    uncertain = CategoryPrediction(category_slug="dining", confidence=0.60, reason="unclear")

    assert _needs_web_research(shopping, {"messages": []})
    assert _needs_web_research(uncertain, {"messages": []})


def test_merchant_search_query_excludes_amounts_dates_and_identifiers() -> None:
    tx = _tx(
        "ACME MARKET 38,09 EUR 20.08.2026 IBAN DE17123456780000000001",
        "-38.09",
        "CARD_TRANSACTION",
    )

    query = _merchant_search_query(tx)

    assert query == "ACME MARKET"
    assert "38" not in query
    assert "2026" not in query
    assert "DE17123456780000000001" not in query


def test_prediction_allows_models_to_omit_optional_reason() -> None:
    prediction = CategoryPrediction.model_validate(
        {"category_slug": "savings", "confidence": 1.0}
    )

    assert prediction.reason == ""
