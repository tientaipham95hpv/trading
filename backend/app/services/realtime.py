"""Shared realtime fan-out for web and native clients."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

PayloadProducer = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ChannelSchedule:
    producer: PayloadProducer
    interval: float


class RealtimeBroadcaster:
    def __init__(self) -> None:
        self._schedules: dict[str, ChannelSchedule] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._lock = asyncio.Lock()
        self._anti_stale_task: asyncio.Task[None] | None = None

    def register(self, channel: str, producer: PayloadProducer, interval: float) -> None:
        self._schedules[channel] = ChannelSchedule(producer, interval)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._tasks = [
            asyncio.create_task(self._run(channel, schedule), name=f"realtime:{channel}")
            for channel, schedule in self._schedules.items()
        ]
        self._anti_stale_task = asyncio.create_task(self._run_anti_stale(), name="realtime:loopAntiStale")

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._anti_stale_task is not None:
            self._anti_stale_task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._anti_stale_task is not None:
            await asyncio.gather(self._anti_stale_task, return_exceptions=True)
        self._anti_stale_task = None
        self._tasks = []
        self._started = False
        async with self._lock:
            self._subscribers.clear()

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            queues = tuple(self._subscribers.get(channel, ()))
        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def subscribe(self, channel: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
        async with self._lock:
            self._subscribers[channel].add(queue)
        schedule = self._schedules.get(channel)
        if schedule is not None:
            try:
                queue.put_nowait(await schedule.producer())
            except Exception as exc:  # noqa: BLE001 - isolate producer failures per client
                queue.put_nowait({"channel": channel, "error": str(exc)})
        return queue

    async def unsubscribe(self, channel: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.get(channel, set()).discard(queue)

    async def _run_anti_stale(self) -> None:
        """Keep a visible stale marker when exchange/user-stream data stops."""
        while True:
            await asyncio.sleep(2.0)
            await self.publish("exchange", {"channel": "exchange", "event": "loopAntiStale"})

    async def _run(self, channel: str, schedule: ChannelSchedule) -> None:
        while True:
            try:
                await self.publish(channel, await schedule.producer())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep scheduled channels alive
                await self.publish(channel, {"channel": channel, "error": str(exc)})
            await asyncio.sleep(schedule.interval)
