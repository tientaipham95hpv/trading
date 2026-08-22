from datetime import UTC, datetime

import httpx
import pytest

from app.domain.models import Candle
from app.services.binance_client import BinanceMarketDataClient


def row(index: int):
    opened = index * 60_000
    return [opened, "100", "102", "99", "101", "10", opened + 59_999, "1000"]


@pytest.mark.asyncio
async def test_historical_klines_paginates_deduplicates_and_orders(monkeypatch):
    calls = []

    async def fake_get(_self, _url, params):
        calls.append(params)
        upper = min(1205, params["endTime"] // 60_000 + 1)
        start = max(0, upper - params["limit"])
        response = httpx.Response(200, json=[row(i) for i in range(start, upper)])
        response.request = httpx.Request("GET", _url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    candles = await BinanceMarketDataClient("https://example.test").historical_klines(
        "BTCUSDT", "1m", 1200
    )
    assert len(calls) == 2
    assert len(candles) == 1200
    assert candles[0].open_time == 5 * 60_000
    assert candles[-1].open_time == 1204 * 60_000
    assert all("endTime" in call for call in calls)


@pytest.mark.asyncio
async def test_historical_klines_excludes_current_open_candle(monkeypatch):
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    current_open = now_ms - now_ms % 60_000

    async def fake_get(_self, _url, params):
        response = httpx.Response(
            200,
            json=[
                row(current_open // 60_000 - 2),
                row(current_open // 60_000 - 1),
                row(current_open // 60_000),
            ],
        )
        response.request = httpx.Request("GET", _url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    candles = await BinanceMarketDataClient("https://example.test").historical_klines(
        "BTCUSDT", "1m", 2
    )
    assert len(candles) == 2
    assert candles[-1].close_time < now_ms
    assert candles[-1].open_time == current_open - 60_000


@pytest.mark.asyncio
async def test_historical_klines_ends_before_current_interval(monkeypatch):
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    current_open = now_ms - now_ms % 60_000
    calls = []

    async def fake_get(_path, *, params, timeout):
        calls.append(params)
        last_index = params["endTime"] // 60_000
        return [row(last_index - 1), row(last_index)]

    client = BinanceMarketDataClient("https://example.test")
    monkeypatch.setattr(client, "_get", fake_get)
    candles = await client.historical_klines("BTCUSDT", "1m", 2)
    assert calls[0]["endTime"] == current_open - 1
    assert len(candles) == 2
    assert candles[-1].open_time == current_open - 60_000


def test_historical_validation_rejects_missing_candle():
    client = BinanceMarketDataClient("https://example.test")
    candles = []
    for index in (0, 2):
        item = row(index)
        candles.append(
            Candle(
                open_time=item[0],
                open=100,
                high=102,
                low=99,
                close=101,
                volume=10,
                close_time=item[6],
                quote_volume=1000,
            )
        )
    with pytest.raises(ValueError, match="Thiếu nến"):
        client._validate_historical_candles(candles, 2)


@pytest.mark.asyncio
async def test_historical_klines_days_uses_forward_bounded_pages(monkeypatch):
    interval_ms = 14_400_000
    calls = []

    async def fake_get(_path, *, params=None, timeout=0):
        calls.append(params)
        start = params["startTime"]
        count = params["limit"]
        return [
            [
                start + i * interval_ms,
                "1",
                "2",
                "0.5",
                "1.5",
                "10",
                start + (i + 1) * interval_ms - 1,
                "15",
            ]
            for i in range(count)
        ]

    client = BinanceMarketDataClient("https://example.test")
    monkeypatch.setattr(client, "_get", fake_get)
    candles = await client.historical_klines_days("BTCUSDT", "4h", 30)

    assert len(candles) == 180
    assert len(calls) == 1
    assert calls[0]["endTime"] > candles[-1].open_time
    assert candles[-1].close_time == calls[0]["endTime"]
