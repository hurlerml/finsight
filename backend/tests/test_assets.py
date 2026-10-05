from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import app.api.assets as assets_api
from app.api.assets import (
    _aggregate_performance,
    _combine_value_series,
    _portfolio_history_result,
    _position_cost_value,
    _reconstruct_portfolio_performance,
    _trade_performance_ledger,
    _provider_relative_percent,
    _current_portfolio_point,
)
from app.models import AssetPricePoint, Portfolio
from app.models.enums import AccountSource
from app.schemas.assets import AssetHistoryPointRead
from app.services.secure_portfolios import AssetTradeData, PositionData


def _position(
    *,
    external_id: str,
    quantity: Decimal,
    average_buy_in: Decimal | None = None,
    market_value: Decimal | None = None,
    captured_at: datetime,
    name: str | None = None,
) -> PositionData:
    return PositionData(
        id=1,
        portfolio_id=1,
        external_id=external_id,
        isin=None,
        name=name or external_id,
        asset_type=None,
        quantity=quantity,
        average_buy_in=average_buy_in,
        current_price=None,
        market_value=market_value,
        currency="EUR",
        captured_at=captured_at,
        raw_payload=None,
        created_at=captured_at,
    )


def _trade(
    *,
    external_id: str,
    instrument_external_id: str,
    timestamp: datetime,
    side: str,
    quantity: Decimal,
    cash_amount: Decimal,
) -> AssetTradeData:
    return AssetTradeData(
        id=1,
        portfolio_id=1,
        external_id=external_id,
        instrument_external_id=instrument_external_id,
        timestamp=timestamp,
        side=side,
        quantity=quantity,
        cash_amount=cash_amount,
        fees=None,
        taxes=None,
        currency="EUR",
        raw_payload=None,
        created_at=timestamp,
    )


def test_combines_provider_histories_with_forward_fill() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    combined = _combine_value_series(
        [
            [
                AssetHistoryPointRead(
                    timestamp=start,
                    value=Decimal("100"),
                    invested_value=Decimal("80"),
                ),
                AssetHistoryPointRead(
                    timestamp=start + timedelta(days=2),
                    value=Decimal("120"),
                    invested_value=Decimal("90"),
                ),
            ],
            [
                AssetHistoryPointRead(
                    timestamp=start + timedelta(days=1),
                    value=Decimal("50"),
                    invested_value=Decimal("40"),
                ),
                AssetHistoryPointRead(
                    timestamp=start + timedelta(days=2),
                    value=Decimal("55"),
                    invested_value=Decimal("42"),
                ),
            ],
        ]
    )

    assert [point.value for point in combined] == [
        Decimal("100"),
        Decimal("150"),
        Decimal("175"),
    ]
    assert [point.invested_value for point in combined] == [
        Decimal("80"),
        Decimal("120"),
        Decimal("132"),
    ]


def test_aggregate_performance_adds_pnl_and_basis_not_percentages() -> None:
    aggregate = _aggregate_performance(
        [
            (Decimal("1000"), Decimal("10000")),
            (Decimal("200"), Decimal("2000")),
        ]
    )

    assert aggregate.absolute == Decimal("1200")
    assert aggregate.basis == Decimal("12000")
    assert aggregate.percent == Decimal("10")


def test_aggregate_performance_ignores_missing_basis_for_percentage() -> None:
    aggregate = _aggregate_performance(
        [(Decimal("1000"), Decimal("10000")), (Decimal("200"), None)]
    )

    assert aggregate.absolute == Decimal("1200")
    assert aggregate.basis == Decimal("10000")
    assert aggregate.percent == Decimal("12")


