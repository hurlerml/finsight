from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from app.db import get_session
from app.deps import require_unlocked
from app.models import (
    AssetPositionSnapshot,
    AssetPricePoint,
    AssetTrade,
    Portfolio,
    PortfolioValuePoint,
)
from app.models.enums import AccountSource
from app.schemas.assets import (
    AssetHistoryCalibrationRead,
    AssetHistoryPointRead,
    AssetHistoryRead,
    AssetPositionRead,
    AssetsOverviewRead,
    PortfolioRead,
)
from app.services.secure_portfolios import (
    AssetTradeData,
    PortfolioData,
    PositionData,
    decode_portfolio,
    decode_portfolio_value,
    decode_position,
    decode_trade,
)

router = APIRouter(prefix="/api/assets", tags=["assets"])
RANGE_DAYS = {"1d": 1, "5d": 5, "1m": 31, "1y": 366}
IMMATERIAL_POSITION_EUR = Decimal("1")


@dataclass(frozen=True)
class _LedgerSummary:
    """Canonical moving-average ledger shared by table and current chart point."""

    realized: dict[str, Decimal]
    invested: dict[str, Decimal]
    open_costs: dict[str, Decimal]
    quantities: dict[str, Decimal]
    mismatched_instruments: frozenset[str]


@dataclass(frozen=True)
class _PerformanceAggregate:
    """Provider-independent aggregate of absolute P/L and its basis."""

    absolute: Decimal
    basis: Decimal
    percent: Decimal | None


def _aggregate_performance(
    components: list[tuple[Decimal, Decimal | None]],
) -> _PerformanceAggregate:
    """Add absolute P/L and capital bases, then derive one percentage.

    Percentages must never be added directly: a 10% result on 10,000 EUR and
    a 10% result on 1,000 EUR are still only a 10% aggregate result, not 20%.
    """

    absolute = sum((pnl for pnl, _ in components), Decimal("0"))
    basis = sum(
        (value for _, value in components if value is not None and value > 0),
        Decimal("0"),
    )
    percent = absolute / basis * Decimal("100") if basis > 0 else None
    return _PerformanceAggregate(absolute=absolute, basis=basis, percent=percent)


