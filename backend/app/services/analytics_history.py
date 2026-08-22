import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalyticsHistorySnapshot:
    income: list[dict[str, object]]
    trades: list[dict[str, object]]


@dataclass(frozen=True)
class AnalyticsHistoryResult:
    snapshot: AnalyticsHistorySnapshot
    degraded: bool = False
    reason: str | None = None


@dataclass
class _Entry:
    snapshot: AnalyticsHistorySnapshot
    fetched_at: float


class AnalyticsHistoryCache:
    """Short-lived exchange history cache with per-key request coalescing."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 15.0,
        stale_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.stale_seconds = stale_seconds
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._inflight: dict[str, asyncio.Task[AnalyticsHistorySnapshot]] = {}
        self._lock = asyncio.Lock()

    async def get(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[AnalyticsHistorySnapshot]],
    ) -> AnalyticsHistoryResult:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and now - entry.fetched_at < self.ttl_seconds:
            return AnalyticsHistoryResult(entry.snapshot)

        async with self._lock:
            now = self._clock()
            entry = self._entries.get(key)
            if entry is not None and now - entry.fetched_at < self.ttl_seconds:
                return AnalyticsHistoryResult(entry.snapshot)
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._fetch_and_store(key, fetcher))
                self._inflight[key] = task

        try:
            snapshot = await asyncio.shield(task)
        except Exception as exc:
            entry = self._entries.get(key)
            if entry is not None and self._clock() - entry.fetched_at < self.stale_seconds:
                return AnalyticsHistoryResult(entry.snapshot, degraded=True, reason=str(exc))
            raise
        else:
            return AnalyticsHistoryResult(snapshot)

    async def _fetch_and_store(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[AnalyticsHistorySnapshot]],
    ) -> AnalyticsHistorySnapshot:
        task = asyncio.current_task()
        try:
            snapshot = await fetcher()
            self._entries[key] = _Entry(snapshot=snapshot, fetched_at=self._clock())
            return snapshot
        finally:
            async with self._lock:
                if self._inflight.get(key) is task:
                    self._inflight.pop(key, None)
