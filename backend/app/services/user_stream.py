import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import websockets

from app.domain.models import NotificationEvent, TradingMode
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
        self._started_at: datetime | None = None
        self._history_reconciled_lifecycles: set[str] = set()

    def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self._started_at = datetime.now(UTC)
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
                snapshot = await self._reconcile_after_connect(adapter)
                await self._reconcile_lifecycle_history_safely(adapter, snapshot)
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
            maintenance_task = asyncio.create_task(self._maintenance_loop(adapter))
            try:
                async for raw in websocket:
                    event = json.loads(raw)
                    await self._handle_event(adapter, event)
            finally:
                maintenance_task.cancel()
                try:
                    await maintenance_task
                except asyncio.CancelledError:
                    pass

    async def _reconcile_after_connect(self, adapter: Any) -> Any:
        """Reconnect cannot prove that no account events were missed."""
        # DEMO/LIVE positions are authoritative on Binance. ExecutionService is
        # in-memory, so recover positions proven to be bot-managed before the
        # symbol reconciliation performed after a process restart.
        initial_snapshot = await adapter.snapshot()
        self._restore_managed_positions(initial_snapshot)
        exchange_symbols = {
            position.symbol for position in initial_snapshot.positions if abs(position.quantity) > 0
        }
        pruned = self.state.execution.prune_positions_not_on_exchange(exchange_symbols)
        if pruned:
            await self.state.storage.log(
                "Đóng vị thế local không còn trên Binance",
                {"mode": self.state.trading_mode.value, "symbols": pruned},
                level="WARNING",
            )
        local_positions = (
            [position.model_dump(mode="json") for position in self.state.execution.open_positions()]
            if hasattr(self.state, "execution")
            else []
        )
        snapshot = await adapter.reconcile(local_positions)
        await adapter.remove_duplicate_stop_losses(snapshot)
        repaired = await adapter.repair_missing_stop_losses(snapshot)
        if repaired:
            snapshot = await adapter.snapshot()
        unprotected = set(adapter.unprotected_bot_positions(snapshot))
        if unprotected:
            closed = await adapter.close_unprotected_bot_positions(snapshot, set(unprotected))
            if closed:
                await self.state.storage.log(
                    "Đã đóng vị thế bot thiếu Stop Loss sau reconnect",
                    {"mode": self.state.trading_mode.value, "actions": closed},
                    level="CRITICAL",
                )
                snapshot = await adapter.snapshot()
                unprotected = set(adapter.unprotected_bot_positions(snapshot))
        if snapshot.safe_mode or unprotected:
            reason = snapshot.safe_mode_reason or (
                f"Position không có SL: {', '.join(sorted(unprotected))}"
            )
            self.state.enter_safe_mode(reason)
            raise ExchangeError(reason)
        return snapshot

    def _restore_managed_positions(self, snapshot: Any) -> None:
        from uuid import uuid4

        from app.domain.models import PaperPosition, Side

        existing = {position.symbol for position in self.state.execution.open_positions()}
        for position in snapshot.positions:
            if position.symbol in existing:
                continue
            orders = [order for order in snapshot.orders if order.symbol == position.symbol]
            managed = [
                order
                for order in orders
                if order.client_order_id.startswith(("a-demo-", "a-live-", "demo-", "live-"))
            ]
            stops = [
                order
                for order in managed
                if "STOP" in order.order_type
                and "TAKE_PROFIT" not in order.order_type
                and order.stop_price
            ]
            # Never adopt a manual/foreign or unprotected exchange position.
            if not managed or not stops:
                continue
            take_profits = sorted(
                {
                    float(order.stop_price)
                    for order in managed
                    if "TAKE_PROFIT" in order.order_type and order.stop_price
                },
                reverse=position.side == "SHORT",
            )
            self.state.execution.positions.append(
                PaperPosition(
                    id=f"recovered-{position.symbol}-{uuid4()}",
                    symbol=position.symbol,
                    side=Side.LONG if position.side == "LONG" else Side.SHORT,
                    quantity=position.quantity,
                    remaining_quantity=position.quantity,
                    entry_price=position.entry_price,
                    stop_loss=float(stops[0].stop_price),
                    take_profits=take_profits,
                )
            )
            existing.add(position.symbol)

    async def _maintenance_loop(self, adapter: Any) -> None:
        """Keep the authoritative snapshot fresh even when the stream is quiet."""
        keepalive_at = datetime.now(UTC)
        while True:
            await asyncio.sleep(60)
            snapshot = await self._reconcile_after_connect(adapter)
            await self._reconcile_lifecycle_history_safely(adapter, snapshot)
            if (datetime.now(UTC) - keepalive_at).total_seconds() >= 25 * 60:
                await adapter.keepalive_user_stream()
                keepalive_at = datetime.now(UTC)
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
                    recorded = await recorder(lifecycle_fact)
                    if recorded and lifecycle_fact.get("event_type") in {
                        "PARTIAL_CLOSE",
                        "CLOSE_FILL",
                    }:
                        await self._log_lifecycle_fill(lifecycle_fact)
                        await self._notify_lifecycle(lifecycle_fact)
                    if (
                        recorded
                        and lifecycle_fact.get("event_type") == "ENTRY_FILL"
                        and lifecycle_fact.get("order_status") == "FILLED"
                    ):
                        task = asyncio.create_task(
                            self.state.auto_trader.repair_lifecycle_open_from_entry_fill(
                                adapter, lifecycle_fact
                            )
                        )
                        task.add_done_callback(self._background_task_done)
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

    async def _reconcile_lifecycle_history_safely(self, adapter: Any, snapshot: Any) -> None:
        """Recover algo SL/TP fills that Binance did not publish on the user stream."""
        try:
            await self._reconcile_lifecycle_history(adapter, snapshot)
        except Exception as exc:  # noqa: BLE001 - audit recovery must not drop the live stream
            await self.state.storage.log(
                "Lifecycle fill reconciliation deferred",
                {"mode": self.state.trading_mode.value, "error": str(exc)},
                level="WARNING",
            )

    async def _reconcile_lifecycle_history(self, adapter: Any, snapshot: Any) -> None:
        reader = getattr(self.state.storage, "lifecycle_open_events_since", None)
        recorder = getattr(self.state.storage, "save_lifecycle_analytics_event", None)
        if not callable(reader) or not callable(recorder):
            return
        opens = await reader(
            mode=self.state.trading_mode.value,
            since=datetime.now(UTC) - timedelta(days=30),
            limit=100,
        )
        open_symbols = {
            position.symbol for position in snapshot.positions if abs(position.quantity) > 0
        }
        by_symbol: dict[str, list[dict[str, object]]] = {}
        for item in opens:
            lifecycle_id = str(item.get("lifecycle_id") or "")
            symbol = str(item.get("symbol") or "").upper()
            if (
                not lifecycle_id
                or not symbol
                or lifecycle_id in self._history_reconciled_lifecycles
            ):
                continue
            by_symbol.setdefault(symbol, []).append(item)

        for symbol, symbol_opens in by_symbol.items():
            trades = await adapter.trade_history(symbol, limit=1000)
            for trade in trades:
                fact = _history_lifecycle_fact(self.state.trading_mode, trade, symbol_opens)
                if fact is None:
                    continue
                recorded = await recorder(fact)
                event_at = datetime.fromisoformat(str(fact["event_at"]))
                is_close = fact.get("event_type") in {"PARTIAL_CLOSE", "CLOSE_FILL"}
                if recorded and is_close:
                    await self._log_lifecycle_fill(fact)
                if (
                    recorded
                    and is_close
                    and self._started_at is not None
                    and event_at >= self._started_at
                ):
                    await self._notify_lifecycle(fact)
            settled_opens = (
                symbol_opens
                if symbol not in open_symbols
                else sorted(symbol_opens, key=_fact_time)[:-1]
            )
            self._history_reconciled_lifecycles.update(
                str(item.get("lifecycle_id") or "") for item in settled_opens
            )

    async def _log_lifecycle_fill(self, fact: dict[str, object]) -> None:
        await self.state.storage.log(
            "Lifecycle close fill recorded",
            {
                "mode": fact.get("mode"),
                "lifecycle_id": fact.get("lifecycle_id"),
                "symbol": fact.get("symbol"),
                "reason": fact.get("reason"),
                "quantity": fact.get("last_fill_quantity"),
                "price": fact.get("last_fill_price"),
                "realized_pnl": fact.get("realized_pnl"),
                "source": fact.get("source"),
            },
            level="INFO",
        )

    async def _notify_lifecycle(self, fact: dict[str, object]) -> None:
        notifications = getattr(self.state, "notifications", None)
        if notifications is None:
            return
        reason = str(fact.get("reason") or "MARKET_CLOSE")
        event = (
            NotificationEvent.TP
            if reason == "TAKE_PROFIT"
            else NotificationEvent.SL
            if reason == "STOP_LOSS"
            else NotificationEvent.POSITION_CLOSE
        )
        title = {
            NotificationEvent.TP: "Chốt lời đã khớp",
            NotificationEvent.SL: "Stop Loss đã khớp",
            NotificationEvent.POSITION_CLOSE: "Đóng vị thế đã khớp",
        }[event]
        await notifications.alert(
            event,
            title=title,
            body=f"{fact.get('symbol')} {reason}",
            data={
                "mode": fact.get("mode"),
                "symbol": fact.get("symbol"),
                "reason": reason,
                "quantity": fact.get("last_fill_quantity"),
                "last_fill_price": fact.get("last_fill_price"),
                "realized_pnl": fact.get("realized_pnl"),
                "client_order_id": fact.get("client_order_id"),
            },
        )

    @staticmethod
    def _background_task_done(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

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
    if status not in {"FILLED", "PARTIALLY_FILLED"}:
        return None
    close_markers = ("-tp-", "-sl-", "-be-", "-lock-", "-repair-", "-close")
    is_close = any(marker in client_id for marker in close_markers)
    is_managed_entry = client_id.startswith(("a-demo-", "a-live-")) and not is_close
    if not is_close and not is_managed_entry:
        return None
    event_time = int(event.get("E") or order.get("T") or 0)
    event_at = datetime.fromtimestamp(event_time / 1000, UTC) if event_time else datetime.now(UTC)
    event_type = (
        "ENTRY_FILL"
        if is_managed_entry
        else "PARTIAL_CLOSE"
        if status == "PARTIALLY_FILLED"
        else "CLOSE_FILL"
    )
    if is_managed_entry:
        reason = "ENTRY"
    elif "-tp-" in client_id:
        reason = "TAKE_PROFIT"
    elif any(marker in client_id for marker in ("-sl-", "-be-", "-lock-", "-repair-")):
        reason = "STOP_LOSS"
    else:
        reason = "MARKET_CLOSE"
    lifecycle_id = client_id
    for marker in close_markers:
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
        "order_status": status,
        "side": str(order.get("S") or ""),
        "last_fill_quantity": float(order.get("l") or 0),
        "cumulative_quantity": float(order.get("z") or 0),
        "last_fill_price": float(order.get("L") or order.get("ap") or 0),
        "realized_pnl": float(order.get("rp") or 0),
        "commission": float(order.get("n") or 0),
        "commission_asset": order.get("N"),
        "source": "BINANCE_USER_STREAM",
    }