def _build_trade_ledger(
    trades: list[AssetTradeData],
    positions: list[PositionData] | None = None,
) -> _LedgerSummary:
    """Return realized P/L and cumulative invested cash per instrument.

    A moving-average cost basis keeps realized gains when units are sold while
    deposits/withdrawals (which are not trades) never enter the performance
    denominator. Fees and taxes are treated as part of the execution result.
    """
    zero = Decimal("0")
    quantities: dict[str, Decimal] = {}
    costs: dict[str, Decimal] = {}
    realized: dict[str, Decimal] = {}
    invested: dict[str, Decimal] = {}
    mismatched_instruments: set[str] = set()
    for trade in sorted(trades, key=lambda item: item.timestamp):
        instrument = trade.instrument_external_id
        qty = max(trade.quantity, zero)
        fees = trade.fees or zero
        taxes = trade.taxes or zero
        cash = max(trade.cash_amount, zero)
        external_flow = bool(
            isinstance(trade.raw_payload, dict)
            and trade.raw_payload.get("external_flow")
        )
        quantity = quantities.get(instrument, zero)
        cost = costs.get(instrument, zero)
        realized.setdefault(instrument, zero)
        invested.setdefault(instrument, zero)
        if trade.side == "buy":
            execution_cost = cash + fees + taxes
            quantities[instrument] = quantity + qty
            costs[instrument] = cost + execution_cost
            # A deposit is valued at its arrival price to keep the chart
            # performance-neutral, but it is not investor capital invested via
            # a purchase and therefore stays out of the percentage denominator.
            if not external_flow:
                invested[instrument] += execution_cost
        elif trade.side == "sell" and qty > zero:
            sold = min(qty, quantity)
            released = cost * sold / quantity if quantity > zero else zero
            if external_flow:
                quantities[instrument] = max(zero, quantity - sold)
                costs[instrument] = max(zero, cost - released)
                continue
            proceeds = max(zero, cash - fees - taxes)
            realized[instrument] += proceeds * (sold / qty) - released
            quantities[instrument] = max(zero, quantity - sold)
            costs[instrument] = max(zero, cost - released)
        elif trade.side == "income":
            realized[instrument] += cash - fees - taxes
        elif trade.side == "charge":
            realized[instrument] -= cash + fees + taxes
    # A provider can report a current holding whose original acquisition is
    # not present in the execution endpoint (deposits, migrations and old
    # account history are common examples).  The chart reconstruction uses the
    # position's average buy-in for that opening quantity.  Add the same
    # neutral opening cost here so the table and the final chart sample share
    # exactly one cost basis instead of disagreeing by the missing quantity.
    if positions:
        net_trade_quantity: dict[str, Decimal] = {}
        for trade in trades:
            if trade.side == "buy":
                net_trade_quantity[trade.instrument_external_id] = (
                    net_trade_quantity.get(trade.instrument_external_id, zero)
                    + max(trade.quantity, zero)
                )
            elif trade.side == "sell":
                net_trade_quantity[trade.instrument_external_id] = (
                    net_trade_quantity.get(trade.instrument_external_id, zero)
                    - max(trade.quantity, zero)
                )
        tolerance = Decimal("0.00000001")
        for position in positions:
            if position.average_buy_in is None:
                continue
            net_quantity = net_trade_quantity.get(position.external_id, zero)
            # A negative net execution quantity means the provider exposed
            # outflows without the original inflow (common with old converts
            # or transfers).  Do not back-solve ``current - negative``: that
            # manufactures a large phantom opening position and can turn a
            # tiny VET remainder into a four-digit loss.  The current holding
            # is the only defensible unknown opening quantity in that case.
            opening_quantity = (
                position.quantity
                if net_quantity < zero
                else position.quantity - net_quantity
            )
            if net_quantity < zero:
                mismatched_instruments.add(position.external_id)
            if opening_quantity > tolerance:
                quantities[position.external_id] = (
                    quantities.get(position.external_id, zero) + opening_quantity
                )
                costs[position.external_id] = costs.get(position.external_id, zero) + (
                    opening_quantity * position.average_buy_in
                )

        # The execution ledger and the current Binance balance do not always
        # describe the same universe.  Delisted pairs, conversions and old
        # imports can leave buys in the ledger while the current snapshot only
        # contains a tiny remainder.  In that case using the full ledger cost
        # for the current position creates a phantom loss (e.g. a few cents of
        # VET carrying a four-digit historical cost).  Reconcile the tracked
        # quantity to the provider's current holding and use its average buy-in
        # for that remaining quantity.  Realized P/L stays in ``realized``;
        # only the open position cost is corrected.
        for position in positions:
            if position.average_buy_in is None:
                continue
            current_quantity = max(position.quantity, zero)
            tracked_quantity = quantities.get(position.external_id, zero)
            quantity_tolerance = max(
                tolerance, current_quantity.copy_abs() * Decimal("0.001")
            )
            if (
                position.external_id in mismatched_instruments
                or (tracked_quantity - current_quantity).copy_abs() > quantity_tolerance
            ):
                mismatched_instruments.add(position.external_id)
                quantities[position.external_id] = current_quantity
                costs[position.external_id] = current_quantity * position.average_buy_in
    mismatched = frozenset(mismatched_instruments)
    if positions:
        for position in positions:
            current_quantity = max(position.quantity, zero)
            tracked_quantity = quantities.get(position.external_id, zero)
            tolerance = max(
                Decimal("0.00000001"), current_quantity.copy_abs() * Decimal("0.001")
            )
            if (tracked_quantity - current_quantity).copy_abs() > tolerance:
                mismatched = mismatched | frozenset({position.external_id})
    return _LedgerSummary(
        realized=realized,
        invested=invested,
        open_costs=costs,
        quantities=quantities,
        mismatched_instruments=mismatched,
    )


def _trade_performance_ledger(
    trades: list[AssetTradeData],
    positions: list[PositionData] | None = None,
) -> tuple[dict[str, Decimal], dict[str, Decimal], dict[str, Decimal]]:
    """Compatibility wrapper for callers that only need the three maps."""
    summary = _build_trade_ledger(trades, positions)
    return summary.realized, summary.invested, summary.open_costs


def _provider_relative_percent(value: object) -> Decimal | None:
    """Normalize Trade Republic's fractional relativeValue to display percent.

    The portfolio endpoint returns e.g. ``0.0528`` for a 5.28% result, while
    some older responses already contain ``5.28``.  Supporting both forms
    keeps migrated snapshots readable without changing stored raw payloads.
    """
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed * Decimal("100") if abs(parsed) <= Decimal("1") else parsed


@dataclass
class _HistoryResult:
    points: list[AssetHistoryPointRead]
    estimated: bool
    source: str
    calibration: AssetHistoryCalibrationRead | None = None


