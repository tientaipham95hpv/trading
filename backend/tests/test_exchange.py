from decimal import Decimal
from typing import Any

from app.domain.models import MarginType, OrderPlan, Side, TradingMode
from app.services.exchange import BinanceFuturesAdapter, ExchangeError
from app.services.user_stream import UserStreamWatchdog


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
    def __init__(self, mode: TradingMode = TradingMode.DEMO) -> None:
        super().__init__(api_key="key", api_secret="secret", mode=mode)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.sl_exists = True
        self.position_risk: list[dict[str, Any]] = []
        self.open_algo_orders: list[dict[str, Any]] | None = None
        # Unit tests must never depend on Binance or make real network calls.
        self._symbol_filters["BTCUSDT"] = {
            "quantity_step": Decimal("0.001"),
            "min_quantity": Decimal("0.001"),
            "price_tick": Decimal("0.1"),
        }

    async def _signed(self, method: str, path: str, params: dict[str, Any]) -> Any:
        self.calls.append((method, path, params))
        if path == "/fapi/v1/algoOrder" and method == "DELETE":
            return {"code": 0, "msg": "OK", "clientAlgoId": params.get("clientAlgoId", "")}
        if path in {"/fapi/v1/order", "/fapi/v1/algoOrder"} and method == "POST":
            if path == "/fapi/v1/algoOrder" and self.open_algo_orders is not None:
                self.open_algo_orders.append(
                    {
                        "symbol": params["symbol"],
                        "algoId": len(self.calls),
                        "clientAlgoId": params.get("clientAlgoId", ""),
                        "side": params.get("side", ""),
                        "orderType": params.get("type", ""),
                        "algoStatus": "NEW",
                        "quantity": params.get("quantity", "0"),
                        "actualQty": "0",
                        "reduceOnly": params.get("reduceOnly") == "true",
                        "triggerPrice": params.get("triggerPrice", "0"),
                    }
                )
            return {
                "symbol": params["symbol"],
                "orderId": len(self.calls),
                "algoId": len(self.calls),
                "clientOrderId": params.get("newClientOrderId", ""),
                "clientAlgoId": params.get("clientAlgoId", ""),
                "side": params.get("side", ""),
                "type": params.get("type", ""),
                "orderType": params.get("type", ""),
                "status": "NEW",
                "algoStatus": "NEW",
                "price": params.get("price", 0),
                "origQty": params.get("quantity", 0),
                "quantity": params.get("quantity", 0),
                "executedQty": "0",
                "actualQty": "0",
                "reduceOnly": params.get("reduceOnly") == "true",
                "stopPrice": params.get("stopPrice", params.get("triggerPrice", 0)),
                "triggerPrice": params.get("triggerPrice", 0),
            }
        if path == "/fapi/v1/order" and method == "GET":
            submitted = any(
                call_path == "/fapi/v1/order"
                and call_method == "POST"
                and call_params.get("newClientOrderId") == params["origClientOrderId"]
                for call_method, call_path, call_params in self.calls[:-1]
            )
            if not submitted:
                return None
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
            return self.position_risk
        if path == "/fapi/v1/openOrders":
            return []
        if path == "/fapi/v1/openAlgoOrders":
            if self.open_algo_orders is not None:
                return self.open_algo_orders
            if not self.sl_exists:
                return []
            return [
                {
                    "symbol": params.get("symbol", "BTCUSDT"),
                    "algoId": 99,
                    "clientAlgoId": "demo-BTCUSDT-1-sl-0",
                    "side": "SELL",
                    "orderType": "STOP_MARKET",
                    "algoStatus": "NEW",
                    "quantity": "0",
                    "actualQty": "0",
                    "reduceOnly": False,
                    "triggerPrice": "95",
                }
            ]
        return {}


class FakeStorage:
    async def log(self, *args, **kwargs):
        return None


