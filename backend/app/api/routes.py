import asyncio
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.domain.models import (
    AIShadowConfigResponse,
    AIShadowConfigUpdate,
    BacktestOptimizerRequest,
    BacktestRunRequest,
    BotSettings,
    BotState,
    ExitAnalyticsResponse,
    LiveConfigUpdate,
    LiveReadiness,
    NotificationEvent,
    OrderPlan,
    PerformanceSnapshot,
    PushDeviceRegistration,
    Timeframe,
    TradingMode,
)
from app.services.analytics_history import AnalyticsHistorySnapshot
from app.services.app_state import state
from app.services.capital_risk import capital_risk_profile_for_mode
from app.services.exchange import ExchangeCredentialsError, ExchangeError
from app.services.exit_analytics import (
    ExitAnalyticsService,
    excursion_requests,
    normalize_exchange_closes,
)

router = APIRouter(prefix="/api")


def _ai_config_response() -> AIShadowConfigResponse:
    return AIShadowConfigResponse(**state.ai_shadow_config)


@router.get("/status")
async def status() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    account_equity = max(
        adapter.snapshot_cache.balance.margin_balance or adapter.snapshot_cache.balance.available,
        0.0,
    )
    capital_profile = capital_risk_profile_for_mode(
        account_equity,
        mode=state.trading_mode.value,
        settings=state.bot_settings,
    )
    return {
        "mode": state.trading_mode,
        "live_enabled": state.live_trading_enabled,
        "bot_state": state.bot_state,
        "emergency_stop": state.emergency_stop.active,
        "safe_mode": state.safe_mode,
        "safe_mode_reason": state.safe_mode_reason,
        "exchange": adapter.snapshot_cache.model_dump(mode="json"),
        "capital_risk": capital_profile.snapshot(),
        "risk": {
            "max_leverage": capital_profile.max_leverage,
            "risk_per_trade": capital_profile.risk_per_trade,
            "max_risk_per_trade": capital_profile.max_risk_per_trade,
            "max_total_open_risk": state.bot_settings.max_total_open_risk,
            "max_margin_per_trade": capital_profile.max_margin_per_trade,
            "max_total_margin": capital_profile.max_total_margin,
            "max_daily_loss": capital_profile.max_daily_loss,
            "max_weekly_drawdown": capital_profile.max_weekly_drawdown,
            "max_open_positions": capital_profile.max_open_positions,
            "max_portfolio_exposure": capital_profile.max_portfolio_exposure,
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
    try:
        results = await asyncio.wait_for(
            state.scanner.scan(
                symbols=parsed_symbols,
                timeframes=parsed_timeframes,
                limit=limit,
            ),
            timeout=20.0,
        )
        for result in results:
            await state.storage.save_signal(result.model_dump(mode="json"))
        return {"items": [item.model_dump(mode="json") for item in results]}
    except (ExchangeError, TimeoutError, httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
        await state.storage.log(
            "Scanner dùng signal cache",
            {"mode": state.trading_mode.value, "error": str(exc)},
            level="WARNING",
        )
        if state.scanner.last_results:
            return {
                "items": [
                    item.model_dump(mode="json") for item in state.scanner.last_results[:limit]
                ],
                "degraded": True,
                "reason": str(exc),
            }
        return {
            "items": await state.storage.list_payloads("signals", limit),
            "degraded": True,
            "reason": str(exc),
        }


@router.get("/signals")
async def signals(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    if state.scanner.last_results:
        return {
            "items": [item.model_dump(mode="json") for item in state.scanner.last_results[:limit]]
        }
    return {"items": await state.storage.list_payloads("signals", limit)}


@router.get("/smart-entry")
async def smart_entry(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    from app.services.smart_entry import (
        SmartEntryAnalytics,
        SmartEntryOutcomeAnalytics,
        SmartEntryPerformanceReport,
    )

    mode = state.trading_mode.value
    items = await state.storage.smart_entry_events(mode=mode, limit=limit)
    outcomes = await state.storage.smart_entry_outcomes(
        mode=mode, decision_keys=[str(item["event_key"]) for item in items]
    )
    outcomes_by_key: dict[str, list[dict[str, object]]] = {}
    for outcome in outcomes:
        outcomes_by_key.setdefault(str(outcome["decision_event_key"]), []).append(outcome)
    for item in items:
        decision_label, decision_description = SmartEntryAnalytics.decision_presentation(
            str(item.get("decision", "WOULD_SKIP"))
        )
        item["decision_label"] = decision_label
        item["decision_description"] = decision_description
        item_outcomes = outcomes_by_key.get(str(item["event_key"]), [])
        item["outcomes"] = {
            str(horizon): next(
                (outcome for outcome in item_outcomes if int(outcome["horizon"]) == horizon),
                None,
            )
            for horizon in SmartEntryOutcomeAnalytics.HORIZONS
        }
    counts = {"WOULD_ENTER": 0, "WOULD_SKIP": 0}
    for item in items:
        decision = str(item.get("decision"))
        if decision in counts:
            counts[decision] += 1
    decision_legend = {
        decision: {
            "label": label,
            "description": description,
        }
        for decision in counts
        for label, description in [SmartEntryAnalytics.decision_presentation(decision)]
    }
    return {
        "mode": mode,
        "shadow_only": True,
        "read_only": True,
        "decision_legend": decision_legend,
        "items": items,
        "summary": {
            "total": len(items),
            **counts,
            "outcomes_available": sum(
                sum(value is not None for value in item["outcomes"].values()) for item in items
            ),
        },
        "performance": SmartEntryPerformanceReport.build(items),
        "collector": {
            **state.smart_entry_collector.snapshot(),
            "coverage": await state.storage.smart_entry_collection_coverage(mode=mode),
        },
        "note": "Smart Entry chỉ quan sát; không thay đổi Baseline hoặc gửi lệnh.",
    }


@router.get("/ai/training")
async def ai_training_status(limit: int = Query(default=500, ge=50, le=2000)) -> dict[str, object]:
    from app.services.smart_entry import SmartEntryOutcomeAnalytics, SmartEntryPerformanceReport

    mode = state.trading_mode.value
    ai_config = state.ai_shadow_config
    items = await state.storage.smart_entry_events(mode=mode, limit=limit)
    outcomes = await state.storage.smart_entry_outcomes(
        mode=mode, decision_keys=[str(item["event_key"]) for item in items]
    )
    outcomes_by_key: dict[str, list[dict[str, object]]] = {}
    for outcome in outcomes:
        outcomes_by_key.setdefault(str(outcome["decision_event_key"]), []).append(outcome)
    for item in items:
        item["outcomes"] = {
            str(horizon): next(
                (
                    outcome
                    for outcome in outcomes_by_key.get(str(item["event_key"]), [])
                    if int(outcome["horizon"]) == horizon
                ),
                None,
            )
            for horizon in SmartEntryOutcomeAnalytics.HORIZONS
        }
    report = SmartEntryPerformanceReport.build(items)
    sample = int(report["sample_size"])
    win_rate = report["overall"].get("win_rate")
    average_return = report["overall"].get("average_return")
    minimum_training_samples = int(ai_config["minimum_training_samples"])
    enough_sample = sample >= minimum_training_samples
    positive_edge = (
        isinstance(win_rate, (int, float))
        and isinstance(average_return, (int, float))
        and win_rate >= 0.52
        and average_return > 0
    )
    return {
        "mode": mode,
        "shadow_only": True,
        "execution_enabled": False,
        "model_family": str(ai_config["model"]),
        "configured_outcome_horizon": int(ai_config["outcome_horizon"]),
        "sample_size": sample,
        "minimum_sample_for_training": minimum_training_samples,
        "minimum_sample_for_execution": 1000,
        "ready_for_training": enough_sample,
        "ready_for_execution": False,
        "edge_detected": bool(enough_sample and positive_edge),
        "performance": report,
        "collector": {
            **state.smart_entry_collector.snapshot(),
            "coverage": await state.storage.smart_entry_collection_coverage(mode=mode),
        },
        "guardrails": [
            "AI không được đặt lệnh trực tiếp",
            "Chỉ dùng làm confidence/filter sau khi đủ mẫu shadow",
            "LIVE cần walk-forward + paper/shadow pass trước",
            "Execution/SL/rate-limit phải ổn định trước khi tăng quyền",
        ],
        "next_step": (
            "Thu thập thêm shadow outcomes"
            if not enough_sample
            else (
                "Có thể chạy thử confidence filter trong DEMO"
                if positive_edge
                else "Chưa có edge, tiếp tục quan sát và không đưa vào execution"
            )
        ),
    }


@router.get("/positions")
async def positions() -> dict[str, object]:
    # User stream + reconciliation maintain this snapshot. Dashboard reads must
    # not multiply signed Binance REST traffic for every connected client.
    return {"items": _exchange_positions_for_app(_current_adapter().snapshot_cache)}


@router.get("/trades")
async def trades() -> dict[str, object]:
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        adapter = _current_adapter()
        try:
            history = await _analytics_history(adapter)
            rows = history.snapshot.trades
        except (ExchangeError, TimeoutError) as exc:
            await state.storage.log(
                "Trades dùng fallback do exchange rate-limit",
                {"mode": state.trading_mode.value, "error": str(exc)},
                level="WARNING",
            )
            return {
                "items": [item.model_dump(mode="json") for item in state.execution.trades],
                "degraded": True,
                "reason": str(exc),
            }
        rows.sort(key=lambda row: int(_float(row.get("time"))), reverse=True)
        reset_at = state.performance_reset_at_for()
        if reset_at is not None:
            cutoff_ms = int(reset_at.timestamp() * 1000)
            rows = [row for row in rows if int(_float(row.get("time"))) >= cutoff_ms]
        return {
            "items": _exchange_trades_for_app(rows),
            "degraded": history.degraded,
            "reason": history.reason,
        }
    return {"items": [item.model_dump(mode="json") for item in state.execution.trades]}


@router.get("/exit-analytics", response_model=ExitAnalyticsResponse)
async def exit_analytics() -> ExitAnalyticsResponse:
    """Phân tích lịch sử thoát lệnh; chỉ đọc, không tác động execution/risk/config."""
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        adapter = _current_adapter()
        try:
            history = await _analytics_history(adapter)
            income = _income_since_reset(history.snapshot.income)
            rows = history.snapshot.trades
        except (ExchangeError, TimeoutError) as exc:
            await state.storage.log(
                "Exit analytics dùng fallback do exchange rate-limit",
                {"mode": state.trading_mode.value, "error": str(exc)},
                level="WARNING",
            )
            return ExitAnalyticsService().analyze(
                [],
                [],
                source=f"Exchange history temporarily unavailable: {exc}",
            )
        reset_at = state.performance_reset_at_for()
        if reset_at is not None:
            cutoff_ms = int(reset_at.timestamp() * 1000)
            rows = [row for row in rows if int(_float(row.get("time"))) >= cutoff_ms]
        lifecycle_events = await state.storage.lifecycle_analytics_events(
            mode=state.trading_mode.value, limit=5000
        )
        lifecycle_candles = {}
        for lifecycle_id, request in excursion_requests(lifecycle_events).items():
            symbol, interval, start_ms, end_ms, count = request
            try:
                lifecycle_candles[lifecycle_id] = await state.market_client.closed_klines_range(
                    symbol,
                    interval,
                    start_time=start_ms,
                    end_time=end_ms,
                    limit=count,
                )
            except ValueError:
                lifecycle_candles[lifecycle_id] = []
        return ExitAnalyticsService().analyze(
            normalize_exchange_closes(rows),
            income,
            lifecycle_events=lifecycle_events,
            lifecycle_candles=lifecycle_candles,
        )


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


@router.get("/equity/history")
async def equity_history(limit: int = 500) -> dict[str, object]:
    limit = max(1, min(limit, 5000))
    points = await state.equity_tracker.history(state.trading_mode.value, limit=limit)
    return {"mode": state.trading_mode.value, "points": points}


@router.get("/equity/analytics")
async def equity_analytics() -> dict[str, object]:
    return await state.equity_tracker.analytics(state.trading_mode.value)


@router.get("/performance")
async def performance() -> dict[str, object]:
    if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
        adapter = _current_adapter()
        try:
            history = await _analytics_history(adapter)
            snapshot = adapter.snapshot_cache
            income = _income_since_reset(history.snapshot.income)
        except (ExchangeError, TimeoutError) as exc:
            await state.storage.log(
                "Performance dùng exchange cache",
                {"mode": state.trading_mode.value, "error": str(exc)},
                level="WARNING",
            )
            snapshot = adapter.snapshot_cache
            income = []
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


@router.get("/ai/config", response_model=AIShadowConfigResponse)
async def get_ai_config() -> AIShadowConfigResponse:
    return _ai_config_response()


@router.put("/ai/config", response_model=AIShadowConfigResponse)
async def update_ai_config(update: AIShadowConfigUpdate) -> AIShadowConfigResponse:
    state.ai_shadow_config.update(update.model_dump(exclude_none=True))
    state.save_runtime_config()
    await state.storage.log(
        "Cập nhật AI shadow config",
        {**state.ai_shadow_config, "shadow_only": True, "execution_enabled": False},
    )
    return _ai_config_response()


@router.get("/backtest")
async def backtest() -> dict[str, object]:
    metrics = state.backtest.metrics(state.execution.trades)
    return metrics.model_dump(mode="json")


@router.post("/backtests/run")
async def run_backtest(request: BacktestRunRequest) -> dict[str, object]:
    try:
        fetch = (
            (
                lambda timeframe: state.market_client.historical_klines_days(
                    request.symbol, timeframe, request.history_days
                )
            )
            if request.history_days is not None
            else (
                lambda timeframe: state.market_client.historical_klines(
                    request.symbol, timeframe, limit=request.limit
                )
            )
        )
        candles = dict(
            zip(
                ("15m", "1h", "4h"),
                await asyncio.gather(*(fetch(frame) for frame in ("15m", "1h", "4h"))),
                strict=True,
            )
        )
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
    try:
        fetch = (
            (
                lambda timeframe: state.market_client.historical_klines_days(
                    request.run.symbol, timeframe, request.run.history_days
                )
            )
            if request.run.history_days is not None
            else (
                lambda timeframe: state.market_client.historical_klines(
                    request.run.symbol, timeframe, limit=request.run.limit
                )
            )
        )
        candles = dict(
            zip(
                ("15m", "1h", "4h"),
                await asyncio.gather(*(fetch(frame) for frame in ("15m", "1h", "4h"))),
                strict=True,
            )
        )
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
    snapshot = adapter.snapshot_cache
    symbols = sorted({item.symbol for item in snapshot.positions})
    lookback = 60
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    closed_at = now_ms - (now_ms % 900_000)
    correlation_candles = {}
    for symbol in symbols:
        try:
            correlation_candles[symbol] = await state.market_client.closed_klines(
                symbol, "15m", limit=lookback + 1, end_time=closed_at
            )
        except (ValueError, httpx.HTTPError):
            correlation_candles[symbol] = []
    portfolio = state.portfolio_risk.snapshot(
        snapshot,
        max_open_risk_fraction=state.bot_settings.max_total_open_risk,
        max_exposure_fraction=state.bot_settings.max_portfolio_exposure,
        max_symbol_exposure_fraction=state.bot_settings.max_symbol_exposure,
        max_directional_exposure_fraction=state.bot_settings.max_directional_exposure,
        max_symbol_open_risk_fraction=state.bot_settings.max_symbol_open_risk,
        correlation_candles=correlation_candles,
        correlation_lookback=lookback,
        correlation_closed_at=closed_at,
    )
    portfolio = portfolio.model_copy(
        update={
            "mode": "ENFORCED" if state.portfolio_risk_enforcement_enabled else "SHADOW",
            "enforcement_enabled": state.portfolio_risk_enforcement_enabled,
        }
    )
    return {
        "limits": (await status())["risk"],
        "portfolio": portfolio.model_dump(mode="json"),
        "audits": await state.storage.portfolio_risk_audits(25),
        "audit_summary": await state.storage.portfolio_risk_audit_summary(),
    }


@router.get("/risk/audits")
async def risk_audits(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    return {
        "items": await state.storage.portfolio_risk_audits(limit),
        "summary": await state.storage.portfolio_risk_audit_summary(),
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


@router.post("/safe-mode/reset")
async def reset_safe_mode() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    try:
        snapshot = await adapter.snapshot()
    except (ExchangeCredentialsError, ExchangeError) as exc:
        return {"accepted": False, "reason": f"Không lấy được snapshot exchange: {exc}"}

    if snapshot.safe_mode:
        return {
            "accepted": False,
            "reason": snapshot.safe_mode_reason or "Exchange vẫn đang SAFE_MODE",
        }

    unprotected = state.auto_trader._unprotected_exchange_positions(snapshot)
    if unprotected:
        return {
            "accepted": False,
            "reason": f"Vị thế chưa có SL bảo vệ: {', '.join(unprotected)}",
        }

    state.clear_safe_mode_after_verified_reconciliation()
    await state.storage.log(
        "SAFE_MODE đã reset từ dashboard",
        {"mode": state.trading_mode.value, "bot_state": state.bot_state.value},
        level="WARNING",
    )
    return {"accepted": True, "bot_state": state.bot_state}


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
    # The background user stream/watchdog and reconciliation own exchange I/O.
    # Serving their snapshot keeps web/app reads fast and prevents API fan-out.
    return _current_adapter().snapshot_cache.model_dump(mode="json")


@router.get("/exchange/gateway")
async def exchange_gateway_status() -> dict[str, object]:
    return {
        "demo": state.demo_exchange.gateway.status(),
        "live": state.live_exchange.gateway.status(),
        "market": state.market_client.gateway.status(),
    }


@router.get("/operations")
async def operations_status() -> dict[str, object]:
    mode = state.trading_mode.value
    return {
        "mode": mode,
        "gateway": {
            "demo": state.demo_exchange.gateway.status(),
            "live": state.live_exchange.gateway.status(),
            "market": state.market_client.gateway.status(),
        },
        "notifications": state.telegram_alerts.status(),
        "equity": await state.equity_tracker.analytics(mode),
        "ai_analytics": {
            "shadow_only": True,
            "read_only": True,
            "collector": state.smart_entry_collector.snapshot(),
            "training": await ai_training_status(limit=500),
        },
        "reconciliation": {
            "last_reconciled_at": state._active_exchange().snapshot_cache.last_reconciled_at,
            "safe_mode": state.safe_mode,
            "safe_mode_reason": state.safe_mode_reason,
        },
    }


@router.post("/exchange/reconcile")
async def exchange_reconcile() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
    try:
        snapshot = await state.reconciliation.reconcile(
            adapter=adapter,
            mode=state.trading_mode,
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
    else:
        state.clear_safe_mode_after_verified_reconciliation()
        await state.storage.log(
            "SAFE_MODE cleared after verified reconciliation",
            {"mode": state.trading_mode.value, "bot_state": state.bot_state.value},
            level="WARNING",
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
            notification = await state.notifications.alert(
                NotificationEvent.TP,
                title="Bảo vệ chốt lời",
                body=f"{action['symbol']} dời SL {action['old_stop']} -> {action['new_stop']}",
                data={
                    "symbol": str(action["symbol"]),
                    "mode": state.trading_mode.value,
                    "old_stop": action["old_stop"],
                    "new_stop": action["new_stop"],
                },
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
    orders = await adapter.cancel_all_orders(symbol.upper() if symbol else None)
    await state.storage.log(
        "Cancel Orders", {"symbol": symbol, "mode": state.trading_mode.value}, level="WARNING"
    )
    return {"accepted": True, "orders": [order.model_dump(mode="json") for order in orders]}


@router.post("/controls/close-all")
async def close_all() -> dict[str, object]:
    adapter = state.live_exchange if state.trading_mode == TradingMode.LIVE else state.demo_exchange
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
    notification = await state.notifications.alert(
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
    symbol = plan.symbol.upper()
    if symbol not in state.bot_settings.whitelist or symbol in state.bot_settings.blacklist:
        raise HTTPException(
            status_code=400,
            detail="Chỉ cho phép BTCUSDT, ETHUSDT, SOLUSDT trong giai đoạn kiểm chứng",
        )
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
            snapshot = await adapter.snapshot()
            if len(snapshot.positions) >= 1:
                return {"accepted": False, "reason": "Chỉ cho phép tối đa 1 vị thế đang mở"}
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
            notification = await state.notifications.alert(
                NotificationEvent.SAFE_MODE,
                title="SAFE_MODE",
                body=result.critical_alert,
                data={"client_order_id": result.client_order_id},
            )
            await state.storage.log(
                "APNs-ready notification", notification.model_dump(mode="json"), level="CRITICAL"
            )
        elif result.accepted:
            notification = await state.notifications.alert(
                NotificationEvent.POSITION_OPEN,
                title="Mở vị thế",
                body=f"{plan.symbol} {plan.side.value}",
                data={
                    "client_order_id": plan.client_order_id,
                    "mode": state.trading_mode.value,
                    "symbol": plan.symbol,
                    "side": plan.side.value,
                    "quantity": plan.quantity,
                    "entry_price": plan.entry_price,
                    "stop_loss": plan.stop_loss,
                    "take_profits": plan.take_profits,
                },
            )
            await state.storage.log(
                "APNs-ready notification", notification.model_dump(mode="json"), level="INFO"
            )
        return result.model_dump(mode="json")


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
        # WebSocket fan-out must never turn into Binance REST polling. The
        # user-stream/watchdog keeps this authoritative cache current.
        return {
            "channel": channel,
            "items": _exchange_positions_for_app(_current_adapter().snapshot_cache),
        }
    if channel == "performance":
        # Keep this legacy channel cheap. In DEMO/LIVE it must still reflect
        # the active exchange cache, not PAPER's simulation balance.
        if state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            performance = _exchange_performance(
                _current_adapter().snapshot_cache,
                [],
                initial_capital=state.performance_initial_capital_for(),
            )
            return {"channel": channel, "data": performance.model_dump(mode="json")}
        return {
            "channel": channel,
            "data": state.execution.performance().model_dump(mode="json"),
        }
    if channel == "system":
        return {"channel": channel, "data": await status()}
    if channel == "exchange":
        return {
            "channel": channel,
            "data": _current_adapter().snapshot_cache.model_dump(mode="json"),
        }
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


async def _performance_income_rows(adapter) -> list[dict[str, object]]:
    history = await _analytics_history(adapter)
    return _income_since_reset(history.snapshot.income)


async def _analytics_history(adapter):
    async def fetch() -> AnalyticsHistorySnapshot:
        income_batches = await asyncio.gather(
            *(
                asyncio.wait_for(
                    adapter.income_history(income_type=income_type, limit=500),
                    timeout=8.0,
                )
                for income_type in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE")
            )
        )
        income = [row for batch in income_batches for row in batch]
        symbols = sorted({str(row.get("symbol")) for row in income if row.get("symbol")})
        trade_batches = await asyncio.gather(
            *(
                asyncio.wait_for(adapter.trade_history(symbol, limit=500), timeout=5.0)
                for symbol in symbols
            )
        )
        return AnalyticsHistorySnapshot(
            income=income,
            trades=[row for batch in trade_batches for row in batch],
        )

    key = f"{state.trading_mode.value}:{id(adapter)}"
    return await state.analytics_history.get(key, fetch)


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
    return 0.0


def _weekly_drawdown_fraction() -> float:
    return 0.0


def _portfolio_exposure_fraction() -> float:
    return 0.0


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


@router.get("/monitoring/dashboard")
async def monitoring_dashboard() -> dict[str, object]:
    """Real-time monitoring dashboard với health checks và alerts."""
    performance = state.execution.performance()
    dashboard = state.monitoring.dashboard(performance, mode=state.trading_mode.value)

    # Thêm thông tin bổ sung
    dashboard["bot_state"] = state.bot_state.value
    dashboard["safe_mode"] = state.safe_mode
    dashboard["emergency_stop"] = state.emergency_stop.active
    dashboard["open_positions"] = len(state.execution.open_positions())

    return dashboard
