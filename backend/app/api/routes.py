import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.domain.models import (
    BacktestOptimizerRequest,
    BacktestRunRequest,
    BotSettings,
    BotState,
    LiveConfigUpdate,
    LiveReadiness,
    NotificationEvent,
    OrderPlan,
    PerformanceSnapshot,
    PushDeviceRegistration,
    SignalAction,
    Timeframe,
    TradingMode,
)
from app.services.app_state import state
from app.services.exchange import ExchangeCredentialsError, ExchangeError
from app.services.execution import DuplicateOrderError

router = APIRouter(prefix="/api")


@router.get("/status")
async def status() -> dict[str, object]:
    return {
        "mode": state.trading_mode,
        "live_enabled": state.live_trading_enabled,
        "bot_state": state.bot_state,
        "emergency_stop": state.emergency_stop.active,
        "safe_mode": state.safe_mode,
        "safe_mode_reason": state.safe_mode_reason,
        "exchange": (
            state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
        ).snapshot_cache.model_dump(mode="json"),
        "risk": {
            "max_leverage": state.bot_settings.max_leverage,
            "risk_per_trade": state.bot_settings.risk_per_trade,
            "max_risk_per_trade": state.bot_settings.max_risk_per_trade,
            "max_total_open_risk": state.bot_settings.max_total_open_risk,
            "max_margin_per_trade": state.bot_settings.max_margin_per_trade,
            "max_total_margin": state.bot_settings.max_total_margin,
            "max_daily_loss": state.bot_settings.max_daily_loss,
            "max_weekly_drawdown": state.bot_settings.max_weekly_drawdown,
            "max_open_positions": state.bot_settings.max_open_positions,
            "max_portfolio_exposure": state.bot_settings.max_portfolio_exposure,
            "max_correlated_positions": state.bot_settings.max_correlated_positions,
            "max_loss_streak": state.bot_settings.max_loss_streak,
            "minimum_risk_reward": state.bot_settings.minimum_risk_reward,
        },
        "live_readiness": _live_readiness(state.stability.last_report).model_dump(mode="json"),
        "auto_trader": state.auto_trader.snapshot(),
        "user_stream": state.user_stream.snapshot(),
        "performance_reset_at": state.performance_reset_at_for().isoformat()
        if state.performance_reset_at_for()
        else None,
    }


@router.get("/markets")
async def markets() -> dict[str, object]:
    return {"items": [item.model_dump() for item in await state.scanner.scan_usdm_pairs()]}


@router.get("/klines/{symbol}")
async def klines(
    symbol: str,
    interval: Timeframe = Timeframe.M15,
    limit: int = Query(default=180, ge=50, le=1000),
) -> dict[str, object]:
    rows = await state.market_client.klines(symbol.upper(), interval.value, limit=limit)
    return {
        "symbol": symbol.upper(),
        "interval": interval.value,
        "items": [item.model_dump(mode="json") for item in rows],
    }


@router.get("/scanner")
async def scanner(
    symbols: str | None = None,
    timeframes: str | None = None,
    limit: int = Query(default=30, ge=1, le=250),
) -> dict[str, object]:
    parsed_symbols = [item.strip().upper() for item in symbols.split(",")] if symbols else None
    parsed_timeframes = (
        [Timeframe(item.strip()) for item in timeframes.split(",")] if timeframes else None
    )
    results = await state.scanner.scan(
        symbols=parsed_symbols,
        timeframes=parsed_timeframes,
        limit=limit,
    )
    for result in results:
        await state.storage.save_signal(result.model_dump(mode="json"))
    return {"items": [item.model_dump(mode="json") for item in results]}


