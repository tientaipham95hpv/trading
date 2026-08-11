from typing import Any

from app.domain.models import MarginType, OrderPlan, Side
from app.services.exchange import BinanceFuturesAdapter


def plan(**overrides):
    data = {
        "client_order_id": "demo-BTCUSDT-1",
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "quantity": 0.01,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profits": [105.0, 110.0, 115.0],
        "leverage": 2,
        "margin_type": MarginType.ISOLATED,
    }
    data.update(overrides)
    return OrderPlan(**data)


class FakeBinanceAdapter(BinanceFuturesAdapter):
    def __init__(self) -> None:
        super().__init__(api_key="key", api_secret="secret")
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.sl_exists = True

    async def _signed(self, method: str, path: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, path, params))
        if path == "/fapi/v1/order" and method == "POST":
            return {
                "symbol": params["symbol"],
                "orderId": len(self.calls),
                "clientOrderId": params.get("newClientOrderId", ""),
                "side": params.get("side", ""),
                "type": params.get("type", ""),
                "status": "NEW",
                "price": params.get("price", 0),
                "origQty": params.get("quantity", 0),
                "executedQty": "0",
                "reduceOnly": params.get("reduceOnly") == "true",
                "stopPrice": params.get("stopPrice", 0),
            }
        if path == "/fapi/v1/order" and method == "GET":
            return {
                "symbol": params["symbol"],
                "orderId": 1,
                "clientOrderId": params["origClientOrderId"],
                "side": "BUY",
                "type": "MARKET",
                "status": "FILLED",
                "price": "0",
                "origQty": "0.01",
                "executedQty": "0.01",
                "reduceOnly": False,
                "stopPrice": "0",
            }
        if path == "/fapi/v2/positionRisk":
            return []
        if path == "/fapi/v1/openOrders":
            if not self.sl_exists:
                return []
            return [
                {
                    "symbol": params.get("symbol", "BTCUSDT"),
                    "orderId": 99,
                    "clientOrderId": "demo-BTCUSDT-1-sl-0",
                    "side": "SELL",
                    "type": "STOP_MARKET",
                    "status": "NEW",
                    "origQty": "0",
                    "executedQty": "0",
                    "reduceOnly": False,
                    "stopPrice": "95",
                }
            ]
        return {}


async def test_binance_demo_places_entry_sl_and_reduce_only_take_profits():
    adapter = FakeBinanceAdapter()

    result = await adapter.submit_order_plan(plan())

    assert result.accepted is True
    order_types = [params.get("type") for _, path, params in adapter.calls if path == "/fapi/v1/order"]
    assert "MARKET" in order_types
    assert "STOP_MARKET" in order_types
    assert "TAKE_PROFIT_MARKET" in order_types
    assert any(params.get("reduceOnly") == "true" for _, _, params in adapter.calls)


async def test_sl_failure_closes_position_and_returns_critical_alert():
    adapter = FakeBinanceAdapter()
    adapter.sl_exists = False

    result = await adapter.submit_order_plan(plan())

    assert result.accepted is False
    assert result.critical_alert is not None
    assert any(
        params.get("newClientOrderId") == "demo-BTCUSDT-1-critical-close"
        for _, path, params in adapter.calls
        if path == "/fapi/v1/order"
    )


async def test_reconcile_mismatch_enters_safe_mode():
    adapter = FakeBinanceAdapter()

    async def fake_snapshot():
        snapshot = adapter.snapshot_cache
        snapshot.positions = []
        return snapshot

    adapter.snapshot = fake_snapshot  # type: ignore[method-assign]

    snapshot = await adapter.reconcile([{"symbol": "BTCUSDT", "status": "OPEN"}])

    assert snapshot.safe_mode is True
    assert "BTCUSDT" in (snapshot.safe_mode_reason or "")


async def test_duplicate_client_order_id_queries_existing_order():
    adapter = FakeBinanceAdapter()
    await adapter.submit_order_plan(plan())

    result = await adapter.submit_order_plan(plan())

    assert result.status == "DEMO_DUPLICATE_ACK"
