from datetime import date, datetime, timezone
from decimal import Decimal
import asyncio

import httpx

from app.adapters.base import RawAssetPosition
from app.adapters.traderepublic import TradeRepublicAdapter


def test_maps_timeline_amount_without_rescaling_display_digits() -> None:
    adapter = TradeRepublicAdapter()
    item = {
        "id": "example-id",
        "timestamp": "2026-08-20T12:00:00.000Z",
        "title": "Card payment",
        "body": "Coffee",
        "cashChangeAmount": {
            "value": -425.25,
            "fractionDigits": 2,
            "currency": "EUR",
        },
    }

    transaction = adapter._map_item(item, date(2026, 1, 1), date(2026, 12, 31))

    assert transaction is not None
    assert transaction.amount == Decimal("-425.25")
    assert transaction.booking_date == date(2026, 8, 20)
    assert transaction.external_id == "example-id"


def test_maps_nested_timeline_data() -> None:
    adapter = TradeRepublicAdapter()
    item = {
        "data": {
            "id": "nested-id",
            "timestamp": 1787227200000,
            "title": "Transfer",
            "cashChangeAmount": {"value": 12, "fractionDigits": 2},
        }
    }

    transaction = adapter._map_item(item, date(2026, 1, 1), date(2026, 12, 31))

    assert transaction is not None
    assert transaction.amount == Decimal("12")
    assert transaction.external_id == "nested-id"


def test_maps_current_timezone_without_colon() -> None:
    adapter = TradeRepublicAdapter()
    item = {
        "id": "current-id",
        "timestamp": "2026-08-20T12:00:00.000+0000",
        "title": "Transfer",
        "amount": {"value": 1200, "fractionDigits": 2, "currency": "EUR"},
    }

    transaction = adapter._map_item(item, date(2026, 1, 1), date(2026, 12, 31))

    assert transaction is not None
    assert transaction.booking_date == date(2026, 8, 20)


def test_accepts_nested_timeline_page() -> None:
    items, cursors = TradeRepublicAdapter._timeline_page(
        {"data": {"items": [{"id": "one"}], "cursors": {"after": "next"}}}
    )

    assert items == [{"id": "one"}]
    assert cursors == {"after": "next"}


def test_login_405_is_reported_as_waf_block() -> None:
    response = httpx.Response(405, request=httpx.Request("POST", "https://example.test"))

    try:
        TradeRepublicAdapter._raise_login_error(response)
    except RuntimeError as exc:
        assert "AWS WAF" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_maps_cash_response_to_account_balance() -> None:
    balance = TradeRepublicAdapter._map_cash(
        [{"amount": "1234.56", "currencyId": "EUR"}]
    )

    assert balance is not None
    assert balance.booked == Decimal("1234.56")
    assert balance.available is None
    assert balance.currency == "EUR"


def test_cash_mapping_does_not_treat_portfolio_positions_as_balance() -> None:
    balance = TradeRepublicAdapter._map_cash(
        {"categories": [{"positions": [{"netSize": "12"}]}]}
    )

    assert balance is None


def test_portfolio_sync_keeps_positions_separate_from_cash(monkeypatch) -> None:
    adapter = TradeRepublicAdapter({"phone": "+49123", "pin": "1234"})
    position = RawAssetPosition(
        external_id="DE000ETF1234",
        isin="DE000ETF1234",
        name="Example ETF",
        asset_type="ETF",
        quantity=Decimal("2.5"),
        average_buy_in=Decimal("100"),
        current_price=Decimal("110"),
        market_value=Decimal("275"),
        currency="EUR",
    )

    async def positions(
        _cookies,
        _securities_account,
        history_range="5d",
        known_history_external_ids=None,
    ):
        return [position], []

    monkeypatch.setattr(adapter, "_authenticated_cookies", lambda: {"session": "ok"})
    monkeypatch.setattr(
        adapter,
        "_account_settings",
        lambda _cookies: {"securitiesAccountNumber": "SEC-1"},
    )
    monkeypatch.setattr(adapter, "_fetch_portfolio_positions", positions)
    monkeypatch.setattr(adapter, "_fetch_portfolio_value_history", lambda *_args: [])

    portfolios = adapter.fetch_portfolios()

    assert len(portfolios) == 1
    assert portfolios[0].external_id == "tr-depot-SEC-1"
    assert portfolios[0].positions == [position]


