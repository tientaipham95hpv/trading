import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.domain.models import (
    BotSettings,
    BotState,
    LiveConfigUpdate,
    LiveReadiness,
    NotificationEvent,
    OrderPlan,
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
        "exchange": (state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange).snapshot_cache.model_dump(mode="json"),
        "risk": {
            "max_leverage": state.bot_settings.max_leverage,
            "risk_per_trade": state.bot_settings.risk_per_trade,
            "max_risk_per_trade": state.bot_settings.max_risk_per_trade,
            "max_daily_loss": state.bot_settings.max_daily_loss,
            "max_weekly_drawdown": state.bot_settings.max_weekly_drawdown,
            "max_open_positions": state.bot_settings.max_open_positions,
            "max_portfolio_exposure": state.bot_settings.max_portfolio_exposure,
            "max_correlated_positions": state.bot_settings.max_correlated_positions,
            "max_loss_streak": state.bot_settings.max_loss_streak,
            "minimum_risk_reward": state.bot_settings.minimum_risk_reward,
        },
        "live_readiness": _live_readiness().model_dump(mode="json"),
        "auto_trader": state.auto_trader.snapshot(),
    }


@router.get("/markets")
async def markets() -> dict[str, object]:
    return {"items": [item.model_dump() for item in await state.scanner.scan_usdm_pairs()]}


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
        return {"items": [item.model_dump(mode="json") for item in state.scanner.last_results[:limit]]}
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
    signal = await state.ai.score(signal)
    if signal.metadata.get("ai_action") == "NO_TRADE":
        return {"accepted": False, "reason": "AI trả NO_TRADE hoặc timeout"}
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
        await state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="WARNING")
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
            performance=state.execution.performance({symbol.upper(): price}).model_dump(mode="json"),
        )
        for trade in trades:
            event = NotificationEvent.TP if trade.reason == "TP" else NotificationEvent.SL if trade.reason == "SL" else NotificationEvent.POSITION_CLOSE
            notification = state.notifications.build(
                event,
                title=event.value,
                body=f"{trade.symbol} {trade.reason} {trade.net_pnl:.2f}",
                data={"symbol": trade.symbol, "reason": trade.reason},
            )
            await state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="INFO")
    return {
        "closed_trades": [item.model_dump(mode="json") for item in trades],
        "positions": [item.model_dump(mode="json") for item in state.execution.positions],
        "performance": state.execution.performance({symbol.upper(): price}).model_dump(mode="json"),
    }


@router.get("/trades")
async def trades() -> dict[str, object]:
    return {"items": [item.model_dump(mode="json") for item in state.execution.trades]}


@router.get("/logs")
async def logs(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    return {"items": await state.storage.list_payloads("logs", limit)}


@router.get("/performance")
async def performance() -> dict[str, object]:
    return state.execution.performance().model_dump(mode="json")


@router.get("/backtest")
async def backtest() -> dict[str, object]:
    metrics = state.backtest.metrics(state.execution.trades)
    return metrics.model_dump(mode="json")


@router.get("/risk")
async def risk() -> dict[str, object]:
    return (await status())["risk"]  # type: ignore[index]


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
    if mode == TradingMode.DEMO and state.safe_mode:
        return {"accepted": False, "reason": state.safe_mode_reason}
    if mode == TradingMode.LIVE and not state.live_trading_enabled:
        return {"accepted": False, "reason": "Chế độ LIVE đang bị tắt trong cấu hình"}
    if mode == TradingMode.LIVE:
        readiness = _live_readiness()
        if not readiness.allowed:
            return {"accepted": False, "reason": "; ".join(readiness.blockers)}
    state.trading_mode = mode
    state.save_runtime_config()
    await state.storage.log("Đổi trading mode", {"mode": mode.value})
    return {"accepted": True, "mode": mode.value}


@router.get("/exchange")
async def exchange_snapshot() -> dict[str, object]:
    if state.trading_mode == TradingMode.PAPER:
        return state.demo_exchange.snapshot_cache.model_dump(mode="json")
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    try:
        return (await adapter.snapshot()).model_dump(mode="json")
    except ExchangeCredentialsError as exc:
        return adapter.snapshot_cache.model_copy(
            update={"safe_mode_reason": str(exc)}
        ).model_dump(mode="json")
    except ExchangeError as exc:
        await state.storage.log("Exchange DEMO disconnected", {"error": str(exc)}, level="WARNING")
        notification = state.notifications.build(
            NotificationEvent.API_DISCONNECT,
            title="API disconnect",
            body=str(exc),
            data={"mode": state.trading_mode.value},
        )
        await state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="WARNING")
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


