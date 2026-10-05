import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app.api import banks


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "items": [
                {
                    "blz": "12345678",
                    "bic": "TESTDEFFXXX",
                    "name": "Example Bank",
                    "location": "Example City",
                    "pinTanAddress": "https://bank.example/fints30",
                    "pinTanVersion": "300: FinTS 3.0",
                }
            ],
            "count": 1,
        }


def test_search_banks_proxies_internal_gateway(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 5.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str, *, params: dict) -> _Response:
            assert url == "http://fints-gateway:8082/banks"
            assert params == {"query": "Example", "limit": 5}
            return _Response()

    monkeypatch.setattr(banks.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(banks.search_banks(query="Example", limit=5))

    assert result["count"] == 1
    assert result["items"][0]["blz"] == "12345678"


def test_search_banks_maps_gateway_failure_to_service_unavailable(monkeypatch) -> None:
    class OfflineClient:
        def __init__(self, *, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str, *, params: dict):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(banks.httpx, "AsyncClient", OfflineClient)

    with pytest.raises(HTTPException) as error:
        asyncio.run(banks.search_banks(query="Example", limit=5))

    assert error.value.status_code == 503
