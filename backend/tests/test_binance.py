from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.adapters.binance import BinanceAdapter


def test_moving_average_cost_tracks_open_position() -> None:
    average, summary = BinanceAdapter._open_average_cost(
        [
            {"time": 1, "isBuyer": True, "qty": "2", "quoteQty": "200"},
            {"time": 2, "isBuyer": False, "qty": "1", "quoteQty": "120"},
            {"time": 3, "isBuyer": True, "qty": "1", "quoteQty": "150"},
        ],
        "BTC",
        "EUR",
    )

    assert average == Decimal("125")
    assert summary["open_trade_quantity"] == "2"
    assert summary["buy_count"] == 2
    assert summary["sell_count"] == 1


def test_moving_average_cost_includes_eur_fee_on_buy() -> None:
    average, summary = BinanceAdapter._open_average_cost(
        [
            {
                "time": 1,
                "isBuyer": True,
                "qty": "1",
                "quoteQty": "100",
                "commission": "1",
                "commissionAsset": "EUR",
            }
        ],
        "BTC",
        "EUR",
    )

    assert average == Decimal("101")
    assert summary["open_trade_quantity"] == "1"


def test_moving_average_cost_includes_base_asset_fee_at_execution_price() -> None:
    average, summary = BinanceAdapter._open_average_cost(
        [
            {
                "time": 1,
                "isBuyer": True,
                "qty": "1",
                "quoteQty": "100",
                "commission": "0.01",
                "commissionAsset": "BTC",
            }
        ],
        "BTC",
        "EUR",
    )

    assert average == Decimal("102.0202020202020202020202020")
    assert summary["open_trade_quantity"] == "0.99"


def test_moving_average_cost_releases_base_fee_on_sell() -> None:
    average, summary = BinanceAdapter._open_average_cost(
        [
            {
                "time": 1,
                "isBuyer": True,
                "qty": "1",
                "quoteQty": "100",
                "commission": "0",
                "commissionAsset": "BTC",
            },
            {
                "time": 2,
                "isBuyer": False,
                "qty": "0.5",
                "quoteQty": "60",
                "commission": "0.01",
                "commissionAsset": "BTC",
            },
        ],
        "BTC",
        "EUR",
    )

    assert average == Decimal("100")
    assert summary["open_trade_quantity"] == "0.49"