@router.get("", response_model=AssetsOverviewRead)
def assets_overview(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> AssetsOverviewRead:
    stored_portfolios = session.exec(select(Portfolio).order_by(Portfolio.id)).all()
    portfolios = sorted(
        (decode_portfolio(row, dek) for row in stored_portfolios),
        key=lambda item: item.name.casefold(),
    )
    result: list[PortfolioRead] = []
    for portfolio in portfolios:
        positions = []
        if portfolio.last_synced_at is not None:
            stored_positions = session.exec(
                    select(AssetPositionSnapshot)
                    .where(
                        AssetPositionSnapshot.portfolio_id == portfolio.id,
                        AssetPositionSnapshot.captured_at == portfolio.last_synced_at,
                    )
                    .order_by(AssetPositionSnapshot.id)
                ).all()
            positions = sorted(
                (decode_position(row, dek) for row in stored_positions),
                key=lambda item: item.market_value or Decimal("0"),
                reverse=True,
            )

        position_reads: list[AssetPositionRead] = []
        total_market = Decimal("0")
        total_cost = Decimal("0")
        total_gain = Decimal("0")
        unrealized_gain = Decimal("0")
        performance_cost = Decimal("0")
        total_gain_percent: Decimal | None = None
        priced_positions = 0
        trades = [
            decode_trade(row, dek)
            for row in session.exec(
                select(AssetTrade)
                .where(AssetTrade.portfolio_id == portfolio.id)
                .order_by(AssetTrade.timestamp)
            ).all()
        ]
        ledger = _build_trade_ledger(trades, positions)
        realized_by_instrument = ledger.realized
        invested_by_instrument = ledger.invested
        open_costs_by_instrument = ledger.open_costs
        for position in positions:
            cost_value = (
                position.average_buy_in * position.quantity
                if position.average_buy_in is not None
                else None
            )
            performance_cost_value = invested_by_instrument.get(position.external_id)
            ledger_cost_value = open_costs_by_instrument.get(position.external_id)
            # When an execution ledger is available it is the authoritative
            # cost basis: provider snapshots may predate a CSV import and
            # would otherwise make the displayed gain and percentage use two
            # different denominators.
            effective_cost_value = (
                ledger_cost_value
                if ledger_cost_value is not None and trades
                else cost_value
            )
            # A position row describes the currently held units.  Realized P/L
            # from earlier sales is portfolio-level performance and must not be
            # attached to the remaining dust/position (otherwise a sold VET
            # position could display a four-digit loss on a few cents).
            gain_value = (
                position.market_value - effective_cost_value
                if position.market_value is not None and effective_cost_value is not None
                else None
            )
            gain_percent = (
                gain_value / effective_cost_value * Decimal("100")
                if gain_value is not None and effective_cost_value not in (None, Decimal("0"))
                else None
            )
            if position.market_value is not None:
                total_market += position.market_value
                priced_positions += 1
                if effective_cost_value is not None:
                    total_cost += cost_value or Decimal("0")
                    unrealized_gain += position.market_value - effective_cost_value
            position_reads.append(
                AssetPositionRead(
                    id=position.id,  # type: ignore[arg-type]
                    external_id=position.external_id,
                    isin=position.isin,
                    name=position.name,
                    asset_type=position.asset_type,
                    quantity=position.quantity,
                    average_buy_in=position.average_buy_in,
                    current_price=position.current_price,
                    market_value=position.market_value,
                    cost_value=cost_value,
                    gain_value=gain_value,
                    gain_percent=gain_percent,
                    performance_cost_value=performance_cost_value,
                    currency=position.currency,
                )
            )

        # The denominator for portfolio P/L must include capital that was
        # invested in positions already sold.  Restricting it to currently
        # visible rows makes a realized gain/loss change the percentage just
        # because an instrument disappeared from the holdings table.
        performance_cost = sum(invested_by_instrument.values(), Decimal("0"))

        # Trade Republic's portfolio chart is an authoritative performance
        # series (Absolute Value). Use its latest point for the depot headline
        # as well; summing current asset positions alone omits provider-side
        # realized/closed positions and therefore cannot match the chart.
        total_gain = unrealized_gain + sum(realized_by_instrument.values(), Decimal("0"))
        if portfolio.source == AccountSource.TRADE_REPUBLIC:
            provider_points = _provider_performance_points(session, portfolio, None, dek)
            if provider_points:
                # Use the exact same series that /api/assets/history exposes.
                total_gain = provider_points[-1].value
            provider_row = session.exec(
                select(PortfolioValuePoint)
                .where(
                    PortfolioValuePoint.portfolio_id == portfolio.id,
                    PortfolioValuePoint.history_range == "max",
                )
                .order_by(PortfolioValuePoint.timestamp.desc())
                .limit(1)
            ).first()
            if provider_row is not None:
                performance = (decode_portfolio_value(provider_row, dek).raw_payload or {}).get("performance")
                if isinstance(performance, dict):
                    raw_percent = performance.get("relativeValue", performance.get("relativePerformance", performance.get("percentage")))
                    try:
                        total_gain_percent = _provider_relative_percent(raw_percent)
                    except (InvalidOperation, TypeError, ValueError):
                        total_gain_percent = None
        aggregate = _aggregate_performance([(total_gain, performance_cost)])
        total_gain = aggregate.absolute
        if total_gain_percent is None:
            total_gain_percent = aggregate.percent
        result.append(
            PortfolioRead(
                id=portfolio.id,  # type: ignore[arg-type]
                connection_id=portfolio.connection_id,
                source=portfolio.source,
                name=portfolio.name,
                currency=portfolio.currency,
                last_synced_at=portfolio.last_synced_at,
                total_market_value=total_market,
                total_cost_value=total_cost,
                total_gain_value=total_gain,
                total_gain_percent=total_gain_percent,
                performance_cost_value=performance_cost,
                priced_positions=priced_positions,
                positions=position_reads,
            )
        )
    return AssetsOverviewRead(portfolios=result)


@router.get("/history", response_model=AssetHistoryRead)
def asset_history(
    portfolio_id: int | None = None,
    range_: str = Query(default="1y", alias="range", pattern="^(1d|5d|1m|1y|max)$"),
    external_id: str | None = None,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> AssetHistoryRead:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=RANGE_DAYS[range_])
        if range_ in RANGE_DAYS
        else None
    )

    if portfolio_id is None:
        portfolios = [
            decode_portfolio(row, dek)
            for row in session.exec(select(Portfolio).order_by(Portfolio.id)).all()
        ]
        series: list[list[AssetHistoryPointRead]] = []
        estimated = False
        for item in portfolios:
            item_result = _portfolio_history_result(
                session, item, cutoff, range_, dek
            )
            if item_result.points:
                series.append(item_result.points)
                estimated = estimated or item_result.estimated
        combined = _combine_value_series(series)
        return AssetHistoryRead(
            kind="aggregate",
            label="Total portfolio",
            currency="EUR",
            estimated=estimated,
            source="mixed",
            points=_downsample(combined),
        )

    stored_portfolio = session.get(Portfolio, portfolio_id)
    if stored_portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    portfolio = decode_portfolio(stored_portfolio, dek)

    if external_id:
        exchange_row = session.exec(
            select(AssetPricePoint.exchange, func.count(AssetPricePoint.id))
            .where(
                AssetPricePoint.source == portfolio.source,
                AssetPricePoint.external_id == external_id,
            )
            .group_by(AssetPricePoint.exchange)
            .order_by(func.count(AssetPricePoint.id).desc())
        ).first()
        exchange = exchange_row[0] if exchange_row else None
        query = select(AssetPricePoint).where(
            AssetPricePoint.source == portfolio.source,
            AssetPricePoint.external_id == external_id,
        )
        if exchange:
            query = query.where(AssetPricePoint.exchange == exchange)
        if cutoff:
            query = query.where(AssetPricePoint.timestamp >= cutoff)
        rows = list(session.exec(query.order_by(AssetPricePoint.timestamp)).all())
        stored_positions = session.exec(
            select(AssetPositionSnapshot)
            .where(AssetPositionSnapshot.portfolio_id == portfolio_id)
            .order_by(AssetPositionSnapshot.captured_at.desc())
        ).all()
        latest_position = next(
            (
                decoded
                for row in stored_positions
                if (decoded := decode_position(row, dek)).external_id == external_id
            ),
            None,
        )
        label = latest_position.name if latest_position else external_id
        currency = rows[-1].currency if rows else portfolio.currency
        # Prefer a historical ledger when executions are available. Some
        # providers (notably older Trade Republic data) expose prices and the
        # current position but no historical executions; retain a clearly
        # estimated fallback for those assets instead of inventing a curve.
        instrument_trades = [
            decode_trade(row, dek)
            for row in session.exec(
                select(AssetTrade).where(AssetTrade.portfolio_id == portfolio_id)
            ).all()
        ]
        instrument_trades = [
            trade for trade in instrument_trades if trade.instrument_external_id == external_id
        ]
        current_cost = None
        if latest_position and latest_position.average_buy_in is not None:
            current_cost = latest_position.average_buy_in * latest_position.quantity
        fallback_points = [
            AssetHistoryPointRead(
                timestamp=row.timestamp,
                value=row.close * latest_position.quantity
                if latest_position is not None
                else row.close,
                invested_value=current_cost,
            )
            for row in rows
        ]
        reconstructed, estimated = _reconstruct_portfolio_performance(
            [latest_position] if latest_position else [],
            instrument_trades,
            {external_id: rows},
        ) if instrument_trades else ([], True)
        points = reconstructed or fallback_points
        return AssetHistoryRead(
            kind="instrument",
            label=label,
            currency=currency,
            estimated=estimated or (not bool(reconstructed) and current_cost is not None),
            source="calculated" if reconstructed or current_cost is not None else "market_price",
            points=_downsample(points),
        )

    result = _portfolio_history_result(session, portfolio, cutoff, range_, dek)
    return AssetHistoryRead(
        kind="portfolio",
        label=portfolio.name,
        currency=portfolio.currency,
        estimated=result.estimated,
        source=result.source,
        calibration=result.calibration,
        points=_downsample(result.points),
    )


