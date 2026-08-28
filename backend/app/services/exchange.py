import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from app.domain.models import (
    ExchangeBalance,
    ExchangeConnectionState,
    ExchangeExecutionResult,
    ExchangeOrder,
    ExchangePosition,
    ExchangePositionLifecycle,
    ExchangePositionLifecycleState,
    ExchangeSnapshot,
    OrderPlan,
    OrderType,
    Side,
    TradingMode,
)
from app.services.binance_gateway import (
    BinanceGateway,
    CircuitOpenError,
    RateLimitBudgetExceeded,
    gateway_for,
)


class ExchangeError(Exception):
    pass


class ExchangeCredentialsError(ExchangeError):
    pass


class StopLossProtectionError(ExchangeError):
    pass


class ExchangeAdapter(ABC):
    @abstractmethod
    async def submit_order_plan(self, plan: OrderPlan) -> ExchangeExecutionResult:
        raise NotImplementedError

    @abstractmethod
    async def snapshot(self) -> ExchangeSnapshot:
        raise NotImplementedError

    @abstractmethod
    async def reconcile(self, local_positions: list[dict[str, Any]]) -> ExchangeSnapshot:
        raise NotImplementedError

    @abstractmethod
    async def open_user_stream(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def cancel_all_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        raise NotImplementedError

    @abstractmethod
    async def close_all_positions(self) -> list[ExchangeOrder]:
        raise NotImplementedError


class BinanceFuturesAdapter(ExchangeAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = "https://demo-fapi.binance.com",
        stream_url: str = "wss://demo-fstream.binance.com",
        recv_window: int = 5000,
        mode: TradingMode = TradingMode.DEMO,
        gateway: BinanceGateway | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.stream_url = stream_url.rstrip("/")
        self.recv_window = recv_window
        self.mode = mode
        self.gateway = gateway or gateway_for(self.base_url)
        self._submitted_client_ids: set[str] = set()
        self._listen_key: str | None = None
        self.snapshot_cache = ExchangeSnapshot(mode=mode)
        self._symbol_filters: dict[str, dict[str, Decimal]] = {}
        self._submitted_plans_by_symbol: dict[str, OrderPlan] = {}
        self._lifecycles_by_symbol: dict[str, ExchangePositionLifecycle] = {}
        self._time_offset_ms = 0
        self._last_time_sync_ms = 0
        self._stop_repair_attempts: dict[str, int] = {}
        self._stop_management_symbols: set[str] = set()
        self._reconciliation_safe_mode = False

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def submit_order_plan(self, plan: OrderPlan) -> ExchangeExecutionResult:
        self._require_credentials()
        plan = await self._normalize_plan(plan)
        # Binance client ids survive process restarts; the in-memory set does not.
        try:
            existing = await self.query_order(plan.symbol, plan.client_order_id, strict=True)
        except ExchangeError as exc:
            self._enter_safe_mode(
                f"Không xác minh được client order id {plan.client_order_id}: {exc}"
            )
            raise
        if existing:
            return ExchangeExecutionResult(
                accepted=True,
                status=f"{self.mode.value}_DUPLICATE_ACK",
                client_order_id=plan.client_order_id,
                order=self._normalize_order(existing).model_dump(mode="json"),
            )
        if plan.client_order_id in self._submitted_client_ids:
            raise ExchangeError(f"Duplicate client order id: {plan.client_order_id}")
        self._submitted_client_ids.add(plan.client_order_id)
        self._submitted_plans_by_symbol[plan.symbol] = plan
        self._lifecycles_by_symbol[plan.symbol] = ExchangePositionLifecycle(
            symbol=plan.symbol,
            group_id=plan.client_order_id,
            state=ExchangePositionLifecycleState.OPENING,
            side=plan.side.value,
            entry_price=plan.entry_price,
            current_quantity=plan.quantity,
            initial_quantity=plan.quantity,
            remaining_take_profits=len(plan.take_profits),
        )

        await self.change_margin_type(plan.symbol, plan.margin_type.value)
        await self.change_leverage(plan.symbol, plan.leverage)

        entry = await self._place_entry(plan)
        reference_price = await self._post_entry_reference_price(plan, entry)
        filters = await self._filters_for(plan.symbol)
        if not self._stop_loss_is_actionable(
            plan.side,
            plan.stop_loss,
            reference_price=reference_price,
            price_tick=filters["price_tick"],
        ):
            await self._close_position_market(plan)
            return ExchangeExecutionResult(
                accepted=False,
                status=f"{self.mode.value}_SL_INVALID_POSITION_CLOSED",
                client_order_id=plan.client_order_id,
                order=self._normalize_order(entry).model_dump(mode="json"),
            )
        sl_order = await self._ensure_stop_loss(plan)
        if sl_order is None:
            await self._close_position_market(plan)
            alert = (
                "CRITICAL: Không tạo được SL trên LIVE, đã gửi lệnh đóng vị thế"
                if self.mode == TradingMode.LIVE
                else "CRITICAL: Không tạo được SL trên DEMO, đã gửi lệnh đóng vị thế"
            )
            self._enter_safe_mode(alert)
            return ExchangeExecutionResult(
                accepted=False,
                status=f"{self.mode.value}_SL_FAILED_POSITION_CLOSING",
                client_order_id=plan.client_order_id,
                order=self._normalize_order(entry).model_dump(mode="json"),
                critical_alert=alert,
            )

        take_profit_orders = []
        try:
            tp_created = 0
            for index, take_profit in enumerate(plan.take_profits):
                if not self._take_profit_is_actionable(
                    plan.side,
                    take_profit,
                    reference_price=reference_price,
                    price_tick=filters["price_tick"],
                ):
                    continue
                quantity = await self._take_profit_quantity_for_plan(
                    plan, index, len(plan.take_profits)
                )
                is_last = index == len(plan.take_profits) - 1
                if quantity <= 0 and not is_last:
                    continue
                take_profit_orders.append(
                    await self._place_take_profit(
                        plan,
                        take_profit,
                        quantity,
                        index,
                        close_position=quantity <= 0,
                    )
                )
                tp_created += 1
            if tp_created == 0:
                raise ExchangeError("Không tạo được TP hợp lệ sau khi làm tròn quantity")
        except ExchangeError as exc:
            await self.cancel_all_orders(plan.symbol)
            await self._close_position_market(plan)
            alert = f"CRITICAL: Không tạo được TP trên {self.mode.value}, đã hủy order và gửi lệnh đóng vị thế: {exc}"
            return ExchangeExecutionResult(
                accepted=False,
                status=f"{self.mode.value}_TP_FAILED_POSITION_CLOSING",
                client_order_id=plan.client_order_id,
                order=self._normalize_order(entry).model_dump(mode="json"),
                critical_alert=alert,
            )

        # Publish the position and its protective algo orders to the cache as one
        # snapshot. Readers either see the old flat state or the fully protected
        # state, never a transient position without its SL.
        protected_snapshot = await self.snapshot()
        return ExchangeExecutionResult(
            accepted=True,
            status=f"{self.mode.value}_SUBMITTED",
            client_order_id=plan.client_order_id,
            order={
                **self._normalize_order(entry).model_dump(mode="json"),
                "submitted_plan": plan.model_dump(mode="json"),
            },
            positions=[
                position.model_dump(mode="json")
                for position in protected_snapshot.positions
                if position.symbol == plan.symbol
            ],
            fills=[],
            trades=[],
        )

    def submitted_plan(self, symbol: str) -> OrderPlan | None:
        return self._submitted_plans_by_symbol.get(symbol.upper())

    async def close_submitted_plan_fail_closed(self, plan: OrderPlan) -> None:
        """Cancel protection orders and flatten one just-submitted plan."""
        await self.cancel_all_orders(plan.symbol)
        await self._close_position_market(plan)
        await self.snapshot()

    async def snapshot(self) -> ExchangeSnapshot:
        if not self.configured:
            self.snapshot_cache = ExchangeSnapshot(
                mode=self.mode,
                connection=ExchangeConnectionState.DISCONNECTED,
                safe_mode=self.snapshot_cache.safe_mode,
                safe_mode_reason=self._credentials_message(),
            )
            return self.snapshot_cache
        balance = await self.balance()
        orders = await self.open_orders()
        positions = await self.positions()
        lifecycles = self._sync_lifecycles_from_snapshot(positions, orders)
        self.snapshot_cache = ExchangeSnapshot(
            mode=self.mode,
            connection=ExchangeConnectionState.CONNECTED,
            safe_mode=self.snapshot_cache.safe_mode,
            safe_mode_reason=self.snapshot_cache.safe_mode_reason,
            balance=balance,
            orders=orders,
            positions=positions,
            lifecycles=lifecycles,
            snapshot_at=datetime.now(UTC),
            freshness="LIVE",
            last_reconciled_at=self.snapshot_cache.last_reconciled_at,
            last_user_stream_at=self.snapshot_cache.last_user_stream_at,
        )
        return self.snapshot_cache

    async def reconcile(self, local_positions: list[dict[str, Any]]) -> ExchangeSnapshot:
        try:
            snapshot = await self.snapshot()
        except ExchangeError as exc:
            self._enter_safe_mode(f"Reconcile không chắc chắn: {exc}")
            raise
        exchange_symbols = {
            position.symbol for position in snapshot.positions if abs(position.quantity) > 0
        }
        local_symbols = {
            str(position.get("symbol"))
            for position in local_positions
            if position.get("status") == "OPEN"
        }
        mismatch = sorted(exchange_symbols.symmetric_difference(local_symbols))
        if mismatch:
            self._reconciliation_safe_mode = True
            self._enter_safe_mode(f"Mismatch vị thế Binance vs DB: {', '.join(mismatch)}")
            snapshot = self.snapshot_cache
        elif self._reconciliation_safe_mode:
            # Only a prior position mismatch may be cleared automatically.
            # Other safety latches (for example failed SL placement) require
            # an explicit operator reset after verification.
            self._reconciliation_safe_mode = False
            snapshot.safe_mode = False
            snapshot.safe_mode_reason = None
            snapshot.connection = ExchangeConnectionState.CONNECTED
        snapshot.last_reconciled_at = datetime.now(UTC)
        self.snapshot_cache = snapshot
        return snapshot

    def _enter_safe_mode(self, reason: str) -> None:
        self.snapshot_cache.safe_mode = True
        self.snapshot_cache.connection = ExchangeConnectionState.SAFE_MODE
        self.snapshot_cache.safe_mode_reason = reason

    async def open_user_stream(self) -> str:
        self._require_credentials()
        payload = await self._request("POST", "/fapi/v1/listenKey", signed=False)
        listen_key = str(payload["listenKey"])
        self._listen_key = listen_key
        self.snapshot_cache.last_user_stream_at = datetime.now(UTC)
        return f"{self.stream_url}/ws/{listen_key}"

    async def cancel_all_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        self._require_credentials()
        symbols = (
            [symbol] if symbol else sorted({order.symbol for order in await self.open_orders()})
        )
        canceled: list[ExchangeOrder] = []
        for item in symbols:
            payload = await self._signed("DELETE", "/fapi/v1/allOpenOrders", {"symbol": item})
            algo_payload = await self._signed("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": item})
            canceled.append(
                ExchangeOrder(
                    symbol=item,
                    order_id=payload.get("code", ""),
                    client_order_id=f"cancel-all-{item}",
                    side="",
                    order_type="CANCEL_ALL",
                    status=f"{payload.get('msg', 'OK')}; {algo_payload.get('msg', 'OK')}",
                )
            )
        return canceled

    async def close_all_positions(self) -> list[ExchangeOrder]:
        orders: list[ExchangeOrder] = []
        for position in await self.positions():
            plan = OrderPlan(
                client_order_id=_client_order_id(
                    self.mode.value.lower(), position.symbol, "close", int(time.time() * 1000)
                ),
                symbol=position.symbol,
                side=Side.LONG if position.side == "LONG" else Side.SHORT,
                quantity=position.quantity,
                entry_price=position.mark_price or position.entry_price,
                stop_loss=position.entry_price,
                leverage=min(position.leverage or 1, 5),
            )
            close_client_id = await self._close_position_market(plan)
            existing = await self.query_order(plan.symbol, close_client_id)
            if existing:
                orders.append(self._normalize_order(existing))
        return orders

    async def manage_open_position_stops(self) -> list[dict[str, object]]:
        snapshot = await self.snapshot()
        actions: list[dict[str, object]] = []
        orders_by_symbol: dict[str, list[ExchangeOrder]] = {}
        for order in snapshot.orders:
            orders_by_symbol.setdefault(order.symbol, []).append(order)

        for position in snapshot.positions:
            if position.symbol in self._stop_management_symbols:
                continue
            self._stop_management_symbols.add(position.symbol)
            try:
                action = await self._manage_position_stop(
                    position, orders_by_symbol.get(position.symbol, [])
                )
                if action is not None:
                    actions.append(action)
            finally:
                self._stop_management_symbols.discard(position.symbol)
        return actions

    async def _manage_position_stop(
        self, position: ExchangePosition, orders: list[ExchangeOrder]
    ) -> dict[str, object] | None:
        group_id = self._managed_group_id(position.symbol, orders)
        if group_id is None:
            self._set_lifecycle_state(position, orders, ExchangePositionLifecycleState.PROTECTED)
            return None
        managed_orders = [
            order for order in orders if self._order_group_id(order.client_order_id) == group_id
        ]
        stop_orders = [
            order
            for order in managed_orders
            if order.stop_price
            and "STOP" in order.order_type
            and "TAKE_PROFIT" not in order.order_type
        ]
        take_profit_orders = [
            order
            for order in managed_orders
            if order.stop_price and "TAKE_PROFIT" in order.order_type
        ]
        self._sync_lifecycle(position, managed_orders, group_id=group_id)
        target = self._managed_stop_target(position, take_profit_orders)
        if target is None:
            return None
        current = self._active_stop_price(position, stop_orders)
        if not self._stop_improves(position, current, target):
            return None
        client_id = _client_order_id(
            group_id,
            "be" if self._remaining_tp_count(take_profit_orders) >= 2 else "lock",
            int(time.time() * 1000),
        )
        plan = OrderPlan(
            client_order_id=client_id,
            symbol=position.symbol,
            side=Side.LONG if position.side == "LONG" else Side.SHORT,
            quantity=position.quantity,
            entry_price=position.entry_price,
            stop_loss=target,
            leverage=min(position.leverage or 1, 10),
        )
        order = await self._place_managed_stop_loss(plan, client_id)
        if not await self._stop_loss_exists(position.symbol, client_id):
            raise StopLossProtectionError(f"Không xác nhận được SL mới cho {position.symbol}")
        for old_stop in stop_orders:
            if old_stop.client_order_id != client_id:
                await self.cancel_algo_order(
                    position.symbol, old_stop.client_order_id, old_stop.order_id
                )
        return {
            "symbol": position.symbol,
            "group_id": group_id,
            "lifecycle_state": self._lifecycle_state_for(position, take_profit_orders).value,
            "side": position.side,
            "old_stop": current,
            "new_stop": target,
            "remaining_take_profits": self._remaining_tp_count(take_profit_orders),
            "client_order_id": client_id,
            "order": self._normalize_algo_order(order).model_dump(mode="json"),
        }

    async def handle_user_stream_event(self, event: dict[str, Any]) -> list[dict[str, object]]:
        order = event.get("o")
        if not isinstance(order, dict):
            return []
        symbol = str(order.get("s") or "")
        client_order_id = str(order.get("c") or "")
        status = str(order.get("X") or "")
        if not symbol or not self._is_bot_order_id(client_order_id):
            return []

        group_id = self._order_group_id(client_order_id)
        lifecycle = self._lifecycles_by_symbol.get(symbol) or ExchangePositionLifecycle(
            symbol=symbol,
            group_id=group_id,
        )
        lifecycle.group_id = group_id
        lifecycle.last_event_at = datetime.now(UTC)
        lifecycle.updated_at = lifecycle.last_event_at
        if status == "FILLED" and "-tp-0" in client_order_id:
            lifecycle.state = ExchangePositionLifecycleState.TP1_HIT
        elif status == "FILLED" and "-tp-" in client_order_id:
            lifecycle.state = ExchangePositionLifecycleState.TP2_HIT
        elif status == "FILLED" and ("-sl-" in client_order_id or "-close" in client_order_id):
            lifecycle.state = ExchangePositionLifecycleState.CLOSING
        self._lifecycles_by_symbol[symbol] = lifecycle
        if status in {"FILLED", "PARTIALLY_FILLED"} and (
            "-tp-" in client_order_id or "-sl-" in client_order_id
        ):
            return await self.manage_open_position_stops()
        return []

    async def keepalive_user_stream(self) -> None:
        if self._listen_key:
            await self._request(
                "PUT", "/fapi/v1/listenKey", params={"listenKey": self._listen_key}, signed=False
            )
            self.snapshot_cache.last_user_stream_at = datetime.now(UTC)

    def mark_user_stream_event(self, received_at: datetime | None = None) -> None:
        self.snapshot_cache.last_user_stream_at = received_at or datetime.now(UTC)

    async def cancel_algo_order(
        self,
        symbol: str,
        client_algo_id: str | None = None,
        algo_id: int | str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if client_algo_id:
            params["clientAlgoId"] = client_algo_id
        elif algo_id not in (None, ""):
            params["algoId"] = algo_id
        else:
            raise ExchangeError("Thiếu clientAlgoId/algoId để hủy algo order")
        return await self._signed("DELETE", "/fapi/v1/algoOrder", params)

    async def change_margin_type(self, symbol: str, margin_type: str) -> None:
        try:
            await self._signed(
                "POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type}
            )
        except ExchangeError as exc:
            if "No need to change margin type" not in str(exc):
                raise

    async def change_leverage(self, symbol: str, leverage: int) -> None:
        await self._signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

    async def query_order(
        self, symbol: str, client_order_id: str, *, strict: bool = False
    ) -> dict[str, Any] | None:
        try:
            return await self._signed(
                "GET",
                "/fapi/v1/order",
                {"symbol": symbol, "origClientOrderId": client_order_id},
            )
        except ExchangeError as exc:
            message = str(exc)
            if "-2013" in message or "Order does not exist" in message:
                return None
            if strict:
                raise
            return None

    async def open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        params = {"symbol": symbol} if symbol else {}
        regular = await self._signed("GET", "/fapi/v1/openOrders", params)
        algo = await self._signed("GET", "/fapi/v1/openAlgoOrders", params)
        return [self._normalize_order(item) for item in regular] + [
            self._normalize_algo_order(item) for item in algo
        ]

    async def positions(self, symbol: str | None = None) -> list[ExchangePosition]:
        params = {"symbol": symbol} if symbol else {}
        data = await self._signed("GET", "/fapi/v2/positionRisk", params)
        positions = []
        for item in data:
            amount = float(item.get("positionAmt", 0) or 0)
            if abs(amount) <= 1e-12:
                continue
            positions.append(
                ExchangePosition(
                    symbol=item["symbol"],
                    side="LONG" if amount > 0 else "SHORT",
                    quantity=abs(amount),
                    entry_price=float(item.get("entryPrice", 0) or 0),
                    mark_price=float(item.get("markPrice", 0) or 0),
                    unrealized_pnl=float(item.get("unRealizedProfit", 0) or 0),
                    liquidation_price=_optional_float(item.get("liquidationPrice")),
                    leverage=int(float(item.get("leverage", 0) or 0)),
                    margin_type=item.get("marginType"),
                    raw=item,
                )
            )
        return positions

    async def balance(self) -> ExchangeBalance:
        data = await self._signed("GET", "/fapi/v2/account", {})
        return ExchangeBalance(
            asset="USDT",
            balance=float(data.get("totalWalletBalance", 0) or 0),
            available=float(data.get("availableBalance", 0) or 0),
            margin_balance=float(data.get("totalMarginBalance", 0) or 0),
            unrealized_pnl=float(data.get("totalUnrealizedProfit", 0) or 0),
        )

    async def income_history(
        self,
        *,
        income_type: str | None = None,
        limit: int = 100,
        start_time: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return income ledger rows, paging forward from an optional timestamp.

        Binance returns only the most recent ``limit`` rows without ``startTime``.
        Supplying the reset boundary prevents an active account from silently
        dropping older post-reset income and undercounting trade outcomes.
        """
        page_size = min(max(limit, 1), 1000)
        params: dict[str, Any] = {"limit": page_size}
        if income_type:
            params["incomeType"] = income_type
        if start_time is None:
            return list(await self._signed("GET", "/fapi/v1/income", params))

        rows: list[dict[str, Any]] = []
        cursor = start_time
        while True:
            data = list(
                await self._signed(
                    "GET", "/fapi/v1/income", {**params, "startTime": cursor}
                )
            )
            rows.extend(data)
            if len(data) < page_size:
                break
            newest = max(int(item.get("time") or 0) for item in data)
            if newest < cursor:
                break
            cursor = newest + 1
        return rows

    async def trade_history(self, symbol: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        trades = list(
            await self._signed("GET", "/fapi/v1/userTrades", {"symbol": symbol, "limit": limit})
        )
        orders = list(
            await self._signed("GET", "/fapi/v1/allOrders", {"symbol": symbol, "limit": limit})
        )
        clients = {str(row.get("orderId")): str(row.get("clientOrderId") or "") for row in orders}
        for trade in trades:
            trade.setdefault("clientOrderId", clients.get(str(trade.get("orderId")), ""))
        return trades

    async def repair_missing_stop_losses(
        self, snapshot: ExchangeSnapshot, *, max_attempts: int = 3
    ) -> list[dict[str, object]]:
        actions: list[dict[str, object]] = []
        managed_orders_by_symbol = {
            position.symbol: [
                order
                for order in snapshot.orders
                if order.symbol == position.symbol and self._is_bot_order_id(order.client_order_id)
            ]
            for position in snapshot.positions
        }
        for position in snapshot.positions:
            managed_orders = managed_orders_by_symbol[position.symbol]
            if self._has_protective_stop(position, managed_orders) or (
                self._stop_repair_attempts.get(position.symbol, 0) >= max_attempts
            ):
                continue
            history = await self._signed(
                "GET", "/fapi/v1/allAlgoOrders", {"symbol": position.symbol}
            )
            candidates = [
                row
                for row in history
                if self._is_bot_order_id(str(row.get("clientAlgoId") or ""))
                and "STOP" in str(row.get("orderType") or row.get("type") or "")
                and "TAKE_PROFIT" not in str(row.get("orderType") or row.get("type") or "")
                and float(row.get("triggerPrice") or row.get("stopPrice") or 0) > 0
            ]
            if not candidates:
                continue
            old = max(
                candidates, key=lambda row: int(row.get("updateTime") or row.get("createTime") or 0)
            )
            stop = float(old.get("triggerPrice") or old.get("stopPrice"))
            mark = position.mark_price or position.entry_price
            if (position.side == "LONG" and stop >= mark) or (
                position.side == "SHORT" and stop <= mark
            ):
                continue
            self._stop_repair_attempts[position.symbol] = (
                self._stop_repair_attempts.get(position.symbol, 0) + 1
            )
            group_id = self._order_group_id(str(old.get("clientAlgoId") or ""))
            client_id = _client_order_id(group_id, "repair", int(time.time() * 1000))
            plan = OrderPlan(
                client_order_id=client_id,
                symbol=position.symbol,
                side=Side.LONG if position.side == "LONG" else Side.SHORT,
                quantity=position.quantity,
                entry_price=position.entry_price,
                stop_loss=stop,
                leverage=min(position.leverage or 1, 10),
            )
            await self._place_managed_stop_loss(plan, client_id)
            if not await self._stop_loss_exists(position.symbol, client_id):
                raise StopLossProtectionError(
                    f"Không xác nhận được SL phục hồi cho {position.symbol}"
                )
            self._stop_repair_attempts.pop(position.symbol, None)
            actions.append(
                {"symbol": position.symbol, "stop_loss": stop, "status": "Đã phục hồi SL"}
            )
        return actions

    def unprotected_bot_positions(self, snapshot: ExchangeSnapshot) -> list[str]:
        """Return bot-owned symbols whose aggregate one-way position lacks a valid SL."""
        result: list[str] = []
        for position in snapshot.positions:
            orders = [
                order
                for order in snapshot.orders
                if order.symbol == position.symbol and self._is_bot_order_id(order.client_order_id)
            ]
            if orders and not self._has_protective_stop(position, orders):
                result.append(position.symbol)
        return sorted(set(result))

    async def close_unprotected_bot_positions(
        self, snapshot: ExchangeSnapshot, symbols: set[str]
    ) -> list[dict[str, object]]:
        """Close only named bot-owned positions that remain unprotected after repair."""
        orders_by_symbol: dict[str, list[ExchangeOrder]] = {}
        for order in snapshot.orders:
            orders_by_symbol.setdefault(order.symbol, []).append(order)

        actions: list[dict[str, object]] = []
        for position in snapshot.positions:
            if position.symbol not in symbols:
                continue
            group_id = self._managed_group_id(
                position.symbol, orders_by_symbol.get(position.symbol, [])
            )
            if not group_id:
                # Manual/foreign positions are never closed by the bot watchdog.
                continue
            plan = OrderPlan(
                client_order_id=group_id,
                symbol=position.symbol,
                side=Side.LONG if position.side == "LONG" else Side.SHORT,
                quantity=position.quantity,
                entry_price=position.mark_price or position.entry_price,
                stop_loss=position.entry_price,
                leverage=min(position.leverage or 1, 5),
            )
            close_client_id = await self._close_position_market(plan)
            actions.append(
                {
                    "symbol": position.symbol,
                    "quantity": position.quantity,
                    "group_id": group_id,
                    "client_order_id": close_client_id,
                    "status": "Đã gửi đóng vị thế thiếu SL",
                }
            )
        return actions

    async def remove_duplicate_stop_losses(
        self, snapshot: ExchangeSnapshot
    ) -> list[dict[str, object]]:
        actions: list[dict[str, object]] = []
        for position in snapshot.positions:
            stops = [
                order
                for order in snapshot.orders
                if order.symbol == position.symbol
                and order.stop_price
                and "STOP" in order.order_type
                and "TAKE_PROFIT" not in order.order_type
            ]
            if len(stops) <= 1:
                continue
            keep = (
                max(stops, key=lambda item: item.stop_price)
                if position.side == "LONG"
                else min(stops, key=lambda item: item.stop_price)
            )
            for order in stops:
                if order is keep or not self._is_bot_order_id(order.client_order_id):
                    continue
                await self._signed(
                    "DELETE",
                    "/fapi/v1/algoOrder",
                    {"symbol": position.symbol, "clientAlgoId": order.client_order_id},
                )
                actions.append(
                    {
                        "symbol": position.symbol,
                        "client_order_id": order.client_order_id,
                        "status": "Đã hủy SL trùng",
                    }
                )
        return actions

    async def is_symbol_tradable(self, symbol: str) -> bool:
        try:
            await self._filters_for(symbol)
        except ExchangeError:
            return False
        return True

    async def _normalize_plan(self, plan: OrderPlan) -> OrderPlan:
        filters = await self._filters_for(plan.symbol)
        quantity = _round_step(plan.quantity, filters["quantity_step"])
        if quantity < float(filters["min_quantity"]):
            raise ExchangeError(
                f"Quantity {quantity} nhỏ hơn minQty {filters['min_quantity']} cho {plan.symbol}"
            )
        return plan.model_copy(
            update={
                "quantity": quantity,
                "entry_price": _round_tick(plan.entry_price, filters["price_tick"]),
                "stop_loss": _round_tick(plan.stop_loss, filters["price_tick"]),
                "take_profits": [
                    _round_tick(take_profit, filters["price_tick"])
                    for take_profit in plan.take_profits
                ],
            }
        )

    async def _filters_for(self, symbol: str) -> dict[str, Decimal]:
        cached = self._symbol_filters.get(symbol)
        if cached:
            return cached
        payload = self.gateway.cached("/fapi/v1/exchangeInfo", None)
        if payload is None:
            payload = await self._request("GET", "/fapi/v1/exchangeInfo", signed=False)
            self.gateway.store("/fapi/v1/exchangeInfo", None, payload)
        data = payload
        for item in data.get("symbols", []):
            if item.get("symbol") != symbol:
                continue
            if item.get("status") != "TRADING":
                raise ExchangeError(f"{symbol} không ở trạng thái TRADING trên {self.mode.value}")
            filters = {entry.get("filterType"): entry for entry in item.get("filters", [])}
            lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
            price = filters.get("PRICE_FILTER") or {}
            parsed = {
                "quantity_step": Decimal(str(lot.get("stepSize", "0.001"))),
                "min_quantity": Decimal(str(lot.get("minQty", "0"))),
                "price_tick": Decimal(str(price.get("tickSize", "0.000001"))),
            }
            self._symbol_filters[symbol] = parsed
            return parsed
        raise ExchangeError(f"Không tìm thấy exchange filters cho {symbol}")

    async def _place_entry(self, plan: OrderPlan) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": plan.symbol,
            "side": "BUY" if plan.side == Side.LONG else "SELL",
            "type": plan.order_type.value,
            "quantity": _format_number(plan.quantity),
            "newClientOrderId": plan.client_order_id,
            "newOrderRespType": "RESULT",
        }
        if plan.order_type == OrderType.LIMIT:
            params["timeInForce"] = "GTC"
            params["price"] = _format_number(plan.entry_price)
        try:
            return await self._signed("POST", "/fapi/v1/order", params)
        except ExchangeError:
            try:
                existing = await self.query_order(plan.symbol, plan.client_order_id, strict=True)
                if existing:
                    return existing
            except ExchangeError as query_exc:
                self._enter_safe_mode(
                    f"Không xác định được kết quả entry {plan.client_order_id}: {query_exc}"
                )
                raise ExchangeError(
                    self.snapshot_cache.safe_mode_reason or "Entry outcome uncertain"
                ) from query_exc
            raise

    async def _ensure_stop_loss(self, plan: OrderPlan) -> dict[str, Any] | None:
        for attempt in range(3):
            client_id = _client_order_id(plan.client_order_id, "sl", attempt)
            try:
                order = await self._place_stop_loss(plan, client_id)
                if await self._stop_loss_exists(plan.symbol, client_id):
                    return order
            except ExchangeError:
                await _sleep_backoff(attempt)
        return None

    async def _place_stop_loss(self, plan: OrderPlan, client_id: str) -> dict[str, Any]:
        return await self._signed(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "algoType": "CONDITIONAL",
                "symbol": plan.symbol,
                "side": "SELL" if plan.side == Side.LONG else "BUY",
                "type": "STOP_MARKET",
                "triggerPrice": _format_number(plan.stop_loss),
                "closePosition": "true",
                "workingType": "CONTRACT_PRICE",
                "clientAlgoId": client_id,
            },
        )

    async def _place_managed_stop_loss(self, plan: OrderPlan, client_id: str) -> dict[str, Any]:
        return await self._signed(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "algoType": "CONDITIONAL",
                "symbol": plan.symbol,
                "side": "SELL" if plan.side == Side.LONG else "BUY",
                "type": "STOP_MARKET",
                "triggerPrice": _format_number(plan.stop_loss),
                "quantity": _format_number(plan.quantity),
                "reduceOnly": "true",
                "workingType": "CONTRACT_PRICE",
                "clientAlgoId": client_id,
            },
        )

    async def _place_take_profit(
        self,
        plan: OrderPlan,
        take_profit: float,
        quantity: float,
        index: int,
        *,
        close_position: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": plan.symbol,
            "side": "SELL" if plan.side == Side.LONG else "BUY",
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": _format_number(take_profit),
            "workingType": "CONTRACT_PRICE",
            "clientAlgoId": _client_order_id(plan.client_order_id, "tp", index),
        }
        if close_position:
            payload["closePosition"] = "true"
        else:
            payload["quantity"] = _format_number(quantity)
            payload["reduceOnly"] = "true"
        return await self._signed("POST", "/fapi/v1/algoOrder", payload)

    async def _post_entry_reference_price(self, plan: OrderPlan, entry: dict[str, Any]) -> float:
        try:
            positions = await self.positions(plan.symbol)
        except ExchangeError:
            positions = []
        for position in positions:
            if position.symbol == plan.symbol and position.mark_price > 0:
                return position.mark_price
        fills = entry.get("fills")
        fill_price = None
        if isinstance(fills, list) and fills:
            first_fill = fills[0]
            if isinstance(first_fill, dict):
                fill_price = first_fill.get("price")
        return float(
            entry.get("avgPrice") or entry.get("price") or fill_price or plan.entry_price or 0
        )

    @staticmethod
    def _stop_loss_is_actionable(
        side: Side,
        stop_loss: float,
        *,
        reference_price: float,
        price_tick: Decimal,
    ) -> bool:
        if reference_price <= 0:
            return True
        buffer = float(price_tick) if price_tick > 0 else 0.0
        if side == Side.LONG:
            return stop_loss < reference_price - buffer
        return stop_loss > reference_price + buffer

    @staticmethod
    def _take_profit_is_actionable(
        side: Side,
        take_profit: float,
        *,
        reference_price: float,
        price_tick: Decimal,
    ) -> bool:
        if reference_price <= 0:
            return True
        buffer = float(price_tick) if price_tick > 0 else 0.0
        if side == Side.LONG:
            return take_profit > reference_price + buffer
        return take_profit < reference_price - buffer

    async def _take_profit_quantity_for_plan(
        self, plan: OrderPlan, index: int, total: int
    ) -> float:
        filters = await self._filters_for(plan.symbol)
        return _round_step(
            self._take_profit_quantity(plan.quantity, index, total),
            filters["quantity_step"],
        )

    async def _close_position_market(self, plan: OrderPlan) -> str:
        client_order_id = _client_order_id(plan.client_order_id, "close")
        await self._signed(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": plan.symbol,
                "side": "SELL" if plan.side == Side.LONG else "BUY",
                "type": "MARKET",
                "quantity": _format_number(plan.quantity),
                "reduceOnly": "true",
                "newClientOrderId": client_order_id,
            },
        )
        return client_order_id

    async def _stop_loss_exists(self, symbol: str, client_id: str) -> bool:
        orders = await self.open_orders(symbol)
        return any(
            order.client_order_id == client_id
            and "STOP" in order.order_type
            and "TAKE_PROFIT" not in order.order_type
            for order in orders
        )

    @staticmethod
    def _has_protective_stop(position: ExchangePosition, orders: list[ExchangeOrder]) -> bool:
        stops = [
            order
            for order in orders
            if order.stop_price
            and "STOP" in order.order_type
            and "TAKE_PROFIT" not in order.order_type
            and order.status in {"NEW", "WORKING", "TRIGGERED"}
        ]
        mark = position.mark_price or position.entry_price
        for order in stops:
            valid_side = (
                order.side == "SELL" and position.side == "LONG" and order.stop_price < mark
            ) or (order.side == "BUY" and position.side == "SHORT" and order.stop_price > mark)
            if not valid_side:
                continue
            raw = order.raw or {}
            if raw.get("closePosition") in {True, "true", "TRUE"}:
                return True
            if order.quantity + 1e-12 >= abs(position.quantity):
                return True
        return False

    def _sync_lifecycles_from_snapshot(
        self,
        positions: list[ExchangePosition],
        orders: list[ExchangeOrder],
    ) -> list[ExchangePositionLifecycle]:
        orders_by_symbol: dict[str, list[ExchangeOrder]] = {}
        for order in orders:
            orders_by_symbol.setdefault(order.symbol, []).append(order)

        live_symbols = {position.symbol for position in positions}
        for symbol in list(self._lifecycles_by_symbol):
            if symbol not in live_symbols and symbol not in orders_by_symbol:
                lifecycle = self._lifecycles_by_symbol[symbol]
                lifecycle.state = ExchangePositionLifecycleState.CLOSED
                lifecycle.current_quantity = 0.0
                lifecycle.remaining_take_profits = 0
                lifecycle.updated_at = datetime.now(UTC)

        for position in positions:
            symbol_orders = orders_by_symbol.get(position.symbol, [])
            group_id = self._managed_group_id(position.symbol, symbol_orders)
            if group_id is None:
                continue
            self._sync_lifecycle(position, symbol_orders, group_id=group_id)
        return list(self._lifecycles_by_symbol.values())

    def _sync_lifecycle(
        self,
        position: ExchangePosition,
        orders: list[ExchangeOrder],
        *,
        group_id: str,
    ) -> ExchangePositionLifecycle:
        managed_orders = [
            order for order in orders if self._order_group_id(order.client_order_id) == group_id
        ]
        take_profit_orders = [
            order
            for order in managed_orders
            if order.stop_price and "TAKE_PROFIT" in order.order_type
        ]
        stop_orders = [
            order
            for order in managed_orders
            if order.stop_price
            and "STOP" in order.order_type
            and "TAKE_PROFIT" not in order.order_type
        ]
        lifecycle = self._lifecycles_by_symbol.get(position.symbol) or ExchangePositionLifecycle(
            symbol=position.symbol,
            group_id=group_id,
            initial_quantity=position.quantity,
        )
        lifecycle.group_id = group_id
        lifecycle.side = position.side
        lifecycle.entry_price = position.entry_price
        lifecycle.current_quantity = position.quantity
        lifecycle.initial_quantity = max(lifecycle.initial_quantity, position.quantity)
        lifecycle.remaining_take_profits = self._remaining_tp_count(take_profit_orders)
        lifecycle.active_stop = self._active_stop_price(position, stop_orders)
        lifecycle.state = self._lifecycle_state_for(position, take_profit_orders)
        lifecycle.updated_at = datetime.now(UTC)
        self._lifecycles_by_symbol[position.symbol] = lifecycle
        return lifecycle

    def _set_lifecycle_state(
        self,
        position: ExchangePosition,
        orders: list[ExchangeOrder],
        state: ExchangePositionLifecycleState,
    ) -> None:
        group_id = self._managed_group_id(position.symbol, orders)
        if group_id is None:
            return
        lifecycle = self._sync_lifecycle(position, orders, group_id=group_id)
        lifecycle.state = state
        lifecycle.updated_at = datetime.now(UTC)

    def _lifecycle_state_for(
        self,
        position: ExchangePosition,
        take_profit_orders: list[ExchangeOrder],
    ) -> ExchangePositionLifecycleState:
        remaining = self._remaining_tp_count(take_profit_orders)
        if position.quantity <= 0:
            return ExchangePositionLifecycleState.CLOSED
        if remaining >= 3:
            return ExchangePositionLifecycleState.PROTECTED
        if remaining == 2:
            return ExchangePositionLifecycleState.TP1_HIT
        if remaining <= 1:
            return ExchangePositionLifecycleState.TP2_HIT
        return ExchangePositionLifecycleState.PROTECTED

    def _managed_group_id(self, symbol: str, orders: list[ExchangeOrder]) -> str | None:
        plan = self._submitted_plans_by_symbol.get(symbol)
        if plan:
            return plan.client_order_id
        group_ids = [
            self._order_group_id(order.client_order_id)
            for order in orders
            if self._is_bot_order_id(order.client_order_id)
        ]
        if not group_ids:
            return None
        return max(set(group_ids), key=group_ids.count)

    def _managed_stop_target(
        self,
        position: ExchangePosition,
        take_profit_orders: list[ExchangeOrder],
    ) -> float | None:
        remaining = self._remaining_tp_count(take_profit_orders)
        if remaining >= 3:
            return None
        plan = self._submitted_plans_by_symbol.get(position.symbol)
        if remaining >= 2:
            target = position.entry_price
        elif plan and plan.take_profits:
            target = plan.take_profits[0]
        else:
            next_tp = self._next_take_profit(position, take_profit_orders)
            if next_tp is None:
                target = position.entry_price
            elif position.side == "LONG":
                target = position.entry_price + abs(next_tp - position.entry_price) * 0.35
            else:
                target = position.entry_price - abs(position.entry_price - next_tp) * 0.35
        filters = self._symbol_filters.get(position.symbol)
        if filters:
            target = _round_tick(target, filters["price_tick"])
        return target

    @staticmethod
    def _remaining_tp_count(take_profit_orders: list[ExchangeOrder]) -> int:
        return len([order for order in take_profit_orders if order.stop_price])

    @staticmethod
    def _active_stop_price(
        position: ExchangePosition, stop_orders: list[ExchangeOrder]
    ) -> float | None:
        prices = [order.stop_price for order in stop_orders if order.stop_price]
        if not prices:
            return None
        return max(prices) if position.side == "LONG" else min(prices)

    @staticmethod
    def _next_take_profit(
        position: ExchangePosition, take_profit_orders: list[ExchangeOrder]
    ) -> float | None:
        prices = sorted(order.stop_price for order in take_profit_orders if order.stop_price)
        if not prices:
            return None
        return prices[0] if position.side == "LONG" else prices[-1]

    @staticmethod
    def _stop_improves(
        position: ExchangePosition, current_stop: float | None, target: float
    ) -> bool:
        mark = position.mark_price or position.entry_price
        if position.side == "LONG":
            if target >= mark:
                return False
            return current_stop is None or target > current_stop + 1e-12
        if target <= mark:
            return False
        return current_stop is None or target < current_stop - 1e-12

    async def _signed(self, method: str, path: str, params: dict[str, Any]) -> Any:
        await self._sync_time_if_needed()
        try:
            return await self._request(method, path, params=params, signed=True)
        except ExchangeError as exc:
            if "-1021" not in str(exc):
                raise
            await self._sync_time_if_needed(force=True)
            return await self._request(method, path, params=params, signed=True)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        signed: bool,
    ) -> Any:
        self._require_credentials()
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            await self.gateway.acquire(method, path, signed=signed)
        except CircuitOpenError as exc:
            raise ExchangeError(f"Binance gateway đang khóa circuit breaker: {exc}") from exc
        except RateLimitBudgetExceeded as exc:
            raise ExchangeError(f"Vượt ngân sách rate limit Binance: {exc}") from exc
        # Ký request sau khi rate limiter cấp lượt. Nếu ký trước khi chờ hàng đợi,
        # timestamp có thể hết recvWindow và Binance trả -1021 dù đồng hồ đã đồng bộ.
        if signed:
            params["timestamp"] = self._timestamp_ms()
            params["recvWindow"] = self.recv_window
            params["signature"] = self._signature(params)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    params=params if method == "GET" else None,
                    data=params if method != "GET" else None,
                )
        except httpx.HTTPError as exc:
            self.gateway.record_failure()
            raise ExchangeError(f"Binance request lỗi mạng: {exc}") from exc
        if response.status_code >= 400:
            self.gateway.record_failure(
                status_code=response.status_code,
                retry_after_seconds=_retry_after_seconds(response),
            )
            raise ExchangeError(f"Binance {response.status_code}: {response.text}")
        self.gateway.record_success()
        return response.json()

    async def _sync_time_if_needed(self, *, force: bool = False) -> None:
        local_before = int(time.time() * 1000)
        if not force and local_before - self._last_time_sync_ms < 30_000:
            return
        await self.gateway.acquire("GET", "/fapi/v1/time", signed=False)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/fapi/v1/time")
        except httpx.HTTPError as exc:
            self.gateway.record_failure()
            raise ExchangeError(f"Binance time sync lỗi mạng: {exc}") from exc
        local_after = int(time.time() * 1000)
        if response.status_code >= 400:
            self.gateway.record_failure(status_code=response.status_code)
            raise ExchangeError(f"Binance {response.status_code}: {response.text}")
        self.gateway.record_success()
        server_time = int(response.json()["serverTime"])
        # Midpoint removes most request latency from the estimated server offset.
        local_midpoint = (local_before + local_after) // 2
        self._time_offset_ms = server_time - local_midpoint
        self._last_time_sync_ms = local_after

    def _timestamp_ms(self) -> int:
        return int(time.time() * 1000) + self._time_offset_ms

    def _signature(self, params: dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        return hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _require_credentials(self) -> None:
        if not self.configured:
            raise ExchangeCredentialsError(self._credentials_message())

    def _credentials_message(self) -> str:
        if self.mode == TradingMode.LIVE:
            return "Thiếu BINANCE_API_KEY/SECRET cho LIVE"
        return "Thiếu BINANCE_DEMO_API_KEY/SECRET"

    @staticmethod
    def _normalize_order(item: dict[str, Any]) -> ExchangeOrder:
        return ExchangeOrder(
            symbol=item["symbol"],
            order_id=item.get("orderId", ""),
            client_order_id=item.get("clientOrderId") or item.get("origClientOrderId") or "",
            side=item.get("side", ""),
            order_type=item.get("type") or item.get("origType") or "",
            status=item.get("status", ""),
            price=float(item.get("price", 0) or 0),
            quantity=float(item.get("origQty", item.get("quantity", 0)) or 0),
            executed_quantity=float(item.get("executedQty", 0) or 0),
            reduce_only=bool(item.get("reduceOnly", False)),
            stop_price=_optional_float(item.get("stopPrice")),
            raw=item,
        )

    @staticmethod
    def _normalize_algo_order(item: dict[str, Any]) -> ExchangeOrder:
        return ExchangeOrder(
            symbol=item["symbol"],
            order_id=item.get("algoId", ""),
            client_order_id=item.get("clientAlgoId", ""),
            side=item.get("side", ""),
            order_type=item.get("orderType", ""),
            status=item.get("algoStatus", ""),
            price=float(item.get("price", 0) or 0),
            quantity=float(item.get("quantity", 0) or 0),
            executed_quantity=float(item.get("actualQty", 0) or 0),
            reduce_only=bool(item.get("reduceOnly", False)),
            stop_price=_optional_float(item.get("triggerPrice")),
            raw=item,
        )

    @staticmethod
    def _take_profit_quantity(quantity: float, index: int, total: int) -> float:
        if total <= 1:
            return quantity
        if index == 0:
            return quantity * 0.4
        if index == 1:
            return quantity * 0.3
        return quantity * 0.3 / max(total - 2, 1)

    @staticmethod
    def _is_bot_order_id(client_order_id: str) -> bool:
        return client_order_id.startswith(("a-demo-", "a-live-", "demo-", "live-"))

    @staticmethod
    def _order_group_id(client_order_id: str) -> str:
        for marker in ("-tp-", "-sl-", "-be-", "-lock-", "-close"):
            if marker in client_order_id:
                return client_order_id.split(marker, 1)[0]
        return client_order_id


def _format_number(value: float) -> str:
    return f"{value:.12f}".rstrip("0").rstrip(".")


def _round_step(value: float, step: Decimal) -> float:
    if step <= 0:
        return value
    quantized = (Decimal(str(value)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    return float(quantized)


def _round_tick(value: float, tick: Decimal) -> float:
    if tick <= 0:
        return value
    quantized = (Decimal(str(value)) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
    return float(quantized)


def _client_order_id(*parts: object, max_length: int = 36) -> str:
    raw = "-".join(str(part) for part in parts if str(part))
    if len(raw) <= max_length:
        return raw
    digest = hashlib.sha1(raw.encode()).hexdigest()[:8]
    prefix_length = max_length - len(digest) - 1
    return f"{raw[:prefix_length].rstrip('-')}-{digest}"


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = float(value)
    return parsed if parsed > 0 else None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


async def _sleep_backoff(attempt: int) -> None:
    import asyncio

    await asyncio.sleep(0.2 * (2**attempt))
