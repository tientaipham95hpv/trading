import asyncio

import pytest

from app.services.analytics_history import AnalyticsHistoryCache, AnalyticsHistorySnapshot


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_fetch() -> None:
    cache = AnalyticsHistoryCache()
    calls = 0
    release = asyncio.Event()

    async def fetch() -> AnalyticsHistorySnapshot:
        nonlocal calls
        calls += 1
        await release.wait()
        return AnalyticsHistorySnapshot(income=[{"income": "1"}], trades=[])

    requests = [asyncio.create_task(cache.get("demo", fetch)) for _ in range(5)]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*requests)

    assert calls == 1
    assert all(result.snapshot.income == [{"income": "1"}] for result in results)


@pytest.mark.asyncio
async def test_cache_refreshes_after_ttl_expiry() -> None:
    now = 0.0
    calls = 0
    cache = AnalyticsHistoryCache(ttl_seconds=5, stale_seconds=30, clock=lambda: now)

    async def fetch() -> AnalyticsHistorySnapshot:
        nonlocal calls
        calls += 1
        return AnalyticsHistorySnapshot(income=[{"call": calls}], trades=[])

    first = await cache.get("demo", fetch)
    now = 4.9
    fresh = await cache.get("demo", fetch)
    now = 5.0
    refreshed = await cache.get("demo", fetch)

    assert calls == 2
    assert first.snapshot.income == fresh.snapshot.income == [{"call": 1}]
    assert refreshed.snapshot.income == [{"call": 2}]


@pytest.mark.asyncio
async def test_refresh_failure_returns_stale_snapshot() -> None:
    now = 0.0
    cache = AnalyticsHistoryCache(ttl_seconds=5, stale_seconds=30, clock=lambda: now)

    async def fetch() -> AnalyticsHistorySnapshot:
        return AnalyticsHistorySnapshot(income=[{"income": "1"}], trades=[])

    await cache.get("demo", fetch)
    now = 6.0

    async def fail() -> AnalyticsHistorySnapshot:
        raise TimeoutError("history timeout")

    result = await cache.get("demo", fail)

    assert result.degraded is True
    assert result.reason == "history timeout"
    assert result.snapshot.income == [{"income": "1"}]


@pytest.mark.asyncio
async def test_refresh_failure_without_stale_snapshot_is_raised() -> None:
    cache = AnalyticsHistoryCache()

    async def fail() -> AnalyticsHistorySnapshot:
        raise TimeoutError("history timeout")

    with pytest.raises(TimeoutError, match="history timeout"):
        await cache.get("demo", fail)


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_or_retain_shared_fetch() -> None:
    cache = AnalyticsHistoryCache()
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch() -> AnalyticsHistorySnapshot:
        started.set()
        await release.wait()
        return AnalyticsHistorySnapshot(income=[{"income": "1"}], trades=[])

    waiter = asyncio.create_task(cache.get("demo", fetch))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert cache._inflight == {}
    cached = await cache.get("demo", fetch)
    assert cached.snapshot.income == [{"income": "1"}]


@pytest.mark.asyncio
async def test_route_history_fetch_is_coalesced_and_fetches_each_symbol_once(monkeypatch) -> None:
    from app.api import routes
    from app.domain.models import TradingMode

    class Adapter:
        def __init__(self) -> None:
            self.income_calls: list[str | None] = []
            self.trade_calls: list[str] = []

        async def income_history(
            self,
            *,
            income_type: str | None = None,
            limit: int = 500,
            start_time: int | None = None,
        ) -> list[dict[str, object]]:
            self.income_calls.append(income_type)
            await asyncio.sleep(0)
            if income_type == "REALIZED_PNL":
                return [
                    {"symbol": "BTCUSDT", "incomeType": income_type},
                    {"symbol": "ETHUSDT", "incomeType": income_type},
                    {"symbol": "BTCUSDT", "incomeType": income_type},
                ]
            return [{"symbol": "BTCUSDT", "incomeType": income_type}]

        async def trade_history(self, symbol: str, *, limit: int = 500) -> list[dict[str, object]]:
            self.trade_calls.append(symbol)
            await asyncio.sleep(0)
            return [{"symbol": symbol}]

    adapter = Adapter()
    monkeypatch.setattr(routes.state, "trading_mode", TradingMode.DEMO)
    monkeypatch.setattr(routes.state, "analytics_history", AnalyticsHistoryCache())

    first, second = await asyncio.gather(
        routes._analytics_history(adapter),
        routes._analytics_history(adapter),
    )

    assert sorted(adapter.income_calls, key=str) == ["COMMISSION", "FUNDING_FEE", "REALIZED_PNL"]
    assert sorted(adapter.trade_calls) == ["BTCUSDT", "ETHUSDT"]
    assert first.snapshot == second.snapshot