def _portfolio_history_result(
    session: Session,
    portfolio: PortfolioData,
    cutoff: datetime | None,
    _history_range: str = "max",
    dek: bytes = b"",
) -> _HistoryResult:
    """Use broker performance when authoritative, otherwise rebuild the ledger."""
    if portfolio.source == AccountSource.TRADE_REPUBLIC:
        provider_points = (
            _provider_performance_points(session, portfolio, cutoff, dek)
            if dek
            else _provider_performance_points(session, portfolio, cutoff)
        )
        if provider_points:
            return _HistoryResult(
                points=provider_points,
                estimated=False,
                source="provider",
            )
        # Do not silently replace Trade Republic's missing performance data with
        # an incomplete ledger reconstruction. Older migrated events do not
        # consistently contain the quantities and cash values needed for it.
        return _HistoryResult([], True, "unavailable")
    points, estimated, _ = _calculated_portfolio_history_points(
        session, portfolio, cutoff, dek
    )
    return _HistoryResult(points, estimated, "calculated")


def _portfolio_history_points(
    session: Session,
    portfolio: PortfolioData,
    cutoff: datetime | None,
    history_range: str = "max",
    dek: bytes = b"",
) -> tuple[list[AssetHistoryPointRead], bool]:
    """Compatibility wrapper used by diagnostics and existing callers."""
    result = _portfolio_history_result(session, portfolio, cutoff, history_range, dek)
    return result.points, result.estimated