def test_maps_instrument_price_history() -> None:
    points = TradeRepublicAdapter._map_price_history(
        {
            "aggregates": [
                {
                    "time": 1787529600000,
                    "open": "100.10",
                    "high": "103.00",
                    "low": "99.50",
                    "close": "102.25",
                    "adjValue": "101.90",
                    "volume": 42,
                }
            ]
        },
        external_id="DE000ETF1234",
        exchange="TIB",
        currency="EUR",
    )

    assert len(points) == 1
    assert points[0].close == Decimal("102.25")
    assert points[0].adjusted == Decimal("101.90")
    assert points[0].timestamp == datetime(2026, 8, 24, tzinfo=timezone.utc)


def test_builds_current_lightweight_price_history_request() -> None:
    request = TradeRepublicAdapter._price_history_request(
        "DE000TEST123", "LSX", "max"
    )

    assert request == {
        "type": "aggregateHistoryLight",
        "id": "DE000TEST123.LSX",
        "range": "5y",
        "resolution": 86_400_000,
    }


def test_maps_structured_asset_execution_detail() -> None:
    trade = TradeRepublicAdapter._map_asset_trade(
        {
            "id": "execution-1",
            "timestamp": "2026-03-10T12:00:00Z",
            "eventType": "TRADING_SAVINGSPLAN_EXECUTED",
            "cashChangeAmount": {"value": -100, "currency": "EUR"},
        },
        {
            "sections": [
                {
                    "title": "Transaktion",
                    "data": [
                        {"title": "Aktienkurs", "detail": {"text": "46,0339 €"}},
                        {"title": "Anteile", "detail": {"text": "2,5000"}},
                        {"title": "Gebühren", "detail": {"text": "1,00 €"}},
                    ],
                },
                {"action": {"type": "instrumentDetail", "payload": "US5949181045"}},
            ]
        },
    )

    assert trade is not None
    assert trade.instrument_external_id == "US5949181045"
    assert trade.side == "buy"
    assert trade.quantity == Decimal("2.5000")
    assert trade.cash_amount == Decimal("100")
    assert trade.fees == Decimal("1.00")


def test_maps_asset_distribution_without_changing_quantity() -> None:
    trade = TradeRepublicAdapter._map_asset_trade(
        {
            "id": "dividend-1",
            "timestamp": "2026-04-10T12:00:00Z",
            "eventType": "SSP_CORPORATE_ACTION_CASH",
            "icon": "logos/US5949181045/v2",
            "amount": {"value": 12.5, "currency": "EUR"},
        },
        None,
    )

    assert trade is not None
    assert trade.instrument_external_id == "US5949181045"
    assert trade.side == "income"
    assert trade.quantity == 0
    assert trade.cash_amount == Decimal("12.5")


def test_rejects_uuid_suffix_as_isin() -> None:
    assert TradeRepublicAdapter._find_isin(
        {"id": "4a76a9fc-fc94-4b3d-b42c-1b0919be8523"}
    ) is None


def test_portfolio_history_excludes_cash_from_market_value() -> None:
    points = TradeRepublicAdapter._map_portfolio_history(
        {
            "points": [
                {
                    "timestamp": "2026-08-24T10:00:00Z",
                    "netValue": "12500.25",
                    "cashBalance": "800.50",
                    "totalValue": "13300.75",
                    "currency": "EUR",
                }
            ]
        },
        "EUR",
    )

    assert len(points) == 1
    assert points[0].market_value == Decimal("12500.25")
    assert points[0].cash_balance == Decimal("800.50")


def test_receive_answer_accepts_initial_answer_message() -> None:
    class WebSocket:
        async def recv(self):
            return '1 A {"categories": []}'

    payload = asyncio.run(
        TradeRepublicAdapter._receive_answer(WebSocket(), "1")
    )

    assert payload == {"categories": []}
