from datetime import date
from decimal import Decimal

import httpx

from app.adapters.trading212 import Trading212Adapter


def test_trading212_maps_official_read_only_endpoints() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        assert request.headers["Authorization"].startswith("Basic ")
        if request.url.path == "/api/v0/equity/account/summary":
            return httpx.Response(
                200,
                json={
                    "id": 42,
                    "currency": "EUR",
                    "cash": {
                        "availableToTrade": 100,
                        "inPies": 5,
                        "reservedForOrders": 2,
                    },
                    "investments": {
                        "currentValue": 600,
                        "totalCost": 500,
                        "realizedProfitLoss": 20,
                        "unrealizedProfitLoss": 100,
                    },
                    "totalValue": 707,
                },
            )
        if request.url.path == "/api/v0/equity/positions":
            return httpx.Response(
                200,
                json=[
                    {
                        "quantity": 2,
                        "instrument": {
                            "ticker": "ACME_US_EQ",
                            "isin": "US0000000001",
                            "name": "Acme",
                            "currency": "USD",
                        },
                        "walletImpact": {
                            "currency": "EUR",
                            "currentValue": 240,
                            "totalCost": 200,
                            "unrealizedProfitLoss": 40,
                        },
                    }
                ],
            )
        if request.url.path == "/api/v0/equity/history/orders":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "order": {
                                "side": "BUY",
                                "ticker": "ACME_US_EQ",
                                "instrument": {"ticker": "ACME_US_EQ"},
                            },
                            "fill": {
                                "id": 99,
                                "filledAt": "2026-01-02T10:00:00Z",
                                "quantity": 2,
                                "walletImpact": {
                                    "currency": "EUR",
                                    "netValue": -200,
                                    "taxes": [{"currency": "EUR", "quantity": 1}],
                                },
                            },
                        }
                    ],
                    "nextPagePath": None,
                },
            )
        if request.url.path == "/api/v0/equity/history/transactions":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "reference": "deposit-1",
                            "dateTime": "2026-01-01T09:00:00Z",
                            "amount": 250,
                            "currency": "EUR",
                            "type": "DEPOSIT",
                        }
                    ],
                    "nextPagePath": None,
                },
            )
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = Trading212Adapter(
        {"api_key": "key", "api_secret": "secret"}, client=client
    )

    account = adapter.list_accounts()[0]
    balance = adapter.fetch_balance(account)
    transactions = adapter.fetch_transactions(
        account, date.fromisoformat("2026-01-01"), date.fromisoformat("2026-01-31")
    )
    portfolio = adapter.fetch_portfolios(history_range="max")[0]

    assert account.external_id == "trading212-cash-42"
    assert balance is not None
    assert balance.booked == Decimal("107")
    assert balance.available == Decimal("100")
    assert transactions[0].amount == Decimal("250")
    assert portfolio.positions[0].average_buy_in == Decimal("100")
    assert portfolio.positions[0].current_price == Decimal("120")
    assert portfolio.trades[0].cash_amount == Decimal("200")
    assert portfolio.trades[0].fees == Decimal("1")
    assert portfolio.trades_complete is True
    assert requested.count("/api/v0/equity/account/summary") == 1


def test_trading212_always_uses_live_host() -> None:
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        return httpx.Response(
            200,
            json={
                "id": 1,
                "currency": "EUR",
                "cash": {},
                "investments": {},
                "totalValue": 0,
            },
        )

    adapter = Trading212Adapter(
        {"api_key": "key", "api_secret": "secret", "environment": "demo"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    adapter.list_accounts()

    assert seen_hosts == ["live.trading212.com"]