async def test_three_bot_positions_each_get_individual_protective_stop_recovery_close():
    from app.domain.models import ExchangeOrder, ExchangePosition, ExchangeSnapshot

    adapter = FakeBinanceAdapter()
    snapshot = ExchangeSnapshot(
        mode=TradingMode.DEMO,
        positions=[
            ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=0.01, entry_price=100),
            ExchangePosition(symbol="ETHUSDT", side="SHORT", quantity=0.2, entry_price=2000),
            ExchangePosition(symbol="SOLUSDT", side="LONG", quantity=1.5, entry_price=150),
        ],
        orders=[
            ExchangeOrder(
                symbol="BTCUSDT",
                order_id=1,
                client_order_id="demo-BTCUSDT-1-tp-0",
                side="SELL",
                order_type="TAKE_PROFIT_MARKET",
                status="NEW",
                stop_price=105,
            ),
            ExchangeOrder(
                symbol="ETHUSDT",
                order_id=2,
                client_order_id="demo-ETHUSDT-1-tp-0",
                side="BUY",
                order_type="TAKE_PROFIT_MARKET",
                status="NEW",
                stop_price=1900,
            ),
            ExchangeOrder(
                symbol="SOLUSDT",
                order_id=3,
                client_order_id="demo-SOLUSDT-1-tp-0",
                side="SELL",
                order_type="TAKE_PROFIT_MARKET",
                status="NEW",
                stop_price=160,
            ),
        ],
    )

    actions = await adapter.close_unprotected_bot_positions(
        snapshot, {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    )

    assert [action["symbol"] for action in actions] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    close_orders = [
        params
        for method, path, params in adapter.calls
        if method == "POST" and path == "/fapi/v1/order" and params.get("type") == "MARKET"
    ]
    assert [params["quantity"] for params in close_orders] == ["0.01", "0.2", "1.5"]
    assert [params["side"] for params in close_orders] == ["SELL", "BUY", "SELL"]


async def test_binance_demo_places_entry_sl_and_reduce_only_take_profits():
    adapter = FakeBinanceAdapter()

    result = await adapter.submit_order_plan(plan(leverage=5))

    assert result.accepted is True
    assert ("POST", "/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": 5}) in adapter.calls
    order_types = [
        params.get("type")
        for _, path, params in adapter.calls
        if path in {"/fapi/v1/order", "/fapi/v1/algoOrder"}
    ]
    assert "MARKET" in order_types
    assert "STOP_MARKET" in order_types
    assert "TAKE_PROFIT_MARKET" in order_types
    assert any(path == "/fapi/v1/algoOrder" for _, path, _ in adapter.calls)
    assert any(params.get("reduceOnly") == "true" for _, _, params in adapter.calls)


async def test_take_profit_skips_levels_that_would_immediately_trigger():
    adapter = FakeBinanceAdapter()
    adapter.position_risk = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "-0.01",
            "entryPrice": "100",
            "markPrice": "104",
            "unRealizedProfit": "0",
            "leverage": "2",
            "marginType": "isolated",
        }
    ]

    result = await adapter.submit_order_plan(
        plan(side=Side.SHORT, stop_loss=110.0, take_profits=[105.0, 103.0, 100.0])
    )

    assert result.accepted is True
    trigger_prices = [
        params.get("triggerPrice")
        for _, path, params in adapter.calls
        if path == "/fapi/v1/algoOrder" and params.get("type") == "TAKE_PROFIT_MARKET"
    ]
    assert trigger_prices == ["103", "100"]


async def test_invalid_post_entry_stop_loss_closes_without_safe_mode_alert():
    adapter = FakeBinanceAdapter()
    adapter.position_risk = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "-0.01",
            "entryPrice": "100",
            "markPrice": "111",
            "unRealizedProfit": "0",
            "leverage": "2",
            "marginType": "isolated",
        }
    ]

    result = await adapter.submit_order_plan(
        plan(side=Side.SHORT, stop_loss=110.0, take_profits=[95.0])
    )

    assert result.accepted is False
    assert result.status == "DEMO_SL_INVALID_POSITION_CLOSED"
    assert result.critical_alert is None
    assert any(
        params.get("newClientOrderId") == "demo-BTCUSDT-1-close"
        for _, path, params in adapter.calls
        if path == "/fapi/v1/order"
    )


async def test_demo_sl_failure_closes_position_and_enters_safe_mode():
    adapter = FakeBinanceAdapter()
    adapter.sl_exists = False

    result = await adapter.submit_order_plan(plan())

    assert result.accepted is False
    assert result.critical_alert is not None
    assert adapter.snapshot_cache.safe_mode is True
    assert any(
        params.get("newClientOrderId") == "demo-BTCUSDT-1-close"
        for _, path, params in adapter.calls
        if path == "/fapi/v1/order"
    )
    assert all(
        len(str(params.get("newClientOrderId") or params.get("clientAlgoId") or "")) <= 36
        for _, path, params in adapter.calls
        if path in {"/fapi/v1/order", "/fapi/v1/algoOrder"}
        and (params.get("newClientOrderId") or params.get("clientAlgoId"))
    )