def test_sub_euro_dust_without_trades_is_performance_neutral() -> None:
    position = _position(
        external_id="DUST",
        name="Dust",
        quantity=Decimal("0.1"),
        market_value=Decimal("0.5"),
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert _position_cost_value(position, Decimal("4")) == Decimal("0.4")


def test_ledger_does_not_project_current_holding_before_purchase() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    position = _position(
        external_id="ETF",
        quantity=Decimal("2"),
        average_buy_in=Decimal("100"),
        market_value=Decimal("240"),
        captured_at=start + timedelta(days=3),
    )
    trade = _trade(
        external_id="buy-1",
        instrument_external_id="ETF",
        timestamp=start + timedelta(days=1),
        side="buy",
        quantity=Decimal("2"),
        cash_amount=Decimal("200"),
    )
    prices = [
        AssetPricePoint(
            source=AccountSource.TRADE_REPUBLIC,
            external_id="ETF",
            exchange="LSX",
            timestamp=start + timedelta(days=offset),
            close=price,
            currency="EUR",
        )
        for offset, price in enumerate((Decimal("90"), Decimal("100"), Decimal("110")))
    ]

    points, estimated = _reconstruct_portfolio_performance(
        [position], [trade], {"ETF": prices}
    )

    assert estimated is False
    assert [point.timestamp for point in points] == [
        start + timedelta(days=1),
        start + timedelta(days=2),
    ]
    assert [point.value - point.invested_value for point in points] == [
        Decimal("0"),
        Decimal("20"),
    ]


def test_sale_keeps_realized_profit_in_performance() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [
        _trade(
            external_id="buy",
            instrument_external_id="ETF",
            timestamp=start,
            side="buy",
            quantity=Decimal("2"),
            cash_amount=Decimal("200"),
        ),
        _trade(
            external_id="sell",
            instrument_external_id="ETF",
            timestamp=start + timedelta(days=1),
            side="sell",
            quantity=Decimal("2"),
            cash_amount=Decimal("240"),
        ),
    ]
    prices = [
        AssetPricePoint(
            source=AccountSource.TRADE_REPUBLIC,
            external_id="ETF",
            exchange="LSX",
            timestamp=start + timedelta(days=offset),
            close=Decimal("100") + Decimal(offset * 20),
            currency="EUR",
        )
        for offset in range(3)
    ]

    points, _ = _reconstruct_portfolio_performance([], trades, {"ETF": prices})

    assert points[-1].value - points[-1].invested_value == Decimal("40")


def test_distribution_on_held_position_is_income_not_zero_quantity_sale() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    position = _position(
        external_id="ETF",
        quantity=Decimal("2"),
        average_buy_in=Decimal("100"),
        market_value=Decimal("220"),
        captured_at=start + timedelta(days=2),
    )
    trades = [
        _trade(
            external_id="buy",
            instrument_external_id="ETF",
            timestamp=start,
            side="buy",
            quantity=Decimal("2"),
            cash_amount=Decimal("200"),
        ),
        _trade(
            external_id="distribution",
            instrument_external_id="ETF",
            timestamp=start + timedelta(days=1),
            side="income",
            quantity=Decimal("0"),
            cash_amount=Decimal("5"),
        ),
    ]
    prices = [
        AssetPricePoint(
            source=AccountSource.TRADE_REPUBLIC,
            external_id="ETF",
            exchange="LSX",
            timestamp=start + timedelta(days=offset),
            close=Decimal("100"),
            currency="EUR",
        )
        for offset in range(3)
    ]

    points, estimated = _reconstruct_portfolio_performance(
        [position], trades, {"ETF": prices}
    )

    assert estimated is False
    assert points[-1].value - points[-1].invested_value == Decimal("5")


def test_unexplained_outflow_marks_history_as_estimated() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trade = _trade(
        external_id="missing-inflow",
        instrument_external_id="BTC",
        timestamp=start,
        side="sell",
        quantity=Decimal("1"),
        cash_amount=Decimal("100"),
    )
    prices = [
        AssetPricePoint(
            source=AccountSource.BINANCE,
            external_id="BTC",
            exchange="BINANCE",
            timestamp=start,
            close=Decimal("100"),
            currency="EUR",
        )
    ]

    _points, estimated = _reconstruct_portfolio_performance(
        [], [trade], {"BTC": prices}
    )

    assert estimated is True


def test_missing_price_keeps_valued_part_of_portfolio_visible() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    positions = [
        _position(
            external_id="BTC",
            quantity=Decimal("1"),
            average_buy_in=Decimal("80"),
            market_value=Decimal("100"),
            captured_at=start,
        ),
        _position(
            external_id="NEW",
            quantity=Decimal("2"),
            average_buy_in=Decimal("5"),
            market_value=Decimal("10"),
            captured_at=start,
        ),
    ]
    prices = {
        "BTC": [
            AssetPricePoint(
                source=AccountSource.BINANCE,
                external_id="BTC",
                exchange="BINANCE",
                timestamp=start,
                close=Decimal("100"),
                currency="EUR",
            )
        ]
    }

    points, estimated = _reconstruct_portfolio_performance(positions, [], prices)

    assert estimated is True
    assert points[0].value == Decimal("100")


def test_trade_republic_always_uses_provider_absolute_values(monkeypatch) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    provider = [
        AssetHistoryPointRead(
            timestamp=start,
            value=Decimal("125"),
            invested_value=Decimal("0"),
        )
    ]
    portfolio = Portfolio(source=AccountSource.TRADE_REPUBLIC)
    provider_calls = []

    def provider_history(*args):
        provider_calls.append(args)
        return provider

    monkeypatch.setattr(assets_api, "_provider_performance_points", provider_history)

    def fail_if_reconstructed(*_args):
        raise AssertionError("Trade Republic must not use ledger reconstruction")

    monkeypatch.setattr(
        assets_api,
        "_calculated_portfolio_history_points",
        fail_if_reconstructed,
    )

    result = _portfolio_history_result(object(), portfolio, None, "1m")

    assert result.points == provider
    assert result.estimated is False
    assert result.source == "provider"
    assert len(provider_calls[0]) == 3


def test_ledger_and_current_position_share_missing_opening_cost() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    position = _position(
        external_id="BTC",
        quantity=Decimal("2"),
        average_buy_in=Decimal("100"),
        market_value=Decimal("240"),
        captured_at=start,
    )
    trades = [
        _trade(
            external_id="buy",
            instrument_external_id="BTC",
            timestamp=start,
            side="buy",
            quantity=Decimal("1"),
            cash_amount=Decimal("100"),
        )
    ]

    _realized, invested, open_costs = _trade_performance_ledger(trades, [position])

    assert invested["BTC"] == Decimal("100")
    # The second unit is an opening holding not represented by the execution
    # endpoint; it gets the same neutral average-buy-in cost as reconstruction.
    assert open_costs["BTC"] == Decimal("200")


def test_missing_inflow_does_not_create_phantom_opening_cost() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    position = _position(
        external_id="VET",
        quantity=Decimal("0.3545"),
        average_buy_in=Decimal("0.02"),
        market_value=Decimal("0.002"),
        captured_at=start,
    )
    trades = [
        _trade(
            external_id="sell-1",
            instrument_external_id="VET",
            timestamp=start,
            side="sell",
            quantity=Decimal("50000"),
            cash_amount=Decimal("1000"),
        )
    ]

    _realized, _invested, open_costs = _trade_performance_ledger(trades, [position])

    # The original inflow is missing, so only the observed remainder receives
    # the provider's average buy-in; 50,000 sold units must not be added back.
    assert open_costs["VET"] == Decimal("0.007090")



def test_provider_relative_value_is_normalized_to_percent() -> None:
    assert _provider_relative_percent("0.0528") == Decimal("5.2800")
    assert _provider_relative_percent("5.28") == Decimal("5.28")


def test_current_chart_point_matches_open_cost_pnl() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    position = _position(
        external_id="BTC",
        quantity=Decimal("2"),
        average_buy_in=Decimal("100"),
        market_value=Decimal("240"),
        captured_at=start,
    )
    trade = _trade(
        external_id="buy",
        instrument_external_id="BTC",
        timestamp=start,
        side="buy",
        quantity=Decimal("1"),
        cash_amount=Decimal("100"),
    )

    point = _current_portfolio_point(
        SimpleNamespace(last_synced_at=start), [position], [trade]
    )[0]

    assert point.value - point.invested_value == Decimal("40")


def test_current_position_reconciles_stale_ledger_quantity() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    position = _position(
        external_id="VET",
        quantity=Decimal("0.3545"),
        average_buy_in=Decimal("0.02"),
        market_value=Decimal("0.002"),
        captured_at=start,
    )
    # The stale ledger still contains a historical buy for a much larger
    # amount than the current provider balance.
    trade = _trade(
        external_id="old-buy",
        instrument_external_id="VET",
        timestamp=start,
        side="buy",
        quantity=Decimal("50000"),
        cash_amount=Decimal("1000"),
    )

    _realized, _invested, open_costs = _trade_performance_ledger(
        [trade], [position]
    )

    assert open_costs["VET"] == Decimal("0.007090")
