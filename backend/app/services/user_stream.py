import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import websockets

from app.domain.models import TradingMode
from app.services.exchange import ExchangeCredentialsError, ExchangeError


class UserStreamWatchdog:
    def __init__(self, app_state: Any, *, reconnect_threshold: int = 5) -> None:
        self.state = app_state
        self.reconnect_threshold = reconnect_threshold
        self.task: asyncio.Task[None] | None = None
        self.running = False
        self.connected = False
        self.last_connected_at: datetime | None = None
        self.last_event_at: datetime | None = None
        self.last_error: str | None = None
        self.reconnects = 0
        self.events = 0
        self._consecutive_failures = 0

    def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def snapshot(self) -> dict[str, object]:
        return {
            "running": self.running and self.task is not None and not self.task.done(),
            "connected": self.connected,
            "last_connected_at": self.last_connected_at.isoformat()
            if self.last_connected_at
            else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "last_error": self.last_error,
            "reconnects": self.reconnects,
            "events": self.events,
            "consecutive_failures": self._consecutive_failures,
        }

    async def _run(self) -> None:
        await self.state.storage.log("User-stream watchdog started", {})
        while self.running:
            if self.state.trading_mode == TradingMode.PAPER:
                self.connected = False
                await asyncio.sleep(10)
                continue

            adapter = (
                self.state.live_exchange
                if self.state.trading_mode == TradingMode.LIVE
                else self.state.demo_exchange
            )
            try:
                url = await adapter.open_user_stream()
                self.connected = True
                self.last_connected_at = datetime.now(UTC)
                self.last_error = None
                self._consecutive_failures = 0
                await self.state.storage.log(
                    "User-stream connected",
                    {"mode": self.state.trading_mode.value},
                    level="INFO",
                )
                await self._consume(url, adapter)
            except asyncio.CancelledError:
                raise
            except (
                ExchangeCredentialsError,
                ExchangeError,
                OSError,
                websockets.WebSocketException,
            ) as exc:
                await self._handle_failure(exc)
            except Exception as exc:  # noqa: BLE001 - background stream must keep retrying
                await self._handle_failure(exc)

            self.connected = False
            if self.running:
                await asyncio.sleep(min(5 * max(self._consecutive_failures, 1), 60))

    async def _consume(self, url: str, adapter: Any) -> None:
        async with websockets.connect(
            url, ping_interval=20, ping_timeout=20, close_timeout=5
        ) as websocket:
            keepalive_task = asyncio.create_task(self._keepalive_loop(adapter))
            try:
                async for raw in websocket:
                    event = json.loads(raw)
                    await self._handle_event(adapter, event)
            finally:
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass

    async def _keepalive_loop(self, adapter: Any) -> None:
        while True:
            await asyncio.sleep(25 * 60)
            await adapter.keepalive_user_stream()
            await self.state.storage.log(
                "User-stream listenKey keepalive",
                {"mode": self.state.trading_mode.value},
                level="INFO",
            )

    async def _handle_event(self, adapter: Any, event: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        self.events += 1
        self.last_event_at = now
        adapter.mark_user_stream_event(now)
        event_type = str(event.get("e") or "")
        if event_type in {"ACCOUNT_UPDATE", "ORDER_TRADE_UPDATE"}:
            lifecycle_actions: list[dict[str, object]] = []
            if event_type == "ORDER_TRADE_UPDATE" and hasattr(adapter, "handle_user_stream_event"):
                lifecycle_actions = await adapter.handle_user_stream_event(event)
                lifecycle_fact = _lifecycle_fact(self.state.trading_mode, event)
                recorder = getattr(self.state.storage, "save_lifecycle_analytics_event", None)
                if lifecycle_fact is not None and recorder is not None:
                    await recorder(lifecycle_fact)
                for index, action in enumerate(lifecycle_actions):
                    if recorder is None:
                        break
                    await recorder(
                        _stop_management_fact(self.state.trading_mode, event, action, index=index)
                    )
            await self.state.storage.log(
                "User-stream event",
                {
                    "mode": self.state.trading_mode.value,
                    "event": event_type,
                    "symbol": _event_symbol(event),
                    "order_status": _event_order_status(event),
                    "lifecycle_actions": lifecycle_actions,
                },
                level="INFO",
            )

    async def _handle_failure(self, exc: Exception) -> None:
        self.connected = False
        self.reconnects += 1
        self._consecutive_failures += 1
        self.last_error = str(exc)
        await self.state.storage.log(
            "User-stream reconnect needed",
            {
                "mode": self.state.trading_mode.value,
                "error": str(exc),
                "consecutive_failures": self._consecutive_failures,
            },
            level="WARNING",
        )
        if (
            self._consecutive_failures >= self.reconnect_threshold
            and await self._has_exchange_exposure()
        ):
            reason = (
                f"SAFE_MODE: user stream reconnect lỗi {self._consecutive_failures} lần liên tiếp"
            )
            self.state.enter_safe_mode(reason)
            await self.state.storage.log(
                "User-stream watchdog entered safe mode",
                {"mode": self.state.trading_mode.value, "reason": reason},
                level="CRITICAL",
            )

    async def _has_exchange_exposure(self) -> bool:
        if self.state.trading_mode == TradingMode.PAPER:
            return False
        adapter = (
            self.state.live_exchange
            if self.state.trading_mode == TradingMode.LIVE
            else self.state.demo_exchange
        )
        try:
            snapshot = await adapter.snapshot()
        except (ExchangeCredentialsError, ExchangeError):
            return True
        return bool(snapshot.positions or snapshot.orders)


def _lifecycle_fact(mode: TradingMode, event: dict[str, Any]) -> dict[str, object] | None:
    order = event.get("o")
    if not isinstance(order, dict):
        return None
    client_id = str(order.get("c") or "")
    status = str(order.get("X") or "")
    if status not in {"FILLED", "PARTIALLY_FILLED"} or not any(
        marker in client_id for marker in ("-tp-", "-sl-", "-be-", "-lock-", "-repair-", "-close")
    ):
        return None
    event_time = int(event.get("E") or order.get("T") or 0)
    event_at = datetime.fromtimestamp(event_time / 1000, UTC) if event_time else datetime.now(UTC)
    event_type = "PARTIAL_CLOSE" if status == "PARTIALLY_FILLED" else "CLOSE_FILL"
    if "-tp-" in client_id:
        reason = "TAKE_PROFIT"
    elif any(marker in client_id for marker in ("-sl-", "-be-", "-lock-", "-repair-")):
        reason = "STOP_LOSS"
    else:
        reason = "MARKET_CLOSE"
    lifecycle_id = client_id
    for marker in ("-tp-", "-sl-", "-be-", "-lock-", "-repair-", "-close"):
        lifecycle_id = lifecycle_id.split(marker)[0]
    order_id = str(order.get("i") or "")
    trade_id = str(order.get("t") or "")
    return {
        "event_key": f"{mode.value}:{order_id}:{trade_id}:{status}",
        "mode": mode.value,
        "lifecycle_id": lifecycle_id,
        "symbol": str(order.get("s") or ""),
        "event_type": event_type,
        "event_at": event_at.isoformat(),
        "reason": reason,
        "client_order_id": client_id,
        "order_id": order_id,
        "trade_id": trade_id,
        "side": str(order.get("S") or ""),
        "last_fill_quantity": float(order.get("l") or 0),
        "cumulative_quantity": float(order.get("z") or 0),
        "last_fill_price": float(order.get("L") or order.get("ap") or 0),
        "realized_pnl": float(order.get("rp") or 0),
        "commission": float(order.get("n") or 0),
        "commission_asset": order.get("N"),
        "source": "BINANCE_USER_STREAM",
    }


def _stop_management_fact(
    mode: TradingMode,
    event: dict[str, Any],
    action: dict[str, object],
    *,
    index: int,
) -> dict[str, object]:
    now = datetime.now(UTC)
    order = event.get("o") if isinstance(event.get("o"), dict) else {}
    lifecycle_id = str(action.get("group_id") or "UNKNOWN")
    client_id = str(action.get("client_order_id") or "")
    return {
        "event_key": f"{mode.value}:{lifecycle_id}:STOP:{client_id}:{index}",
        "mode": mode.value,
        "lifecycle_id": lifecycle_id,
        "symbol": str(action.get("symbol") or order.get("s") or ""),
        "event_type": "STOP_UPDATED",
        "event_at": now.isoformat(),
        "old_stop": action.get("old_stop"),
        "new_stop": action.get("new_stop"),
        "remaining_take_profits": action.get("remaining_take_profits"),
        "lifecycle_state": action.get("lifecycle_state"),
        "source": "STOP_MANAGER",
    }


def _event_symbol(event: dict[str, Any]) -> str | None:
    order = event.get("o")
    if isinstance(order, dict):
        symbol = order.get("s")
        return str(symbol) if symbol else None
    return None


def _event_order_status(event: dict[str, Any]) -> str | None:
    order = event.get("o")
    if isinstance(order, dict):
        status = order.get("X")
        return str(status) if status else None
    return None