async def test_live_sl_failure_closes_position_and_returns_critical_alert():
    adapter = FakeBinanceAdapter(mode=TradingMode.LIVE)
    adapter.sl_exists = False

    result = await adapter.submit_order_plan(plan())

    assert result.accepted is False
    assert result.critical_alert is not None


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


async def test_manage_stops_moves_to_break_even_after_tp1_missing():
    adapter = FakeBinanceAdapter()
    adapter.position_risk = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.006",
            "entryPrice": "100",
            "markPrice": "107",
            "unRealizedProfit": "0.042",
            "liquidationPrice": "80",
            "leverage": "5",
            "marginType": "isolated",
        }
    ]
    adapter.open_algo_orders = [
        {
            "symbol": "BTCUSDT",
            "algoId": 1,
            "clientAlgoId": "demo-BTCUSDT-1-sl-0",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "NEW",
            "quantity": "0",
            "actualQty": "0",
            "reduceOnly": False,
            "triggerPrice": "95",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 2,
            "clientAlgoId": "demo-BTCUSDT-1-tp-1",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "110",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 3,
            "clientAlgoId": "demo-BTCUSDT-1-tp-2",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "115",
        },
    ]

    actions = await adapter.manage_open_position_stops()

    assert actions[0]["new_stop"] == 100
    assert any(
        path == "/fapi/v1/algoOrder"
        and method == "POST"
        and params.get("type") == "STOP_MARKET"
        and params.get("triggerPrice") == "100"
        for method, path, params in adapter.calls
    )
    assert any(
        path == "/fapi/v1/algoOrder"
        and method == "DELETE"
        and params.get("clientAlgoId") == "demo-BTCUSDT-1-sl-0"
        for method, path, params in adapter.calls
    )


async def test_manage_stops_only_touches_bot_owned_order_group():
    adapter = FakeBinanceAdapter()
    adapter.position_risk = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.006",
            "entryPrice": "100",
            "markPrice": "107",
            "unRealizedProfit": "0.042",
            "liquidationPrice": "80",
            "leverage": "5",
            "marginType": "isolated",
        }
    ]
    adapter.open_algo_orders = [
        {
            "symbol": "BTCUSDT",
            "algoId": 1,
            "clientAlgoId": "manual-stop",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "NEW",
            "quantity": "0",
            "actualQty": "0",
            "reduceOnly": False,
            "triggerPrice": "96",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 2,
            "clientAlgoId": "demo-BTCUSDT-1-sl-0",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "NEW",
            "quantity": "0",
            "actualQty": "0",
            "reduceOnly": False,
            "triggerPrice": "95",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 3,
            "clientAlgoId": "demo-BTCUSDT-1-tp-1",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "110",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 4,
            "clientAlgoId": "demo-BTCUSDT-1-tp-2",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "115",
        },
    ]

    actions = await adapter.manage_open_position_stops()

    assert actions[0]["group_id"] == "demo-BTCUSDT-1"
    assert not any(
        path == "/fapi/v1/algoOrder"
        and method == "DELETE"
        and params.get("clientAlgoId") == "manual-stop"
        for method, path, params in adapter.calls
    )


async def test_user_stream_tp_fill_triggers_lifecycle_stop_management():
    adapter = FakeBinanceAdapter()
    adapter.position_risk = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.006",
            "entryPrice": "100",
            "markPrice": "107",
            "unRealizedProfit": "0.042",
            "liquidationPrice": "80",
            "leverage": "5",
            "marginType": "isolated",
        }
    ]
    adapter.open_algo_orders = [
        {
            "symbol": "BTCUSDT",
            "algoId": 1,
            "clientAlgoId": "demo-BTCUSDT-1-sl-0",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "NEW",
            "quantity": "0",
            "actualQty": "0",
            "reduceOnly": False,
            "triggerPrice": "95",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 2,
            "clientAlgoId": "demo-BTCUSDT-1-tp-1",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "110",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 3,
            "clientAlgoId": "demo-BTCUSDT-1-tp-2",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "115",
        },
    ]
    state = type("State", (), {"trading_mode": adapter.mode, "storage": FakeStorage()})()
    watchdog = UserStreamWatchdog(state)

    await watchdog._handle_event(
        adapter,
        {
            "e": "ORDER_TRADE_UPDATE",
            "o": {"s": "BTCUSDT", "c": "demo-BTCUSDT-1-tp-0", "X": "FILLED"},
        },
    )

    lifecycle = adapter.snapshot_cache.lifecycles[0]
    assert lifecycle.group_id == "demo-BTCUSDT-1"
    assert lifecycle.state == "TP1_HIT"
    assert any(
        path == "/fapi/v1/algoOrder"
        and method == "POST"
        and params.get("type") == "STOP_MARKET"
        and params.get("triggerPrice") == "100"
        for method, path, params in adapter.calls
    )