def test_fetches_spot_assets_through_official_read_only_endpoints() -> None:
    requested_paths: list[str] = []
    requested_kline_intervals: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_800_000_000_000})
        if request.url.path == "/api/v3/account":
            assert request.headers["X-MBX-APIKEY"] == "read-only-key"
            assert "signature" in request.url.params
            return httpx.Response(
                200,
                json={
                    "balances": [
                        {"asset": "BTC", "free": "0.5", "locked": "0"},
                        {"asset": "EUR", "free": "100", "locked": "0"},
                        {"asset": "ETH", "free": "0", "locked": "0"},
                    ]
                },
            )
        if request.url.path == "/api/v3/ticker/price":
            return httpx.Response(200, json=[{"symbol": "BTCEUR", "price": "50000"}])
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(
                200,
                json={"symbols": [{"symbol": "BTCEUR", "status": "TRADING"}]},
            )
        if request.url.path == "/sapi/v1/asset/get-funding-asset":
            assert request.method == "POST"
            assert request.headers["X-MBX-APIKEY"] == "read-only-key"
            assert b"signature=" in request.content
            return httpx.Response(
                200,
                json=[
                    {
                        "asset": "BTC",
                        "free": "0.2",
                        "locked": "0",
                        "freeze": "0",
                        "withdrawing": "0",
                    },
                    {
                        "asset": "EUR",
                        "free": "25",
                        "locked": "0",
                        "freeze": "0",
                        "withdrawing": "0",
                    },
                ],
            )
        if request.url.path == "/sapi/v1/simple-earn/flexible/position":
            return httpx.Response(
                200,
                json={
                    "rows": [{"asset": "BTC", "totalAmount": "0.1"}],
                    "total": 1,
                },
            )
        if request.url.path == "/sapi/v1/simple-earn/locked/position":
            return httpx.Response(200, json={"rows": [], "total": 0})
        if request.url.path == "/api/v3/myTrades":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "time": 1,
                        "isBuyer": True,
                        "qty": "0.6",
                        "quoteQty": "24000",
                        "commission": "0",
                        "commissionAsset": "BTC",
                    }
                ],
            )
        if request.url.path in {
            "/sapi/v1/capital/deposit/hisrec",
            "/sapi/v1/capital/withdraw/history",
        }:
            return httpx.Response(200, json=[])
        if request.url.path == "/sapi/v1/asset/assetDividend":
            return httpx.Response(200, json={"rows": [], "total": 0})
        if request.url.path == "/sapi/v1/convert/tradeFlow":
            return httpx.Response(200, json={"list": [], "moreData": False})
        if request.url.path in {
            "/sapi/v1/simple-earn/flexible/history/rewardsRecord",
            "/sapi/v1/simple-earn/locked/history/rewardsRecord",
        }:
            return httpx.Response(200, json={"rows": [], "total": 0})
        if request.url.path == "/sapi/v1/asset/dribblet":
            return httpx.Response(200, json={"userAssetDribblets": []})
        if request.url.path == "/api/v3/klines":
            requested_kline_intervals.append(str(request.url.params.get("interval")))
            return httpx.Response(
                200,
                json=[[1_799_900_000_000, "49000", "51000", "48000", "50000", "10"]],
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = BinanceAdapter(
            {"api_key": "read-only-key", "api_secret": "secret"},
            client=client,
        )
        portfolios = adapter.fetch_portfolios(history_range="5d")
        accounts = adapter.list_accounts()
        euro_balance = adapter.fetch_balance(accounts[0])

    assert len(portfolios) == 1
    assert portfolios[0].external_id == "binance-spot"
    positions = {position.external_id: position for position in portfolios[0].positions}
    assert positions["BTC"].quantity == Decimal("0.8")
    assert positions["BTC"].market_value == Decimal("40000.0")
    assert positions["BTC"].average_buy_in == Decimal("4.000E+4")
    assert positions["BTC"].raw_payload["cost_basis"]["history"][0][
        "open_cost_eur"
    ] == "24000"
    assert "EUR" not in positions
    assert len(accounts) == 1
    assert accounts[0].external_id == "binance-cash-EUR"
    assert euro_balance is not None
    assert euro_balance.booked == Decimal("125")
    assert set(euro_balance.raw_payload["locations"]) == {"spot", "funding"}
    assert portfolios[0].price_history[0].close == Decimal("50000")
    assert len(portfolios[0].trades) == 1
    assert portfolios[0].trades[0].external_id.startswith("binance:spot:BTCEUR")
    assert "1d" in requested_kline_intervals
    assert all("order" not in path.lower() for path in requested_paths)


def test_maps_both_spot_legs_with_historical_eur_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.params.get("symbol")
        if request.url.path == "/api/v3/klines" and symbol == "USDTEUR":
            return httpx.Response(
                200,
                json=[[1_700_000_000_000, "0.9", "0.9", "0.9", "0.9", "1"]],
            )
        return httpx.Response(400, json={"code": -1121})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = BinanceAdapter({}, client=client)
        trades = adapter._map_spot_trade_ledger(
            client,
            [
                {
                    "id": 7,
                    "time": 1_700_000_000_000,
                    "isBuyer": True,
                    "qty": "0.02",
                    "quoteQty": "1000",
                    "commission": "0",
                    "commissionAsset": "BTC",
                }
            ],
            base_asset="BTC",
            quote_asset="USDT",
        )

    assert [(trade.instrument_external_id, trade.side) for trade in trades] == [
        ("BTC", "buy"),
        ("USDT", "sell"),
    ]
    assert all(trade.cash_amount == Decimal("900.0") for trade in trades)


def test_incremental_sync_still_loads_complete_spot_history_for_cost_basis() -> None:
    requested_start_times: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_800_000_000_000})
        if request.url.path == "/api/v3/myTrades":
            requested_start_times.append(int(request.url.params["startTime"]))
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = BinanceAdapter(
            {"api_key": "read-only-key", "api_secret": "secret"},
            client=client,
        )
        adapter.prepare_asset_sync(
            known_trade_external_ids={"existing"},
            known_history_external_ids={"BTC"},
            has_history=True,
            has_complete_trade_history=True,
        )
        adapter._all_spot_trades(client, "BTCEUR")

    expected = int(datetime(2017, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert requested_start_times == [expected]


def test_includes_previously_observed_delisted_pairs_for_asset_history() -> None:
    adapter = BinanceAdapter({})
    adapter.prepare_asset_sync(
        known_trade_external_ids=set(),
        known_history_external_ids=set(),
        has_history=True,
        has_complete_trade_history=True,
        known_trade_symbols={"VETBTC"},
    )

    symbols = adapter._trade_symbols_for_asset(
        "VET",
        {"VETEUR"},
        {"VETEUR": Decimal("0.01"), "BTCEUR": Decimal("50000")},
    )

    assert symbols == ["VETBTC", "VETEUR"]


def test_maps_external_capital_flows_at_historical_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/klines":
            return httpx.Response(
                200,
                json=[[1_700_000_000_000, "40000", "40000", "40000", "40000", "1"]],
            )
        return httpx.Response(400)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = BinanceAdapter({}, client=client)
        deposit = adapter._map_capital_event(
            client,
            {
                "id": "deposit-1",
                "coin": "BTC",
                "amount": "0.1",
                "insertTime": 1_700_000_000_000,
                "status": 1,
            },
            "deposit",
        )

    assert deposit is not None
    assert deposit.side == "buy"
    assert deposit.quantity == Decimal("0.1")
    assert deposit.cash_amount == Decimal("4000.0")
    assert deposit.raw_payload["external_flow"] is True


def test_quote_currency_fee_is_not_added_to_executed_notional_twice() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/klines":
            return httpx.Response(
                200,
                json=[[1_700_000_000_000, "1", "1", "1", "1", "1"]],
            )
        return httpx.Response(400, json={"code": -1121})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = BinanceAdapter({}, client=client)
        trades = adapter._map_spot_trade_ledger(
            client,
            [
                {
                    "id": 8,
                    "time": 1_700_000_000_000,
                    "isBuyer": True,
                    "qty": "2",
                    "quoteQty": "100",
                    "commission": "1",
                    "commissionAsset": "USDT",
                }
            ],
            base_asset="BTC",
            quote_asset="USDT",
        )

    base = next(trade for trade in trades if trade.instrument_external_id == "BTC")
    assert base.cash_amount == Decimal("100")
    assert base.fees == Decimal("1")


def test_quote_currency_fee_on_sell_uses_net_quote_leg() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/klines":
            return httpx.Response(
                200,
                json=[[1_700_000_000_000, "1", "1", "1", "1", "1"]],
            )
        return httpx.Response(400, json={"code": -1121})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = BinanceAdapter({}, client=client)
        trades = adapter._map_spot_trade_ledger(
            client,
            [
                {
                    "id": 9,
                    "time": 1_700_000_000_000,
                    "isBuyer": False,
                    "qty": "2",
                    "quoteQty": "100",
                    "commission": "1",
                    "commissionAsset": "USDT",
                }
            ],
            base_asset="BTC",
            quote_asset="USDT",
        )

    quote = next(trade for trade in trades if trade.instrument_external_id == "USDT")
    assert quote.quantity == Decimal("99")
    assert quote.cash_amount == Decimal("99")