@router.get("/signals")
async def signals(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    if state.scanner.last_results:
        return {
            "items": [item.model_dump(mode="json") for item in state.scanner.last_results[:limit]]
        }
    return {"items": await state.storage.list_payloads("signals", limit)}


@router.post("/signals/{symbol}/paper")
async def paper_from_signal(symbol: str) -> dict[str, object]:
    result = next(
        (
            item
            for item in state.scanner.last_results
            if item.symbol == symbol.upper() and item.action != SignalAction.NO_TRADE
        ),
        None,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Không có signal đủ điểm cho symbol này")
    signal = state.scanner.signal_from_result(result)
    if signal is None:
        raise HTTPException(status_code=400, detail="Signal không hợp lệ")
    decision = state.risk.evaluate(
        signal,
        open_positions=len(state.execution.open_positions()),
        daily_loss_fraction=_daily_loss_fraction(),
        emergency_stop=state.emergency_stop,
        account_equity=state.execution.performance().equity,
        weekly_drawdown_fraction=_weekly_drawdown_fraction(),
        portfolio_exposure_fraction=_portfolio_exposure_fraction(),
        correlated_positions=_correlated_positions(signal.symbol),
        loss_streak=_loss_streak(),
        market_regime=result.regime,
        atr_fraction=(result.indicators.atr / result.price) if result.indicators.atr else None,
        data_age_seconds=max(0.0, (datetime.now(UTC) - result.scanned_at).total_seconds()),
        safe_mode=state.safe_mode,
    )
    if not decision.accepted or decision.quantity is None:
        notification = state.notifications.build(
            NotificationEvent.RISK_LIMIT,
            title="Risk limit",
            body=decision.reason or "Risk rejected",
            data={"symbol": signal.symbol},
        )
        await state.storage.log(
            "APNs-ready notification", notification.model_dump(mode="json"), level="WARNING"
        )
        return {"accepted": False, "reason": decision.reason}
    plan = OrderPlan(
        client_order_id=f"{state.trading_mode.value.lower()}-{signal.symbol}-{uuid4()}",
        symbol=signal.symbol,
        side=signal.side,
        quantity=state.position_sizer.apply(decision),
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        leverage=signal.leverage,
        order_type=signal.order_type,
        take_profits=signal.take_profits,
        risk_fraction=signal.risk_fraction,
    )
    try:
        state.order_validator.validate(plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await _submit_order(plan)


@router.post("/orders/paper")
async def submit_paper_order(plan: OrderPlan) -> dict[str, object]:
    return await _submit_order(plan)


@router.get("/positions")
async def positions() -> dict[str, object]:
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        snapshot = await _current_exchange_snapshot()
        return {"items": _exchange_positions_for_app(snapshot)}
    return {"items": [item.model_dump(mode="json") for item in state.execution.positions]}


@router.post("/positions/mark/{symbol}")
async def mark_position(symbol: str, price: float) -> dict[str, object]:
    before_trades = len(state.execution.trades)
    trades = state.execution.update_market_price(symbol.upper(), price)
    if trades:
        await state.storage.save_order_bundle(
            order={
                "client_order_id": f"mark-{symbol}-{before_trades}-{uuid4()}",
                "symbol": symbol.upper(),
                "status": "MARK_UPDATE",
            },
            fills=[item.model_dump(mode="json") for item in state.execution.fills],
            positions=[item.model_dump(mode="json") for item in state.execution.positions],
            trades=[item.model_dump(mode="json") for item in trades],
            performance=state.execution.performance({symbol.upper(): price}).model_dump(
                mode="json"
            ),
        )
        for trade in trades:
            event = (
                NotificationEvent.TP
                if trade.reason == "TP"
                else NotificationEvent.SL
                if trade.reason == "SL"
                else NotificationEvent.POSITION_CLOSE
            )
            notification = state.notifications.build(
                event,
                title=event.value,
                body=f"{trade.symbol} {trade.reason} {trade.net_pnl:.2f}",
                data={"symbol": trade.symbol, "reason": trade.reason},
            )
            await state.storage.log(
                "APNs-ready notification", notification.model_dump(mode="json"), level="INFO"
            )
    return {
        "closed_trades": [item.model_dump(mode="json") for item in trades],
        "positions": [item.model_dump(mode="json") for item in state.execution.positions],
        "performance": state.execution.performance({symbol.upper(): price}).model_dump(mode="json"),
    }


@router.get("/trades")
async def trades() -> dict[str, object]:
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        adapter = _current_adapter()
        income_rows = await adapter.income_history(income_type="REALIZED_PNL", limit=1000)
        symbols = sorted({str(row.get("symbol") or "") for row in income_rows if row.get("symbol")})
        rows = []
        for symbol in symbols:
            rows.extend(await adapter.trade_history(symbol, limit=1000))
        rows.sort(key=lambda row: int(_float(row.get("time"))), reverse=True)
        reset_at = state.performance_reset_at_for()
        if reset_at is not None:
            cutoff_ms = int(reset_at.timestamp() * 1000)
            rows = [row for row in rows if int(_float(row.get("time"))) >= cutoff_ms]
        return {"items": _exchange_trades_for_app(rows)}
    return {"items": [item.model_dump(mode="json") for item in state.execution.trades]}


@router.get("/logs")
async def logs(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    return {"items": await state.storage.list_payloads("logs", limit)}


@router.post("/notifications/devices")
async def register_push_device(device: PushDeviceRegistration) -> dict[str, object]:
    masked = f"{device.token[:8]}...{device.token[-6:]}"
    await state.storage.log(
        "Registered push notification device",
        {"platform": device.platform, "token": masked},
        level="INFO",
    )
    return {"accepted": True, "platform": device.platform}


@router.get("/performance")
async def performance() -> dict[str, object]:
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        adapter = _current_adapter()
        snapshot = await adapter.snapshot()
        income = await adapter.income_history(limit=200)
        income = _income_since_reset(income)
        performance = _exchange_performance(
            snapshot, income, initial_capital=state.performance_initial_capital_for()
        )
        if state.performance_initial_capital_for() is None:
            state.performance_initial_capital_by_mode[state.trading_mode] = (
                performance.initial_capital
            )
            state.save_runtime_config()
        return performance.model_dump(mode="json")
    return state.execution.performance().model_dump(mode="json")


@router.get("/backtest")
async def backtest() -> dict[str, object]:
    metrics = state.backtest.metrics(state.execution.trades)
    return metrics.model_dump(mode="json")


@router.post("/backtests/run")
async def run_backtest(request: BacktestRunRequest) -> dict[str, object]:
    candles = await state.market_client.historical_klines(
        request.symbol.upper(), request.interval.value, limit=request.limit
    )
    try:
        report = state.backtest.run(candles, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report.model_dump(mode="json")


@router.get("/backtests/latest")
async def latest_backtest() -> dict[str, object]:
    if state.backtest.latest is None:
        raise HTTPException(status_code=404, detail="Chưa có kết quả backtest")
    return state.backtest.latest.model_dump(mode="json")


@router.post("/backtests/optimize")
async def optimize_backtest(request: BacktestOptimizerRequest) -> dict[str, object]:
    candles = await state.market_client.historical_klines(
        request.run.symbol.upper(), request.run.interval.value, limit=request.run.limit
    )
    try:
        report = await asyncio.to_thread(state.backtest.optimize, candles, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report.model_dump(mode="json")

@router.get("/backtests/optimizer/latest")
async def latest_backtest_optimizer() -> dict[str, object]:
    if state.backtest.latest_optimizer is None:
        raise HTTPException(status_code=404, detail="Chưa có kết quả optimizer")
    return state.backtest.latest_optimizer.model_dump(mode="json")

@router.post("/performance/reset")
async def reset_performance() -> dict[str, object]:
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        snapshot = await _current_adapter().snapshot()
        initial_capital = snapshot.balance.balance
    else:
        initial_capital = state.execution.performance().balance
    reset_at = datetime.now(UTC)
    state.set_performance_baseline(state.trading_mode, reset_at, initial_capital)
    state.save_runtime_config()
    await state.storage.log(
        "Reset mốc đo hiệu suất",
        {
            "mode": state.trading_mode.value,
            "performance_reset_at": reset_at.isoformat(),
            "initial_capital": initial_capital,
        },
        level="WARNING",
    )
    return {
        "accepted": True,
        "mode": state.trading_mode.value,
        "performance_reset_at": reset_at.isoformat(),
        "initial_capital": initial_capital,
    }


@router.get("/risk")
async def risk() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    portfolio = state.portfolio_risk.snapshot(
        adapter.snapshot_cache,
        max_open_risk_fraction=state.bot_settings.max_total_open_risk,
        max_exposure_fraction=state.bot_settings.max_portfolio_exposure,
    )
    return {
        "limits": (await status())["risk"],
        "portfolio": portfolio.model_dump(mode="json"),
    }


@router.get("/settings")
async def get_settings() -> BotSettings:
    return state.bot_settings


@router.put("/settings")
async def update_settings(settings: BotSettings) -> BotSettings:
    state.bot_settings = settings
    state.scanner.settings = settings
    state.execution.settings = settings
    state.risk.max_leverage = settings.max_leverage
    state.risk.risk_per_trade = settings.risk_per_trade
    state.risk.max_risk_per_trade = settings.max_risk_per_trade
    state.risk.max_total_open_risk = settings.max_total_open_risk
    state.risk.max_margin_per_trade = settings.max_margin_per_trade
    state.risk.max_total_margin = settings.max_total_margin
    state.risk.max_daily_loss = settings.max_daily_loss
    state.risk.max_weekly_drawdown = settings.max_weekly_drawdown
    state.risk.max_open_positions = settings.max_open_positions
    state.risk.max_portfolio_exposure = settings.max_portfolio_exposure
    state.risk.max_correlated_positions = settings.max_correlated_positions
    state.risk.max_loss_streak = settings.max_loss_streak
    state.risk.extreme_volatility_atr_fraction = settings.extreme_volatility_atr_fraction
    state.risk.stale_data_seconds = settings.stale_data_seconds
    state.risk.minimum_risk_reward = settings.minimum_risk_reward
    await state.storage.log("Cập nhật bot settings", settings.model_dump(mode="json"))
    return settings


@router.post("/bot/start")
async def bot_start() -> dict[str, object]:
    if state.safe_mode:
        return {"bot_state": state.bot_state, "accepted": False, "reason": state.safe_mode_reason}
    state.bot_state = BotState.RUNNING
    await state.storage.log("Bot đã start", {"mode": state.trading_mode.value})
    return {"bot_state": state.bot_state}


@router.post("/bot/auto/run-once")
async def bot_auto_run_once() -> dict[str, object]:
    return await state.auto_trader.run_once()


@router.post("/bot/pause")
async def bot_pause() -> dict[str, object]:
    state.bot_state = BotState.PAUSED
    await state.storage.log("Bot đã pause", {"mode": state.trading_mode.value})
    return {"bot_state": state.bot_state}


@router.post("/bot/stop")
async def bot_stop() -> dict[str, object]:
    state.bot_state = BotState.STOPPED
    await state.storage.log("Bot đã stop", {"mode": state.trading_mode.value})
    return {"bot_state": state.bot_state}


@router.post("/mode/{mode}")
async def set_mode(mode: TradingMode) -> dict[str, object]:
    if mode == TradingMode.PAPER:
        return {"accepted": False, "reason": "PAPER đã tắt khỏi production, dùng DEMO hoặc LIVE"}
    if mode == TradingMode.DEMO and state.safe_mode:
        return {"accepted": False, "reason": state.safe_mode_reason}
    if mode == TradingMode.LIVE and not state.live_trading_enabled:
        return {"accepted": False, "reason": "Chế độ LIVE đang bị tắt trong cấu hình"}
    if mode == TradingMode.LIVE:
        readiness = _live_readiness()
        if not readiness.allowed:
            return {"accepted": False, "reason": "; ".join(readiness.blockers)}
        if state.performance_reset_at_for(TradingMode.LIVE) is None:
            snapshot = await state.live_exchange.snapshot()
            state.set_performance_baseline(
                TradingMode.LIVE, datetime.now(UTC), snapshot.balance.balance
            )
    state.trading_mode = mode
    state.save_runtime_config()
    await state.storage.log("Đổi trading mode", {"mode": mode.value})
    return {"accepted": True, "mode": mode.value}


@router.get("/exchange")
async def exchange_snapshot() -> dict[str, object]:
    if state.trading_mode == TradingMode.PAPER:
        return state.demo_exchange.snapshot_cache.model_dump(mode="json")
    adapter = _current_adapter()
    try:
        return (await adapter.snapshot()).model_dump(mode="json")
    except ExchangeCredentialsError as exc:
        return adapter.snapshot_cache.model_copy(update={"safe_mode_reason": str(exc)}).model_dump(
            mode="json"
        )
    except ExchangeError as exc:
        await state.storage.log("Exchange DEMO disconnected", {"error": str(exc)}, level="WARNING")
        notification = state.notifications.build(
            NotificationEvent.API_DISCONNECT,
            title="API disconnect",
            body=str(exc),
            data={"mode": state.trading_mode.value},
        )
        await state.storage.log(
            "APNs-ready notification", notification.model_dump(mode="json"), level="WARNING"
        )
        return adapter.snapshot_cache.model_copy(
            update={"connection": "STALE", "safe_mode_reason": str(exc)}
        ).model_dump(mode="json")


@router.post("/exchange/reconcile")
async def exchange_reconcile() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    try:
        snapshot = await adapter.reconcile(
            [position.model_dump(mode="json") for position in state.execution.open_positions()]
        )
    except ExchangeCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if snapshot.safe_mode:
        state.enter_safe_mode(snapshot.safe_mode_reason or "Exchange mismatch")
        await state.storage.log(
            "SAFE_MODE do reconcile mismatch", snapshot.model_dump(mode="json"), level="CRITICAL"
        )
    return snapshot.model_dump(mode="json")


@router.post("/exchange/user-stream")
async def exchange_user_stream() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    try:
        url = await adapter.open_user_stream()
    except ExchangeCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"stream_url": url}


@router.post("/exchange/manage-stops")
async def exchange_manage_stops() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    try:
        actions = await adapter.manage_open_position_stops()
    except ExchangeCredentialsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if actions:
        await state.storage.log(
            "Exchange managed protective stops",
            {"mode": state.trading_mode.value, "actions": actions},
            level="WARNING",
        )
        for action in actions:
            notification = state.notifications.build(
                NotificationEvent.TP,
                title="TP protection",
                body=f"{action['symbol']} dời SL {action['old_stop']} -> {action['new_stop']}",
                data={"symbol": str(action["symbol"]), "mode": state.trading_mode.value},
            )
            await state.storage.log(
                "APNs-ready notification", notification.model_dump(mode="json"), level="INFO"
            )
    return {"accepted": True, "actions": actions}


@router.get("/demo/stability")
async def demo_stability() -> dict[str, object]:
    report = await state.stability.report()
    return {
        **report.model_dump(mode="json"),
        "incidents": await state.storage.list_incidents(limit=30),
        "history": await state.storage.stability_history(limit=30),
    }


@router.get("/live/readiness")
async def live_readiness() -> dict[str, object]:
    report = await state.stability.report()
    return _live_readiness(report).model_dump(mode="json")


@router.put("/live/config")
async def update_live_config(update: LiveConfigUpdate) -> dict[str, object]:
    if update.live_enabled is not None:
        state.live_trading_enabled = update.live_enabled
    for key in state.live_preflight:
        value = getattr(update, key)
        if value is not None:
            state.live_preflight[key] = value
    readiness = _live_readiness()
    if not readiness.allowed and state.trading_mode == TradingMode.LIVE:
        state.trading_mode = TradingMode.DEMO
    state.save_runtime_config()
    await state.storage.log(
        "Cập nhật LIVE runtime config", readiness.model_dump(mode="json"), level="WARNING"
    )
    return readiness.model_dump(mode="json")


@router.post("/live/prepare")
async def prepare_live() -> dict[str, object]:
    if state.safe_mode:
        return {"accepted": False, "reason": state.safe_mode_reason or "SAFE_MODE đang bật"}
    demo_snapshot = await state.demo_exchange.snapshot()
    if demo_snapshot.connection != "CONNECTED":
        return {"accepted": False, "reason": "DEMO exchange chưa CONNECTED"}
    if demo_snapshot.positions or demo_snapshot.orders:
        return {
            "accepted": False,
            "reason": "Cần đóng sạch DEMO positions/orders trước khi chuẩn bị LIVE",
            "orders": len(demo_snapshot.orders),
            "positions": len(demo_snapshot.positions),
        }
    report = await state.stability.report()
    if report.verdict != "READY":
        return {
            "accepted": False,
            "reason": "DEMO stability chưa đủ điều kiện tự động",
            "stability": report.model_dump(mode="json"),
        }
    state.live_trading_enabled = True
    readiness = _live_readiness(report)
    state.save_runtime_config()
    await state.storage.log(
        "Chuẩn bị LIVE sau auto-check", readiness.model_dump(mode="json"), level="WARNING"
    )
    return {"accepted": readiness.allowed, "readiness": readiness.model_dump(mode="json")}


@router.post("/controls/pause-new-trades")
async def pause_new_trades() -> dict[str, object]:
    state.bot_state = BotState.PAUSED
    await state.storage.log("Pause New Trades", {"mode": state.trading_mode.value}, level="WARNING")
    return {"accepted": True, "bot_state": state.bot_state}


@router.post("/controls/cancel-orders")
async def cancel_orders(symbol: str | None = None) -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    if state.trading_mode == TradingMode.PAPER:
        orders = state.execution.cancel_open_orders()
        return {"accepted": True, "orders": [order.model_dump(mode="json") for order in orders]}
    orders = await adapter.cancel_all_orders(symbol.upper() if symbol else None)
    await state.storage.log(
        "Cancel Orders", {"symbol": symbol, "mode": state.trading_mode.value}, level="WARNING"
    )
    return {"accepted": True, "orders": [order.model_dump(mode="json") for order in orders]}


@router.post("/controls/close-all")
async def close_all() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    if state.trading_mode == TradingMode.PAPER:
        trades = state.execution.close_all_positions()
        return {
            "accepted": True,
            "trades": [trade.model_dump(mode="json") for trade in trades],
            "positions": [item.model_dump(mode="json") for item in state.execution.positions],
        }
    orders = await adapter.close_all_positions()
    canceled_orders = await adapter.cancel_all_orders()
    await state.storage.log("Close All", {"mode": state.trading_mode.value}, level="CRITICAL")
    return {
        "accepted": True,
        "orders": [order.model_dump(mode="json") for order in orders],
        "canceled_orders": [order.model_dump(mode="json") for order in canceled_orders],
    }


@router.post("/emergency-stop")
async def activate_emergency_stop(reason: str = "manual") -> dict[str, object]:
    state.emergency_stop.active = True
    state.emergency_stop.reason = reason
    await state.storage.log("Dừng khẩn cấp đã bật", {"reason": reason}, level="WARNING")
    notification = state.notifications.build(
        NotificationEvent.EMERGENCY_STOP,
        title="Emergency Stop",
        body=reason,
        data={"mode": state.trading_mode.value},
    )
    await state.storage.log(
        "APNs-ready notification", notification.model_dump(mode="json"), level="CRITICAL"
    )
    return state.emergency_stop.model_dump()


@router.post("/emergency-stop/reset")
async def reset_emergency_stop() -> dict[str, object]:
    state.emergency_stop.active = False
    state.emergency_stop.reason = None
    await state.storage.log("Dừng khẩn cấp đã reset")
    return state.emergency_stop.model_dump()


@router.websocket("/ws/{channel}")
async def websocket_channel(websocket: WebSocket, channel: str) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await _channel_payload(channel))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


async def _submit_order(plan: OrderPlan) -> dict[str, object]:
    try:
        state.order_validator.validate(plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if state.safe_mode:
        return {"accepted": False, "reason": state.safe_mode_reason or "SAFE_MODE đang bật"}
    if state.trading_mode == TradingMode.LIVE:
        readiness = _live_readiness()
        if not readiness.allowed:
            return {"accepted": False, "reason": "; ".join(readiness.blockers)}
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        adapter = (
            state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
        )
        try:
            result = await adapter.submit_order_plan(plan)
        except ExchangeCredentialsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ExchangeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if "DUPLICATE_ACK" not in result.status:
            await state.storage.save_order_bundle(
                order=result.order,
                fills=result.fills,
                positions=result.positions,
                trades=result.trades,
                performance=state.execution.performance().model_dump(mode="json"),
            )
        if result.critical_alert:
            state.enter_safe_mode(result.critical_alert)
            await state.storage.log(
                result.critical_alert, result.model_dump(mode="json"), level="CRITICAL"
            )
            notification = state.notifications.build(
                NotificationEvent.SAFE_MODE,
                title="SAFE_MODE",
                body=result.critical_alert,
                data={"client_order_id": result.client_order_id},
            )
            await state.storage.log(
                "APNs-ready notification", notification.model_dump(mode="json"), level="CRITICAL"
            )
        elif result.accepted:
            notification = state.notifications.build(
                NotificationEvent.POSITION_OPEN,
                title="Position open",
                body=f"{plan.symbol} {plan.side.value}",
                data={"client_order_id": plan.client_order_id, "mode": state.trading_mode.value},
            )
            await state.storage.log(
                "APNs-ready notification", notification.model_dump(mode="json"), level="INFO"
            )
        return result.model_dump(mode="json")

    try:
        before_fills = len(state.execution.fills)
        before_trades = len(state.execution.trades)
        result = await state.execution.submit_order_plan(plan)
    except DuplicateOrderError as exc:
        raise HTTPException(status_code=409, detail="Trùng client_order_id") from exc
    new_fills = [item.model_dump(mode="json") for item in state.execution.fills[before_fills:]]
    new_trades = [item.model_dump(mode="json") for item in state.execution.trades[before_trades:]]
    await state.storage.save_order_bundle(
        order=result["order"],  # type: ignore[arg-type]
        fills=new_fills,
        positions=[item.model_dump(mode="json") for item in state.execution.positions],
        trades=new_trades,
        performance=state.execution.performance().model_dump(mode="json"),
    )
    notification = state.notifications.build(
        NotificationEvent.POSITION_OPEN,
        title="Position open",
        body=f"{plan.symbol} {plan.side.value}",
        data={"client_order_id": plan.client_order_id, "mode": state.trading_mode.value},
    )
    await state.storage.log(
        "APNs-ready notification", notification.model_dump(mode="json"), level="INFO"
    )
    return result


async def _channel_payload(channel: str) -> dict[str, object]:
    if channel == "market":
        return {
            "channel": channel,
            "items": [item.model_dump() for item in state.scanner.last_markets],
        }
    if channel == "scanner":
        return {
            "channel": channel,
            "items": [item.model_dump(mode="json") for item in state.scanner.last_results],
        }
    if channel == "positions":
        if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            return {
                "channel": channel,
                "items": _exchange_positions_for_app(await _current_exchange_snapshot()),
            }
        return {
            "channel": channel,
            "items": [item.model_dump(mode="json") for item in state.execution.open_positions()],
        }
    if channel == "performance":
        if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            adapter = _current_adapter()
            snapshot = await adapter.snapshot()
            income = await adapter.income_history(limit=200)
            income = _income_since_reset(income)
            return {
                "channel": channel,
                "data": _exchange_performance(snapshot, income).model_dump(mode="json"),
            }
        return {"channel": channel, "data": state.execution.performance().model_dump(mode="json")}
    if channel == "system":
        return {"channel": channel, "data": await status()}
    if channel == "exchange":
        return {"channel": channel, "data": await exchange_snapshot()}
    await asyncio.sleep(0)
    return {"channel": channel, "error": "Unknown channel"}


def _current_adapter():
    return state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange


async def _current_exchange_snapshot():
    return await _current_adapter().snapshot()


def _exchange_positions_for_app(snapshot) -> list[dict[str, object]]:
    orders_by_symbol: dict[str, list] = {}
    for order in snapshot.orders:
        orders_by_symbol.setdefault(order.symbol, []).append(order)
    rows: list[dict[str, object]] = []
    for position in snapshot.positions:
        orders = orders_by_symbol.get(position.symbol, [])
        stop_loss = next(
            (
                order.stop_price
                for order in orders
                if order.stop_price
                and "STOP" in order.order_type
                and "TAKE_PROFIT" not in order.order_type
            ),
            0.0,
        )
        take_profits = sorted(
            [
                float(order.stop_price)
                for order in orders
                if order.stop_price and "TAKE_PROFIT" in order.order_type
            ],
            reverse=position.side == "SHORT",
        )
        break_even_active = bool(stop_loss) and abs(float(stop_loss) - position.entry_price) <= 1e-9
        trailing_stop_active = bool(stop_loss) and (
            (position.side == "LONG" and float(stop_loss) > position.entry_price + 1e-9)
            or (position.side == "SHORT" and float(stop_loss) < position.entry_price - 1e-9)
        )
        rows.append(
            {
                "id": f"exchange-{position.symbol}-{position.side}",
                "symbol": position.symbol,
                "side": position.side,
                "status": "OPEN",
                "quantity": position.quantity,
                "remaining_quantity": position.quantity,
                "entry_price": position.entry_price,
                "mark_price": position.mark_price,
                "stop_loss": stop_loss,
                "take_profits": take_profits,
                "realized_pnl": 0.0,
                "unrealized_pnl": position.unrealized_pnl,
                "fees_paid": 0.0,
                "funding_paid": 0.0,
                "break_even_active": break_even_active,
                "trailing_stop_active": trailing_stop_active,
                "liquidation_price": position.liquidation_price,
                "leverage": position.leverage,
                "margin_type": position.margin_type,
            }
        )
    return rows


def _exchange_trades_for_app(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    trades: list[dict[str, object]] = []
    for item in rows:
        pnl = _float(item.get("realizedPnl", item.get("income")))
        if abs(pnl) <= 1e-12:
            continue
        timestamp = int(_float(item.get("time")))
        quantity = _float(item.get("qty"))
        exit_price = _float(item.get("price"))
        order_side = str(item.get("side") or "")
        side = "LONG" if order_side == "SELL" else "SHORT" if order_side == "BUY" else "CLOSED"
        entry_price = 0.0
        if quantity > 0 and exit_price > 0:
            entry_price = (
                exit_price - pnl / quantity if side == "LONG" else exit_price + pnl / quantity
            )
        client_id = str(item.get("clientOrderId") or "").lower()
        reason = (
            "Chạm Stop Loss"
            if any(tag in client_id for tag in ("-sl-", "-be-", "-lock-", "-repair-"))
            else "Chốt lời theo mục tiêu"
            if "-tp-" in client_id
            else "Đóng vị thế thủ công hoặc theo thị trường"
        )
        fee = abs(_float(item.get("commission")))
        trades.append(
            {
                "id": str(
                    item.get("id") or item.get("tradeId") or f"{item.get('symbol')}-{timestamp}"
                ),
                "symbol": str(item.get("symbol") or "-"),
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "gross_pnl": pnl,
                "fee": fee,
                "slippage": 0.0,
                "funding": 0.0,
                "net_pnl": pnl - fee,
                "reason": reason,
                "created_at": datetime.fromtimestamp(timestamp / 1000, UTC).isoformat()
                if timestamp
                else datetime.now(UTC).isoformat(),
            }
        )
    return trades


def _exchange_performance(
    snapshot,
    income_rows: list[dict[str, object]],
    *,
    initial_capital: float | None = None,
) -> PerformanceSnapshot:
    realized_rows = [row for row in income_rows if row.get("incomeType") == "REALIZED_PNL"]
    realized_values = [_float(row.get("income")) for row in realized_rows]
    realized = sum(realized_values)
    fees = abs(
        sum(
            _float(row.get("income"))
            for row in income_rows
            if row.get("incomeType") == "COMMISSION"
        )
    )
    funding = sum(
        _float(row.get("income")) for row in income_rows if row.get("incomeType") == "FUNDING_FEE"
    )
    wins = sum(1 for value in realized_values if value > 0)
    loss_count = sum(1 for value in realized_values if value < 0)
    breakeven_count = sum(1 for value in realized_values if value == 0)
    losses = [value for value in realized_values if value < 0]
    gains = [value for value in realized_values if value > 0]
    total = len(realized_values)
    gross_loss = abs(sum(losses))
    equity_curve = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in reversed(realized_values):
        equity_curve += value
        peak = max(peak, equity_curve)
        max_drawdown = max(max_drawdown, peak - equity_curve)
    expectancy = realized / total if total else 0.0
    balance = snapshot.balance.balance
    equity = snapshot.balance.margin_balance or balance
    net_pnl = sum(_float(row.get("income")) for row in income_rows)
    initial_capital = initial_capital if initial_capital is not None else balance - net_pnl
    equity_pnl = equity - initial_capital
    return_percent = (net_pnl / initial_capital * 100) if initial_capital else 0.0
    equity_return_percent = (equity_pnl / initial_capital * 100) if initial_capital else 0.0
    return PerformanceSnapshot(
        balance=balance,
        equity=equity,
        initial_capital=initial_capital,
        net_pnl=net_pnl,
        equity_pnl=equity_pnl,
        return_percent=return_percent,
        equity_return_percent=equity_return_percent,
        realized_pnl=realized,
        unrealized_pnl=snapshot.balance.unrealized_pnl,
        fees_paid=fees,
        funding_paid=funding,
        win_rate=(wins / total) if total else 0.0,
        total_trades=total,
        winning_trades=wins,
        losing_trades=loss_count,
        breakeven_trades=breakeven_count,
        open_positions=len(snapshot.positions),
        profit_factor=(sum(gains) / gross_loss) if gross_loss > 0 else (999.0 if gains else 0.0),
        max_drawdown=max_drawdown,
        sharpe=0.0,
        sortino=0.0,
        expectancy=expectancy,
    )


def _income_since_reset(income_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    reset_at = state.performance_reset_at_for()
    if reset_at is None:
        return income_rows
    cutoff_ms = int(reset_at.timestamp() * 1000)
    return [row for row in income_rows if int(_float(row.get("time"))) >= cutoff_ms]


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _daily_loss_fraction() -> float:
    realized = state.execution.performance().realized_pnl
    if realized >= 0:
        return 0.0
    return abs(realized) / state.bot_settings.paper_initial_balance


def _weekly_drawdown_fraction() -> float:
    performance = state.execution.performance()
    if state.bot_settings.paper_initial_balance <= 0:
        return 0.0
    return performance.max_drawdown / state.bot_settings.paper_initial_balance


def _portfolio_exposure_fraction() -> float:
    equity = max(state.execution.performance().equity, 1.0)
    exposure = sum(
        position.remaining_quantity * position.entry_price
        for position in state.execution.open_positions()
    )
    return exposure / equity


def _correlated_positions(symbol: str) -> int:
    base = symbol.replace("USDT", "")
    bucket = "BTC_ETH" if base in {"BTC", "ETH"} else base[:3]
    return sum(
        1
        for position in state.execution.open_positions()
        if position.symbol.replace("USDT", "")[:3] == bucket[:3]
    )


def _loss_streak() -> int:
    streak = 0
    for trade in reversed(state.execution.trades):
        if trade.net_pnl < 0:
            streak += 1
        else:
            break
    return streak


def _live_readiness(report: object | None = None) -> LiveReadiness:
    blockers: list[str] = []
    checks = dict(state.live_preflight)
    if report is not None:
        report_checks = report.checks
        checks.update(
            {
                "all_tests_pass": checks["all_tests_pass"],
                "demo_stable": report.verdict == "READY",
                "sl_protection_pass": report_checks["sl_protection"].passed,
                "reconnect_pass": report_checks["user_stream"].passed,
                "reconciliation_pass": report_checks["reconciliation"].passed,
                "duplicate_order_tests_pass": report_checks["duplicate_orders"].passed
                and report_checks["order_ownership"].passed,
            }
        )
    if not state.live_trading_enabled:
        blockers.append("LIVE mặc định OFF, cần bật thủ công bằng cấu hình")
    for key, value in checks.items():
        if not value:
            blockers.append(key)
    if state.safe_mode:
        blockers.append(state.safe_mode_reason or "SAFE_MODE")
    allowed = state.live_trading_enabled and not blockers
    return LiveReadiness(
        live_enabled=state.live_trading_enabled, allowed=allowed, blockers=blockers, **checks
    )