async def test_user_stream_event_marks_adapter_and_snapshot():
    adapter = FakeBinanceAdapter()
    state = type("State", (), {"trading_mode": adapter.mode, "storage": FakeStorage()})()
    watchdog = UserStreamWatchdog(state)

    await watchdog._handle_event(
        adapter,
        {"e": "ACCOUNT_UPDATE", "a": {"m": "ORDER"}},
    )

    assert watchdog.events == 1
    assert watchdog.last_event_at is not None
    assert adapter.snapshot_cache.last_user_stream_at == watchdog.last_event_at


async def test_manage_stops_serializes_concurrent_calls_per_symbol():
    import asyncio

    adapter = FakeBinanceAdapter()
    adapter.position_risk = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.006",
            "entryPrice": "100",
            "markPrice": "107",
            "unRealizedProfit": "0.042",
            "liquidationPrice": "80",
            "leverage": "5",
            "marginType": "isolated",
        }
    ]
    adapter.open_algo_orders = [
        {
            "symbol": "BTCUSDT",
            "algoId": 1,
            "clientAlgoId": "demo-BTCUSDT-1-sl-0",
            "side": "SELL",
            "orderType": "STOP_MARKET",
            "algoStatus": "NEW",
            "quantity": "0",
            "actualQty": "0",
            "reduceOnly": False,
            "triggerPrice": "95",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 2,
            "clientAlgoId": "demo-BTCUSDT-1-tp-1",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "110",
        },
        {
            "symbol": "BTCUSDT",
            "algoId": 3,
            "clientAlgoId": "demo-BTCUSDT-1-tp-2",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": "115",
        },
    ]
    original_place = adapter._place_managed_stop_loss

    async def delayed_place(plan, client_id):
        await asyncio.sleep(0.01)
        return await original_place(plan, client_id)

    adapter._place_managed_stop_loss = delayed_place  # type: ignore[method-assign]
    results = await asyncio.gather(
        adapter.manage_open_position_stops(), adapter.manage_open_position_stops()
    )

    posts = [
        params
        for method, path, params in adapter.calls
        if method == "POST" and path == "/fapi/v1/algoOrder" and params.get("type") == "STOP_MARKET"
    ]
    assert len(posts) == 1
    assert posts[0]["quantity"] == "0.006"
    assert sum(len(result) for result in results) == 1


async def test_manage_stops_protects_three_independent_positions():
    adapter = FakeBinanceAdapter()
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    for symbol in symbols:
        adapter._symbol_filters[symbol] = adapter._symbol_filters["BTCUSDT"].copy()
    adapter.position_risk = [
        {
            "symbol": symbol,
            "positionAmt": "0.01",
            "entryPrice": "100",
            "markPrice": "107",
            "unRealizedProfit": "0.042",
            "liquidationPrice": "80",
            "leverage": "5",
            "marginType": "isolated",
        }
        for symbol in symbols
    ]
    adapter.open_algo_orders = [
        {
            "symbol": symbol,
            "algoId": index,
            "clientAlgoId": f"demo-{symbol}-1-tp-{tp_index}",
            "side": "SELL",
            "orderType": "TAKE_PROFIT_MARKET",
            "algoStatus": "NEW",
            "quantity": "0.003",
            "actualQty": "0",
            "reduceOnly": True,
            "triggerPrice": str(110 + tp_index * 10),
        }
        for index, (symbol, tp_index) in enumerate(
            ((symbol, tp_index) for symbol in symbols for tp_index in (0, 1)),
            start=1,
        )
    ]

    actions = await adapter.manage_open_position_stops()

    stop_posts = [
        params
        for method, path, params in adapter.calls
        if method == "POST" and path == "/fapi/v1/algoOrder" and params.get("type") == "STOP_MARKET"
    ]
    assert {params["symbol"] for params in stop_posts} == set(symbols)
    assert {action["symbol"] for action in actions} == set(symbols)
    assert all(params["quantity"] == "0.01" for params in stop_posts)


async def test_redeploy_queries_exchange_before_entry_submit():
    adapter = FakeBinanceAdapter()
    existing = plan(client_order_id="a-demo-BTCUSDT-durable")
    adapter.calls.append(("POST", "/fapi/v1/order", {"newClientOrderId": existing.client_order_id}))

    result = await adapter.submit_order_plan(existing)

    assert result.status == "DEMO_DUPLICATE_ACK"
    assert (
        len([call for call in adapter.calls if call[0] == "POST" and call[1] == "/fapi/v1/order"])
        == 1
    )