def _calculated_portfolio_history_points(
    session: Session,
    portfolio: PortfolioData,
    cutoff: datetime | None,
    dek: bytes,
) -> tuple[list[AssetHistoryPointRead], bool, datetime | None]:
    """Rebuild performance from holdings and cost basis at each point in time."""
    if portfolio.last_synced_at is None:
        return [], True, None
    stored_positions = session.exec(
            select(AssetPositionSnapshot).where(
                AssetPositionSnapshot.portfolio_id == portfolio.id,
                AssetPositionSnapshot.captured_at == portfolio.last_synced_at,
            )
        ).all()
    positions = [decode_position(row, dek) for row in stored_positions]
    # Historical snapshots retain the last provider-derived cost basis. This
    # also repairs charts created from an already stored delta snapshot that
    # accidentally omitted average_buy_in, without mutating data in a GET.
    if any(position.average_buy_in is None for position in positions):
        stored_cost_rows = session.exec(
            select(AssetPositionSnapshot)
            .where(AssetPositionSnapshot.portfolio_id == portfolio.id)
            .order_by(AssetPositionSnapshot.captured_at.desc())
        ).all()
        known_cost_rows = [
            decoded
            for row in stored_cost_rows
            if (decoded := decode_position(row, dek)).average_buy_in is not None
        ]
        last_known_average: dict[str, Decimal] = {}
        for known in known_cost_rows:
            if known.average_buy_in is not None:
                last_known_average.setdefault(known.external_id, known.average_buy_in)
        positions = [
            replace(
                position,
                average_buy_in=last_known_average.get(position.external_id),
            )
            if position.average_buy_in is None
            and position.external_id in last_known_average
            else position
            for position in positions
        ]
    trades = [
        decode_trade(row, dek)
        for row in session.exec(
            select(AssetTrade)
            .where(AssetTrade.portfolio_id == portfolio.id)
            .order_by(AssetTrade.timestamp)
        ).all()
    ]
    # Without executions we cannot know when today's positions were acquired.
    # Returning the current point is more honest than projecting them backwards.
    if not trades:
        return _current_portfolio_point(portfolio, positions, []), True, None
    first_trade = min(trade.timestamp for trade in trades)

    instrument_ids = {
        position.external_id for position in positions
    } | {trade.instrument_external_id for trade in trades}
    prices_by_instrument: dict[str, list[AssetPricePoint]] = {}
    for external_id in instrument_ids:
        exchange_row = session.exec(
            select(AssetPricePoint.exchange, func.count(AssetPricePoint.id))
            .where(
                AssetPricePoint.source == portfolio.source,
                AssetPricePoint.external_id == external_id,
            )
            .group_by(AssetPricePoint.exchange)
            .order_by(func.count(AssetPricePoint.id).desc())
        ).first()
        if exchange_row is None:
            continue
        price_query = select(AssetPricePoint).where(
            AssetPricePoint.source == portfolio.source,
            AssetPricePoint.external_id == external_id,
            AssetPricePoint.exchange == exchange_row[0],
        )
        prices = list(session.exec(price_query.order_by(AssetPricePoint.timestamp)).all())
        if prices:
            prices_by_instrument[external_id] = prices

    points, estimated = _reconstruct_portfolio_performance(
        positions, trades, prices_by_instrument
    )
    current = _current_portfolio_point(portfolio, positions, trades)
    # The latest provider snapshot is the source of truth for the table. Add
    # it to a calculated series when the last candle predates that snapshot so
    # the final chart sample and the headline P/L cannot drift apart. This is
    # a real captured observation, not a fabricated interpolation.
    if current:
        if points and current[0].timestamp == points[-1].timestamp:
            points[-1] = current[0]
        elif not points or current[0].timestamp > points[-1].timestamp:
            points.append(current[0])
    if cutoff is not None:
        points = [point for point in points if point.timestamp >= cutoff]
    return points, estimated, first_trade


