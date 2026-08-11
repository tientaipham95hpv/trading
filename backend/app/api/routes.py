import asyncio
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.domain.models import BotSettings, BotState, OrderPlan, SignalAction, Timeframe, TradingMode
from app.services.app_state import state
from app.services.execution import DuplicateOrderError

router = APIRouter(prefix="/api")


@router.get("/status")
async def status() -> dict[str, object]:
    return {
        "mode": state.settings.trading_mode,
        "live_enabled": state.settings.live_trading_enabled,
        "bot_state": state.bot_state,
        "emergency_stop": state.emergency_stop.active,
        "risk": {
            "max_leverage": state.settings.max_leverage,
            "risk_per_trade": state.settings.risk_per_trade,
            "max_risk_per_trade": state.settings.max_risk_per_trade,
            "max_daily_loss": state.settings.max_daily_loss,
            "max_open_positions": state.settings.max_open_positions,
            "minimum_risk_reward": state.settings.minimum_risk_reward,
        },
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
    decision = state.risk.evaluate(
        signal,
        open_positions=len(state.execution.open_positions()),
        daily_loss_fraction=_daily_loss_fraction(),
        emergency_stop=state.emergency_stop,
        account_equity=state.execution.performance().equity,
    )
    if not decision.accepted or decision.quantity is None:
        return {"accepted": False, "reason": decision.reason}
    plan = OrderPlan(
        client_order_id=f"paper-{signal.symbol}-{uuid4()}",
        symbol=signal.symbol,
        side=signal.side,
        quantity=decision.quantity,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        leverage=signal.leverage,
        order_type=signal.order_type,
        take_profits=signal.take_profits,
        risk_fraction=signal.risk_fraction,
    )
    return await _submit_paper_order(plan)


@router.post("/orders/paper")
async def submit_paper_order(plan: OrderPlan) -> dict[str, object]:
    return await _submit_paper_order(plan)


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
    await state.storage.log("Cập nhật bot settings", settings.model_dump(mode="json"))
    return settings


@router.post("/bot/start")
async def bot_start() -> dict[str, object]:
    state.bot_state = BotState.RUNNING
    await state.storage.log("Bot PAPER đã start")
    return {"bot_state": state.bot_state}


@router.post("/bot/pause")
async def bot_pause() -> dict[str, object]:
    state.bot_state = BotState.PAUSED
    await state.storage.log("Bot PAPER đã pause")
    return {"bot_state": state.bot_state}


@router.post("/bot/stop")
async def bot_stop() -> dict[str, object]:
    state.bot_state = BotState.STOPPED
    await state.storage.log("Bot PAPER đã stop")
    return {"bot_state": state.bot_state}


@router.post("/mode/{mode}")
async def set_mode(mode: TradingMode) -> dict[str, object]:
    if mode == TradingMode.LIVE and not state.settings.live_trading_enabled:
        return {"accepted": False, "reason": "Chế độ LIVE đang bị tắt trong cấu hình"}
    return {"accepted": True, "mode": mode.value}


@router.post("/emergency-stop")
async def activate_emergency_stop(reason: str = "manual") -> dict[str, object]:
    state.emergency_stop.active = True
    state.emergency_stop.reason = reason
    await state.storage.log("Dừng khẩn cấp đã bật", {"reason": reason}, level="WARNING")
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


async def _submit_paper_order(plan: OrderPlan) -> dict[str, object]:
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
    await asyncio.sleep(0)
    return {"channel": channel, "error": "Unknown channel"}


def _daily_loss_fraction() -> float:
    realized = state.execution.performance().realized_pnl
    if realized >= 0:
        return 0.0
    return abs(realized) / state.bot_settings.paper_initial_balance
