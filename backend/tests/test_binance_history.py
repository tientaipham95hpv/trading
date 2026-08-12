import httpx
import pytest

from app.services.binance_client import BinanceMarketDataClient


def row(index: int):
    opened = index * 60_000
    return [opened, "100", "102", "99", "101", "10", opened + 59_999, "1000"]


@pytest.mark.asyncio
async def test_historical_klines_paginates_deduplicates_and_orders(monkeypatch):
    calls = []

    async def fake_get(_self, _url, params):
        calls.append(params)
        end = params.get("endTime")
        upper = 1205 if end is None else end // 60_000 + 1
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


def test_historical_validation_rejects_missing_candle():
    client = BinanceMarketDataClient("https://example.test")
    candles = []
    for index in (0, 2):
        item = row(index)
        from app.domain.models import Candle
        candles.append(Candle(open_time=item[0], open=100, high=102, low=99, close=101, volume=10, close_time=item[6], quote_volume=1000))
    with pytest.raises(ValueError, match="Thiếu nến"):
        client._validate_historical_candles(candles, 2)