def _performance_value(point: AssetHistoryPointRead) -> Decimal | None:
    if point.invested_value is None:
        return None
    return point.value - point.invested_value


def _provider_performance_points(
    session: Session,
    portfolio: PortfolioData,
    cutoff: datetime | None,
    dek: bytes = b"",
) -> list[AssetHistoryPointRead]:
    """Return one canonical broker performance series, then crop it for display."""
    query = select(PortfolioValuePoint).where(
        PortfolioValuePoint.portfolio_id == portfolio.id,
        PortfolioValuePoint.history_range == "max",
    )
    if cutoff is not None:
        query = query.where(PortfolioValuePoint.timestamp >= cutoff)
    stored_rows = session.exec(query.order_by(PortfolioValuePoint.timestamp)).all()
    rows = (
        [decode_portfolio_value(row, dek) for row in stored_rows]
        if dek
        else stored_rows
    )
    result: list[AssetHistoryPointRead] = []
    for row in rows:
        raw = row.raw_payload or {}
        performance = raw.get("performance")
        absolute = (
            performance.get("absoluteValue")
            if isinstance(performance, dict)
            else None
        )
        try:
            value = Decimal(str(absolute))
        except (InvalidOperation, TypeError, ValueError):
            continue
        relative = performance.get("relativeValue") if isinstance(performance, dict) else None
        result.append(
            AssetHistoryPointRead(
                timestamp=row.timestamp,
                value=value,
                invested_value=Decimal("0"),
                performance_percent=_provider_relative_percent(relative)
                if relative is not None
                else None,
            )
        )
    return result


def _current_portfolio_point(
    portfolio: PortfolioData,
    positions: list[PositionData],
    trades: list[AssetTradeData] | None = None,
) -> list[AssetHistoryPointRead]:
    realized_total = Decimal("0")
    if trades:
        ledger = _build_trade_ledger(trades, positions)
        realized_by_instrument = ledger.realized
        open_costs = ledger.open_costs
        realized_total = sum(realized_by_instrument.values(), Decimal("0"))
        priced_positions = [
            position
            for position in positions
            if position.market_value is not None
            and open_costs.get(position.external_id) is not None
        ]
        costs = [open_costs[position.external_id] for position in priced_positions]
    else:
        priced_positions = [
            position
            for position in positions
            if position.market_value is not None
            and _position_cost_value(position) is not None
        ]
        costs = [_position_cost_value(position) for position in priced_positions]
    current_value = sum(
        (position.market_value or Decimal("0") for position in priced_positions),
        Decimal("0"),
    )
    invested = (
        sum((value for value in costs if value is not None), Decimal("0"))
        if costs and all(value is not None for value in costs)
        else None
    )
    if portfolio.last_synced_at is None or current_value <= 0:
        return []
    return [
        AssetHistoryPointRead(
            timestamp=portfolio.last_synced_at,
            value=current_value + realized_total,
            invested_value=invested,
        )
    ]


