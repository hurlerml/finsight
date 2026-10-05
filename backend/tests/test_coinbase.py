from decimal import Decimal

from app.adapters.coinbase import CoinbaseAdapter


class FakeCoinbaseClient:
    def get_accounts(self, **_kwargs):
        return {
            "accounts": [
                {
                    "uuid": "eur-account",
                    "currency": "EUR",
                    "available_balance": {"value": "120", "currency": "EUR"},
                    "hold": {"value": "5", "currency": "EUR"},
                },
                {
                    "uuid": "btc-account",
                    "currency": "BTC",
                    "available_balance": {"value": "0.1", "currency": "BTC"},
                    "hold": {"value": "0", "currency": "BTC"},
                },
            ],
            "has_next": False,
            "cursor": "",
        }

    def get_portfolios(self):
        return {"portfolios": [{"uuid": "portfolio-1", "name": "Coinbase Main"}]}

    def get_portfolio_breakdown(self, portfolio_uuid, currency):
        assert portfolio_uuid == "portfolio-1"
        assert currency == "EUR"
        return {
            "breakdown": {
                "portfolio_balances": {
                    "total_crypto_balance": {"value": "6000", "currency": "EUR"},
                    "total_cash_equivalent_balance": {"value": "125", "currency": "EUR"},
                },
                "spot_positions": [
                    {
                        "asset": "BTC",
                        "account_uuid": "btc-account",
                        "total_balance_crypto": "0.1",
                        "total_balance_fiat": "6000",
                        "cost_basis": {"value": "5000", "currency": "EUR"},
                    },
                    {
                        "asset": "EUR",
                        "total_balance_crypto": "125",
                        "total_balance_fiat": "125",
                    },
                ],
            }
        }

    def get_fills(self, **kwargs):
        assert kwargs["retail_portfolio_id"] == "portfolio-1"
        return {
            "fills": [
                {
                    "entry_id": "fill-1",
                    "trade_time": "2026-09-01T10:00:00Z",
                    "product_id": "BTC-EUR",
                    "side": "BUY",
                    "size": "0.1",
                    "size_in_quote": "5000",
                    "price": "50000",
                    "commission": "10",
                }
            ],
            "cursor": "",
        }

    def get_public_candles(self, **kwargs):
        assert kwargs["product_id"] == "BTC-EUR"
        return {
            "candles": [
                {
                    "start": "1788220800",
                    "open": "50000",
                    "high": "62000",
                    "low": "49000",
                    "close": "60000",
                    "volume": "100",
                }
            ]
        }


def test_coinbase_maps_official_sdk_responses() -> None:
    adapter = CoinbaseAdapter(
        {"api_key": "organizations/example/apiKeys/key", "api_secret": "private"},
        client=FakeCoinbaseClient(),
    )

    account = adapter.list_accounts()[0]
    balance = adapter.fetch_balance(account)
    portfolio = adapter.fetch_portfolios(history_range="5d")[0]

    assert account.external_id == "coinbase-cash-eur-account"
    assert balance is not None
    assert balance.booked == Decimal("125")
    assert balance.available == Decimal("120")
    assert portfolio.name == "Coinbase Main"
    assert portfolio.positions[0].external_id == "BTC"
    assert portfolio.positions[0].average_buy_in == Decimal("50000")
    assert portfolio.positions[0].current_price == Decimal("60000")
    assert portfolio.trades[0].cash_amount == Decimal("5000")
    assert portfolio.trades[0].fees == Decimal("10")
    assert portfolio.price_history[0].close == Decimal("60000")
    assert portfolio.trades_complete is True


def test_coinbase_marks_non_eur_trade_ledger_incomplete() -> None:
    class UsdFillClient(FakeCoinbaseClient):
        def get_fills(self, **_kwargs):
            return {
                "fills": [
                    {
                        "entry_id": "fill-usd",
                        "trade_time": "2026-09-01T10:00:00Z",
                        "product_id": "BTC-USD",
                        "side": "BUY",
                        "size": "0.1",
                        "size_in_quote": "5000",
                    }
                ],
                "cursor": "",
            }

    portfolio = CoinbaseAdapter(
        {"api_key": "key", "api_secret": "private"}, client=UsdFillClient()
    ).fetch_portfolios()[0]

    assert portfolio.trades == []
    assert portfolio.trades_complete is False
