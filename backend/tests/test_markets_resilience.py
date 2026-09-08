from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api import routes


class MarketItem:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def model_dump(self) -> dict[str, str]:
        return {"symbol": self.symbol}


class RecordingStorage:
    def __init__(self) -> None:
        self.logs: list[tuple[str, dict[str, object], str]] = []

    async def log(self, message: str, payload: dict[str, object], *, level: str) -> None:
        self.logs.append((message, payload, level))


def api_app() -> FastAPI:
    app = FastAPI()
    app.include_router(routes.router)
    return app


@pytest.mark.asyncio
async def test_markets_returns_fresh_result(monkeypatch) -> None:
    class Scanner:
        def __init__(self) -> None:
            self.last_markets: list[MarketItem] = []
            self.last_markets_at = None

        async def scan_usdm_pairs(self) -> list[MarketItem]:
            return [MarketItem("BTCUSDT")]

    state = SimpleNamespace(
        settings=SimpleNamespace(app_env="local", api_auth_token=""),
        scanner=Scanner(),
        storage=RecordingStorage(),
        trading_mode=SimpleNamespace(value="DEMO"),
    )
    monkeypatch.setattr(routes, "state", state)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_app()), base_url="http://test"
    ) as client:
        response = await client.get("/api/markets")

    assert response.status_code == 200
    assert response.json() == {"items": [{"symbol": "BTCUSDT"}], "degraded": False}
    assert state.storage.logs == []


@pytest.mark.asyncio
async def test_markets_uses_last_known_good_on_timeout(monkeypatch) -> None:
    cached_at = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)

    class Scanner:
        def __init__(self) -> None:
            self.last_markets = [MarketItem("ETHUSDT")]
            self.last_markets_at = cached_at

        async def scan_usdm_pairs(self) -> list[MarketItem]:
            raise TimeoutError

    state = SimpleNamespace(
        settings=SimpleNamespace(app_env="local", api_auth_token=""),
        scanner=Scanner(),
        storage=RecordingStorage(),
        trading_mode=SimpleNamespace(value="DEMO"),
    )
    monkeypatch.setattr(routes, "state", state)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_app()), base_url="http://test"
    ) as client:
        response = await client.get("/api/markets")

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"symbol": "ETHUSDT"}],
        "degraded": True,
        "source": "LAST_KNOWN_GOOD",
        "cached_at": "2026-09-07T18:00:00+00:00",
        "reason": "Dữ liệu thị trường tạm thời không khả dụng",
    }
    assert state.storage.logs[0][1] == {
        "mode": "DEMO",
        "cache_available": True,
        "error_type": "TimeoutError",
    }


@pytest.mark.asyncio
async def test_markets_returns_safe_empty_fallback_on_dns_failure(monkeypatch) -> None:
    class Scanner:
        def __init__(self) -> None:
            self.last_markets: list[MarketItem] = []
            self.last_markets_at = None

        async def scan_usdm_pairs(self) -> list[MarketItem]:
            raise httpx.ConnectError("temporary DNS failure")

    monkeypatch.setattr(
        routes,
        "state",
        SimpleNamespace(
            settings=SimpleNamespace(app_env="local", api_auth_token=""),
            scanner=Scanner(),
            storage=RecordingStorage(),
            trading_mode=SimpleNamespace(value="DEMO"),
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_app()), base_url="http://test"
    ) as client:
        response = await client.get("/api/markets")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["source"] == "SAFE_EMPTY"
    assert response.json()["degraded"] is True
    assert "DNS" not in response.json()["reason"]