@router.get("/live/readiness")
async def live_readiness() -> dict[str, object]:
    return _live_readiness().model_dump(mode="json")


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
        state.trading_mode = TradingMode.PAPER
    state.save_runtime_config()
    await state.storage.log("Cập nhật LIVE runtime config", readiness.model_dump(mode="json"), level="WARNING")
    return readiness.model_dump(mode="json")


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
    await state.storage.log("Cancel Orders", {"symbol": symbol, "mode": state.trading_mode.value}, level="WARNING")
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
    await state.storage.log("Close All", {"mode": state.trading_mode.value}, level="CRITICAL")
    return {"accepted": True, "orders": [order.model_dump(mode="json") for order in orders]}


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
    await state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="CRITICAL")
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
        adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
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
            await state.storage.log(result.critical_alert, result.model_dump(mode="json"), level="CRITICAL")
            notification = state.notifications.build(
                NotificationEvent.SAFE_MODE,
                title="SAFE_MODE",
                body=result.critical_alert,
                data={"client_order_id": result.client_order_id},
            )
            await state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="CRITICAL")
        elif result.accepted:
            notification = state.notifications.build(
                NotificationEvent.POSITION_OPEN,
                title="Position open",
                body=f"{plan.symbol} {plan.side.value}",
                data={"client_order_id": plan.client_order_id, "mode": state.trading_mode.value},
            )
            await state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="INFO")
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
    await state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="INFO")
    return result


async def _channel_payload(channel: str) -> dict[str, object]:
    if channel == "market":
        return {"channel": channel, "items": [item.model_dump() for item in state.scanner.last_markets]}
    if channel == "scanner":
        return {
            "channel": channel,
            "items": [item.model_dump(mode="json") for item in state.scanner.last_results],
        }
    if channel == "positions":
        return {
            "channel": channel,
            "items": [item.model_dump(mode="json") for item in state.execution.open_positions()],
        }
    if channel == "performance":
        return {"channel": channel, "data": state.execution.performance().model_dump(mode="json")}
    if channel == "system":
        return {"channel": channel, "data": await status()}
    if channel == "exchange":
        return {"channel": channel, "data": await exchange_snapshot()}
    await asyncio.sleep(0)
    return {"channel": channel, "error": "Unknown channel"}


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
    exposure = sum(position.remaining_quantity * position.entry_price for position in state.execution.open_positions())
    return exposure / equity


def _correlated_positions(symbol: str) -> int:
    base = symbol.replace("USDT", "")
    bucket = "BTC_ETH" if base in {"BTC", "ETH"} else base[:3]
    return sum(1 for position in state.execution.open_positions() if position.symbol.replace("USDT", "")[:3] == bucket[:3])


def _loss_streak() -> int:
    streak = 0
    for trade in reversed(state.execution.trades):
        if trade.net_pnl < 0:
            streak += 1
        else:
            break
    return streak


def _live_readiness() -> LiveReadiness:
    blockers: list[str] = []
    checks = dict(state.live_preflight)
    if not state.live_trading_enabled:
        blockers.append("LIVE mặc định OFF, cần bật thủ công bằng cấu hình")
    for key, value in checks.items():
        if not value:
            blockers.append(key)
    if state.safe_mode:
        blockers.append(state.safe_mode_reason or "SAFE_MODE")
    allowed = state.live_trading_enabled and not blockers
    return LiveReadiness(live_enabled=state.live_trading_enabled, allowed=allowed, blockers=blockers, **checks)