def _reconstruct_portfolio_performance(
    positions: list[PositionData],
    trades: list[AssetTradeData],
    prices_by_instrument: dict[str, list[AssetPricePoint]],
) -> tuple[list[AssetHistoryPointRead], bool]:
    """Apply executions to a moving-average ledger over the price timeline."""
    zero = Decimal("0")
    current = {position.external_id: position for position in positions}
    trade_delta: dict[str, Decimal] = {}
    trade_instruments_with_buy: set[str] = set()
    for trade in trades:
        signed = trade.quantity if trade.side == "buy" else -trade.quantity
        trade_delta[trade.instrument_external_id] = (
            trade_delta.get(trade.instrument_external_id, zero) + signed
        )
        if trade.side == "buy" and trade.quantity > zero:
            trade_instruments_with_buy.add(trade.instrument_external_id)

    instrument_ids = set(prices_by_instrument) | set(trade_delta) | set(current)
    quantities: dict[str, Decimal] = {}
    costs: dict[str, Decimal] = {}
    cost_basis_known: dict[str, bool] = {}
    estimated = False
    for instrument_id in instrument_ids:
        current_position = current.get(instrument_id)
        current_quantity = current_position.quantity if current_position else zero
        net_delta = trade_delta.get(instrument_id, zero)
        if net_delta < zero:
            # See the matching ledger guard above: missing historical inflows
            # must not be inferred by adding every old outflow to the current
            # balance. Keep only the observed current quantity and mark the
            # earlier section as estimated.
            opening_quantity = current_quantity
            estimated = True
        else:
            opening_quantity = current_quantity - net_delta
        if abs(opening_quantity) < Decimal("0.00000001"):
            opening_quantity = zero
        elif opening_quantity < 0:
            # More outflow is present than the current snapshot and imported
            # inflows can explain. A historical event is missing; do not invent
            # a negative opening holding merely to force reconciliation.
            opening_quantity = zero
            estimated = True
        quantities[instrument_id] = opening_quantity
        # A current average buy-in or at least one execution gives us a
        # defensible cost basis.  A position that has neither is still shown
        # in the overview, but must not silently inflate historical P/L.
        cost_basis_known[instrument_id] = bool(
            current_position and current_position.average_buy_in is not None
        ) or instrument_id in trade_instruments_with_buy
        if opening_quantity > 0:
            estimated = True
            average = (
                current_position.average_buy_in
                if current_position and current_position.average_buy_in is not None
                else None
            )
            costs[instrument_id] = opening_quantity * average if average is not None else zero
            estimated = estimated or average is None
        else:
            costs[instrument_id] = zero

    # If replaying the stored executions does not end at the provider's
    # current quantity, at least one historical inflow/outflow is missing (or
    # belongs to a delisted pair).  Do not let that unmatched ledger create a
    # large artificial market value or break-even denominator in the chart.
    for instrument_id in instrument_ids:
        net_delta = trade_delta.get(instrument_id, zero)
        replayed_quantity = quantities.get(instrument_id, zero) + net_delta
        current_quantity = current.get(instrument_id).quantity if instrument_id in current else zero
        quantity_tolerance = max(
            Decimal("0.00000001"), current_quantity.copy_abs() * Decimal("0.001")
        )
        if (replayed_quantity - current_quantity).copy_abs() > quantity_tolerance:
            cost_basis_known[instrument_id] = False
            estimated = True

    timeline = sorted(
        {point.timestamp for rows in prices_by_instrument.values() for point in rows}
    )
    ordered_trades = sorted(trades, key=lambda trade: trade.timestamp)
    if ordered_trades:
        first_evidence = ordered_trades[0].timestamp
        timeline = [timestamp for timestamp in timeline if timestamp >= first_evidence]
    price_indices = {instrument_id: 0 for instrument_id in instrument_ids}
    latest_prices: dict[str, Decimal] = {}
    trade_index = 0
    realized = zero
    result: list[AssetHistoryPointRead] = []
    has_ever_held = any(quantity > 0 for quantity in quantities.values())

    for timestamp in timeline:
        while trade_index < len(ordered_trades) and ordered_trades[trade_index].timestamp <= timestamp:
            trade = ordered_trades[trade_index]
            instrument_id = trade.instrument_external_id
            quantity = quantities.get(instrument_id, zero)
            cost = costs.get(instrument_id, zero)
            external_flow = bool(
                isinstance(trade.raw_payload, dict)
                and trade.raw_payload.get("external_flow")
            )
            if trade.side == "buy":
                quantities[instrument_id] = quantity + trade.quantity
                costs[instrument_id] = cost + trade.cash_amount + (trade.fees or zero) + (trade.taxes or zero)
                has_ever_held = True
            elif trade.side == "sell" and quantity > 0 and trade.quantity > 0:
                sold_quantity = min(trade.quantity, quantity)
                released_cost = cost * sold_quantity / quantity
                if external_flow:
                    quantities[instrument_id] = quantity - sold_quantity
                    costs[instrument_id] = max(zero, cost - released_cost)
                    trade_index += 1
                    continue
                proceeds = max(
                    zero,
                    (trade.cash_amount - (trade.fees or zero) - (trade.taxes or zero))
                    * sold_quantity / trade.quantity,
                )
                realized += proceeds - released_cost
                quantities[instrument_id] = quantity - sold_quantity
                costs[instrument_id] = max(zero, cost - released_cost)
            elif trade.side == "income":
                realized += trade.cash_amount
            elif trade.side == "charge":
                realized -= trade.cash_amount
            elif trade.side == "sell":
                estimated = True
            trade_index += 1

        for instrument_id, rows in prices_by_instrument.items():
            index = price_indices.get(instrument_id, 0)
            while index < len(rows) and rows[index].timestamp <= timestamp:
                latest_prices[instrument_id] = rows[index].close
                index += 1
            price_indices[instrument_id] = index

        if not has_ever_held:
            continue
        missing_price = any(
            quantity > 0 and instrument_id not in latest_prices
            for instrument_id, quantity in quantities.items()
        )
        if missing_price:
            estimated = True
            # Keep the valued portion visible instead of suppressing the whole
            # portfolio until the newest/unresolved asset has its first candle.
            # The API exposes `estimated`, so the UI can state that this earlier
            # section is only a lower bound.
        market_value = sum(
            (
                quantity * latest_prices[instrument_id]
                for instrument_id, quantity in quantities.items()
                if quantity > 0
                and instrument_id in latest_prices
                and cost_basis_known.get(instrument_id, False)
            ),
            zero,
        )
        # Do not put an unpriced holding into the break-even denominator. The
        # corresponding market value is not visible at this timestamp either;
        # including its cost would manufacture a negative P/L spike.
        open_cost = sum(
            (
                cost
                for instrument_id, cost in costs.items()
                if quantities.get(instrument_id, zero) > zero
                and instrument_id in latest_prices
                and cost_basis_known.get(instrument_id, False)
            ),
            zero,
        )
        result.append(
            AssetHistoryPointRead(
                timestamp=timestamp,
                value=market_value + realized,
                invested_value=open_cost,
            )
        )
    return result, estimated


