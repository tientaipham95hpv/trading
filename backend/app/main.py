from fastapi import FastAPI

from app.api.routes import auth_router, configure_realtime, router
from app.services.app_state import state
from app.services.exchange import ExchangeError

app = FastAPI(title="Trading Automation API", version="1.0.0")
app.include_router(auth_router)
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    if state.settings.app_env.lower() == "production" and not state.settings.api_auth_token.strip():
        raise RuntimeError("API_AUTH_TOKEN bắt buộc trong production")
    await state.storage.init()
    adapter = state.live_exchange if state.trading_mode.value == "LIVE" else state.demo_exchange
    if adapter.configured:
        try:
            await state.user_stream._reconcile_after_connect(adapter)
        except ExchangeError as exc:  # keep API observable, but lock entries on uncertain recovery
            state.enter_safe_mode(f"Startup reconcile không chắc chắn: {exc}")
            await state.storage.log(
                "Startup reconciliation entered SAFE_MODE",
                {"error": str(exc)},
                level="CRITICAL",
            )
    state.auto_trader.start()
    state.user_stream.start()
    state.stability.start()
    state.smart_entry_collector.start()
    state.equity_tracker.start()
    state.telegram_alerts.start(
        command_handler=state.handle_telegram_command,
        daily_report_provider=state.telegram_forward_test_report,
    )
    configure_realtime()
    await state.realtime.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await state.realtime.stop()
    await state.telegram_alerts.stop()
    await state.equity_tracker.stop()
    await state.smart_entry_collector.stop()
    await state.stability.stop()
    await state.user_stream.stop()
    await state.auto_trader.stop()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": state.trading_mode}