async def test_uncertain_entry_query_failure_enters_safe_mode():
    adapter = FakeBinanceAdapter()

    async def fail_signed(method, path, params):
        if method == "POST" and path == "/fapi/v1/order":
            raise ExchangeError("timeout")
        if method == "GET" and path == "/fapi/v1/order" and adapter._submitted_client_ids:
            raise ExchangeError("query unavailable")
        return await FakeBinanceAdapter._signed(adapter, method, path, params)

    adapter._signed = fail_signed  # type: ignore[method-assign]

    try:
        await adapter.submit_order_plan(plan())
    except ExchangeError:
        pass

    assert adapter.snapshot_cache.safe_mode is True
    assert "Không xác định" in (adapter.snapshot_cache.safe_mode_reason or "")


async def test_duplicate_stop_losses_keep_most_protective_long_stop():
    from app.domain.models import ExchangeOrder, ExchangePosition, ExchangeSnapshot

    adapter = FakeBinanceAdapter()
    snapshot = ExchangeSnapshot(
        mode=adapter.mode,
        positions=[ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=0.01, entry_price=100)],
        orders=[
            ExchangeOrder(
                symbol="BTCUSDT",
                order_id=1,
                client_order_id="demo-x-sl-1",
                side="SELL",
                order_type="STOP_MARKET",
                status="NEW",
                stop_price=95,
            ),
            ExchangeOrder(
                symbol="BTCUSDT",
                order_id=2,
                client_order_id="demo-x-sl-2",
                side="SELL",
                order_type="STOP_MARKET",
                status="NEW",
                stop_price=97,
            ),
        ],
    )

    actions = await adapter.remove_duplicate_stop_losses(snapshot)

    assert [action["client_order_id"] for action in actions] == ["demo-x-sl-1"]


async def test_preflight_client_id_query_uncertainty_enters_safe_mode():
    adapter = FakeBinanceAdapter()

    async def fail_query(symbol, client_order_id, *, strict=False):
        raise ExchangeError("query unavailable")

    adapter.query_order = fail_query  # type: ignore[method-assign]

    try:
        await adapter.submit_order_plan(plan())
    except ExchangeError:
        pass

    assert adapter.snapshot_cache.safe_mode is True
    assert "client order id" in (adapter.snapshot_cache.safe_mode_reason or "")


async def test_successful_reconcile_clears_previous_mismatch_safe_mode():
    adapter = FakeBinanceAdapter()
    adapter.position_risk = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.01",
            "entryPrice": "100",
            "markPrice": "101",
            "unRealizedProfit": "0.01",
            "leverage": "2",
            "marginType": "isolated",
        }
    ]
    await adapter.reconcile([])
    assert adapter.snapshot_cache.safe_mode is True

    snapshot = await adapter.reconcile([{"symbol": "BTCUSDT", "status": "OPEN"}])

    assert snapshot.safe_mode is False
    assert snapshot.safe_mode_reason is None


def test_restart_recovers_only_protected_bot_managed_position():
    from types import SimpleNamespace

    from app.domain.models import ExchangeOrder, ExchangePosition, ExchangeSnapshot
    from app.services.execution import ExecutionService

    state = SimpleNamespace(execution=ExecutionService())
    watchdog = UserStreamWatchdog(state)
    snapshot = ExchangeSnapshot(
        positions=[
            ExchangePosition(symbol="BNBUSDT", side="LONG", quantity=2.71, entry_price=611.89)
        ],
        orders=[
            ExchangeOrder(
                symbol="BNBUSDT",
                order_id=1,
                client_order_id="a-demo-BNBUSDT-g-sl-0",
                side="SELL",
                order_type="STOP_MARKET",
                status="NEW",
                stop_price=605.53,
            ),
            ExchangeOrder(
                symbol="BNBUSDT",
                order_id=2,
                client_order_id="a-demo-BNBUSDT-g-tp-0",
                side="SELL",
                order_type="TAKE_PROFIT_MARKET",
                status="NEW",
                stop_price=618.3,
            ),
        ],
    )

    watchdog._restore_managed_positions(snapshot)
    watchdog._restore_managed_positions(snapshot)

    positions = state.execution.open_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BNBUSDT"
    assert positions[0].stop_loss == 605.53
    assert positions[0].take_profits == [618.3]