def _position_cost_value(
    position: PositionData, historical_price: Decimal | None = None
) -> Decimal | None:
    if position.average_buy_in is not None:
        return position.average_buy_in * position.quantity
    # Provider rewards and conversion remnants frequently leave sub-euro dust
    # without an execution history. Keep that immaterial amount performance-
    # neutral instead of hiding the reference for the entire portfolio.
    if (
        position.market_value is not None
        and abs(position.market_value) < IMMATERIAL_POSITION_EUR
    ):
        return (
            historical_price * position.quantity
            if historical_price is not None
            else position.market_value
        )
    return None


def _combine_value_series(
    series: list[list[AssetHistoryPointRead]],
) -> list[AssetHistoryPointRead]:
    """Forward-fill independent EUR histories on their combined time axis."""
    ordered = [sorted(items, key=lambda point: point.timestamp) for items in series if items]
    if not ordered:
        return []
    timeline = sorted({point.timestamp for items in ordered for point in items})
    indices = [0] * len(ordered)
    latest: list[Decimal | None] = [None] * len(ordered)
    latest_invested: list[Decimal | None] = [None] * len(ordered)
    result: list[AssetHistoryPointRead] = []
    for timestamp in timeline:
        for index, items in enumerate(ordered):
            while indices[index] < len(items) and items[indices[index]].timestamp <= timestamp:
                latest[index] = items[indices[index]].value
                latest_invested[index] = items[indices[index]].invested_value
                indices[index] += 1
        values = [value for value in latest if value is not None]
        if values:
            active_indices = [index for index, value in enumerate(latest) if value is not None]
            invested_values = [latest_invested[index] for index in active_indices]
            invested_total = (
                sum((value for value in invested_values if value is not None), Decimal("0"))
                if invested_values and all(value is not None for value in invested_values)
                else None
            )
            result.append(
                AssetHistoryPointRead(
                    timestamp=timestamp,
                    value=sum(values, Decimal("0")),
                    invested_value=invested_total,
                )
            )
    return result


def _downsample(
    points: list[AssetHistoryPointRead], maximum: int = 600
) -> list[AssetHistoryPointRead]:
    if len(points) <= maximum:
        return points
    step = ceil((len(points) - 1) / (maximum - 1))
    sampled = points[:-1:step]
    sampled.append(points[-1])
    return sampled
