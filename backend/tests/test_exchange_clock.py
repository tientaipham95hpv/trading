import pytest

from app.domain.models import TradingMode
from app.services.exchange import BinanceFuturesAdapter, ExchangeError


@pytest.mark.asyncio
async def test_signed_resyncs_and_retries_only_timestamp_rejection(monkeypatch):
    adapter = BinanceFuturesAdapter(api_key="k", api_secret="s", mode=TradingMode.DEMO)
    calls, syncs = [], []

    async def sync(*, force=False):
        syncs.append(force)

    async def request(method, path, *, params=None, signed=False):
        calls.append((method, path))
        if len(calls) == 1:
            raise ExchangeError('Binance 400: {"code":-1021,"msg":"Timestamp outside recvWindow"}')
        return {"ok": True}

    monkeypatch.setattr(adapter, "_sync_time_if_needed", sync)
    monkeypatch.setattr(adapter, "_request", request)
    assert await adapter._signed("GET", "/fapi/v1/userTrades", {}) == {"ok": True}
    assert syncs == [False, True]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_signed_does_not_retry_non_timestamp_error(monkeypatch):
    adapter = BinanceFuturesAdapter(api_key="k", api_secret="s", mode=TradingMode.DEMO)
    calls = 0

    async def sync(*, force=False):
        return None

    async def request(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise ExchangeError("Binance 400: insufficient margin")

    monkeypatch.setattr(adapter, "_sync_time_if_needed", sync)
    monkeypatch.setattr(adapter, "_request", request)
    with pytest.raises(ExchangeError):
        await adapter._signed("POST", "/fapi/v1/order", {})
    assert calls == 1