def _history_lifecycle_fact(
    mode: TradingMode,
    trade: dict[str, Any],
    opens: list[dict[str, object]],
) -> dict[str, object] | None:
    """Build the same immutable close fact from Binance's authoritative trade ledger."""
    client_id = str(trade.get("clientOrderId") or "")
    order_type = str(trade.get("conditionalOrderType") or "")
    if not client_id.startswith(("a-demo-", "a-live-", "demo-", "live-")):
        return None
    close_markers = ("-tp-", "-sl-", "-be-", "-lock-", "-repair-", "-close")
    is_entry_client = any(client_id == str(item.get("lifecycle_id") or "") for item in opens)
    if (
        not is_entry_client
        and not order_type
        and not any(marker in client_id for marker in close_markers)
    ):
        return None
    trade_time = int(trade.get("time") or 0)
    event_at = datetime.fromtimestamp(trade_time / 1000, UTC) if trade_time else datetime.now(UTC)
    eligible = [
        item
        for item in opens
        if str(item.get("symbol") or "").upper() == str(trade.get("symbol") or "").upper()
        and _fact_time(item) <= event_at
    ]
    if not eligible:
        return None
    lifecycle_id = ""
    for item in eligible:
        candidate = str(item.get("lifecycle_id") or "")
        if client_id == candidate or any(
            client_id.startswith(f"{candidate}{marker}") for marker in close_markers
        ):
            lifecycle_id = candidate
            break
    if not lifecycle_id:
        # Binance limits client IDs to 36 characters; long repair/lock IDs are
        # suffix-hashed. Time segmentation is the durable fallback association.
        lifecycle_id = str(max(eligible, key=_fact_time).get("lifecycle_id") or "")
    reason = (
        "ENTRY"
        if is_entry_client
        else "TAKE_PROFIT"
        if "TAKE_PROFIT" in order_type or "-tp-" in client_id
        else "STOP_LOSS"
        if "STOP" in order_type
        or any(marker in client_id for marker in ("-sl-", "-be-", "-lock-", "-repair-"))
        else "MARKET_CLOSE"
    )
    order_id = str(trade.get("orderId") or "")
    trade_id = str(trade.get("id") or trade.get("tradeId") or "")
    return {
        "event_key": f"{mode.value}:{order_id}:{trade_id}:FILLED",
        "mode": mode.value,
        "lifecycle_id": lifecycle_id,
        "symbol": str(trade.get("symbol") or ""),
        "event_type": "ENTRY_FILL" if is_entry_client else "CLOSE_FILL",
        "event_at": event_at.isoformat(),
        "reason": reason,
        "client_order_id": client_id,
        "order_id": order_id,
        "trade_id": trade_id,
        "order_status": "FILLED",
        "side": str(trade.get("side") or ""),
        "last_fill_quantity": float(trade.get("qty") or 0),
        "cumulative_quantity": float(trade.get("qty") or 0),
        "last_fill_price": float(trade.get("price") or 0),
        "realized_pnl": float(trade.get("realizedPnl") or 0),
        "commission": float(trade.get("commission") or 0),
        "commission_asset": trade.get("commissionAsset"),
        "source": "BINANCE_TRADE_HISTORY_RECONCILIATION",
    }


def _fact_time(fact: dict[str, object]) -> datetime:
    value = fact.get("event_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
