import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.domain.models import (
    ExchangeBalance,
    ExchangeConnectionState,
    ExchangeExecutionResult,
    ExchangeOrder,
    ExchangePosition,
    ExchangeSnapshot,
    OrderPlan,
    OrderType,
    Side,
    TradingMode,
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


class BinanceFuturesAdapter(ExchangeAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = "https://demo-fapi.binance.com",
        stream_url: str = "wss://demo-fstream.binance.com",
        recv_window: int = 5000,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.stream_url = stream_url.rstrip("/")
        self.recv_window = recv_window
        self._submitted_client_ids: set[str] = set()
        self._listen_key: str | None = None
        self.snapshot_cache = ExchangeSnapshot(mode=TradingMode.DEMO)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def submit_order_plan(self, plan: OrderPlan) -> ExchangeExecutionResult:
        self._require_credentials()
        if plan.client_order_id in self._submitted_client_ids:
            existing = await self.query_order(plan.symbol, plan.client_order_id)
            if existing:
                return ExchangeExecutionResult(
                    accepted=True,
                    status="DEMO_DUPLICATE_ACK",
                    client_order_id=plan.client_order_id,
                    order=self._normalize_order(existing).model_dump(mode="json"),
                )
            raise ExchangeError(f"Duplicate client order id: {plan.client_order_id}")
        self._submitted_client_ids.add(plan.client_order_id)

        await self.change_margin_type(plan.symbol, plan.margin_type.value)
        await self.change_leverage(plan.symbol, plan.leverage)

        entry = await self._place_entry(plan)
        sl_order = await self._ensure_stop_loss(plan)
        if sl_order is None:
            await self._close_position_market(plan)
            alert = "CRITICAL: Không tạo được SL trên Binance DEMO, đã gửi lệnh đóng vị thế"
            return ExchangeExecutionResult(
                accepted=False,
                status="DEMO_SL_FAILED_POSITION_CLOSING",
                client_order_id=plan.client_order_id,
                order=self._normalize_order(entry).model_dump(mode="json"),
                critical_alert=alert,
            )

        take_profit_orders = []
        for index, take_profit in enumerate(plan.take_profits):
            quantity = self._take_profit_quantity(plan.quantity, index, len(plan.take_profits))
            if quantity <= 0:
                continue
            take_profit_orders.append(await self._place_take_profit(plan, take_profit, quantity, index))

        return ExchangeExecutionResult(
            accepted=True,
            status="DEMO_SUBMITTED",
            client_order_id=plan.client_order_id,
            order=self._normalize_order(entry).model_dump(mode="json"),
            positions=[position.model_dump(mode="json") for position in (await self.positions(plan.symbol))],
            fills=[],
            trades=[],
        )

    async def snapshot(self) -> ExchangeSnapshot:
        if not self.configured:
            self.snapshot_cache = ExchangeSnapshot(
                mode=TradingMode.DEMO,
                connection=ExchangeConnectionState.DISCONNECTED,
                safe_mode=self.snapshot_cache.safe_mode,
                safe_mode_reason="Thiếu BINANCE_DEMO_API_KEY/SECRET",
            )
            return self.snapshot_cache
        balance = await self.balance()
        orders = await self.open_orders()
        positions = await self.positions()
        self.snapshot_cache = ExchangeSnapshot(
            mode=TradingMode.DEMO,
            connection=ExchangeConnectionState.CONNECTED,
            safe_mode=self.snapshot_cache.safe_mode,
            safe_mode_reason=self.snapshot_cache.safe_mode_reason,
            balance=balance,
            orders=orders,
            positions=positions,
            last_reconciled_at=self.snapshot_cache.last_reconciled_at,
            last_user_stream_at=self.snapshot_cache.last_user_stream_at,
        )
        return self.snapshot_cache

    async def reconcile(self, local_positions: list[dict[str, Any]]) -> ExchangeSnapshot:
        snapshot = await self.snapshot()
        exchange_symbols = {position.symbol for position in snapshot.positions if abs(position.quantity) > 0}
        local_symbols = {str(position.get("symbol")) for position in local_positions if position.get("status") == "OPEN"}
        mismatch = sorted(exchange_symbols.symmetric_difference(local_symbols))
        if mismatch:
            snapshot.safe_mode = True
            snapshot.connection = ExchangeConnectionState.SAFE_MODE
            snapshot.safe_mode_reason = f"Mismatch vị thế Binance vs DB: {', '.join(mismatch)}"
        snapshot.last_reconciled_at = datetime.now(UTC)
        self.snapshot_cache = snapshot
        return snapshot

    async def open_user_stream(self) -> str:
        self._require_credentials()
        payload = await self._request("POST", "/fapi/v1/listenKey", signed=False)
        listen_key = str(payload["listenKey"])
        self._listen_key = listen_key
        self.snapshot_cache.last_user_stream_at = datetime.now(UTC)
        return f"{self.stream_url}/ws/{listen_key}"

    async def keepalive_user_stream(self) -> None:
        if self._listen_key:
            await self._request("PUT", "/fapi/v1/listenKey", params={"listenKey": self._listen_key}, signed=False)
            self.snapshot_cache.last_user_stream_at = datetime.now(UTC)

    async def change_margin_type(self, symbol: str, margin_type: str) -> None:
        try:
            await self._signed("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type})
        except ExchangeError as exc:
            if "No need to change margin type" not in str(exc):
                raise

    async def change_leverage(self, symbol: str, leverage: int) -> None:
        await self._signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

    async def query_order(self, symbol: str, client_order_id: str) -> dict[str, Any] | None:
        try:
            return await self._signed(
                "GET",
                "/fapi/v1/order",
                {"symbol": symbol, "origClientOrderId": client_order_id},
            )
        except ExchangeError:
            return None

    async def open_orders(self, symbol: str | None = None) -> list[ExchangeOrder]:
        params = {"symbol": symbol} if symbol else {}
        data = await self._signed("GET", "/fapi/v1/openOrders", params)
        return [self._normalize_order(item) for item in data]

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
        except ExchangeError as exc:
            if "Unknown error" in str(exc):
                existing = await self.query_order(plan.symbol, plan.client_order_id)
                if existing:
                    return existing
            raise

    async def _ensure_stop_loss(self, plan: OrderPlan) -> dict[str, Any] | None:
        for attempt in range(3):
            client_id = f"{plan.client_order_id}-sl-{attempt}"
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
            "/fapi/v1/order",
            {
                "symbol": plan.symbol,
                "side": "SELL" if plan.side == Side.LONG else "BUY",
                "type": "STOP_MARKET",
                "stopPrice": _format_number(plan.stop_loss),
                "closePosition": "true",
                "workingType": "CONTRACT_PRICE",
                "newClientOrderId": client_id,
            },
        )

    async def _place_take_profit(
        self, plan: OrderPlan, take_profit: float, quantity: float, index: int
    ) -> dict[str, Any]:
        return await self._signed(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": plan.symbol,
                "side": "SELL" if plan.side == Side.LONG else "BUY",
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": _format_number(take_profit),
                "quantity": _format_number(quantity),
                "reduceOnly": "true",
                "workingType": "CONTRACT_PRICE",
                "newClientOrderId": f"{plan.client_order_id}-tp-{index}",
            },
        )

    async def _close_position_market(self, plan: OrderPlan) -> None:
        await self._signed(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": plan.symbol,
                "side": "SELL" if plan.side == Side.LONG else "BUY",
                "type": "MARKET",
                "quantity": _format_number(plan.quantity),
                "reduceOnly": "true",
                "newClientOrderId": f"{plan.client_order_id}-critical-close",
            },
        )

    async def _stop_loss_exists(self, symbol: str, client_id: str) -> bool:
        orders = await self.open_orders(symbol)
        return any(order.client_order_id == client_id and order.order_type == "STOP_MARKET" for order in orders)

    async def _signed(self, method: str, path: str, params: dict[str, Any]) -> Any:
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
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self.recv_window
            params["signature"] = self._signature(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                params=params if method == "GET" else None,
                data=params if method != "GET" else None,
            )
        if response.status_code >= 400:
            raise ExchangeError(f"Binance {response.status_code}: {response.text}")
        return response.json()

    def _signature(self, params: dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        return hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _require_credentials(self) -> None:
        if not self.configured:
            raise ExchangeCredentialsError("Thiếu BINANCE_DEMO_API_KEY/SECRET")

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
    def _take_profit_quantity(quantity: float, index: int, total: int) -> float:
        if total <= 1:
            return quantity
        if index == 0:
            return quantity * 0.4
        if index == 1:
            return quantity * 0.3
        return quantity * 0.3 / max(total - 2, 1)


def _format_number(value: float) -> str:
    return f"{value:.12f}".rstrip("0").rstrip(".")


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = float(value)
    return parsed if parsed > 0 else None


async def _sleep_backoff(attempt: int) -> None:
    import asyncio

    await asyncio.sleep(0.2 * (2**attempt))
