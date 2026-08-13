from fastapi import FastAPI

from app.api.routes import router
from app.services.app_state import state

app = FastAPI(title="Trading Automation API", version="1.0.0")
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    await state.storage.init()
    state.auto_trader.start()
    state.user_stream.start()
    state.stability.start()
    state.smart_entry_collector.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await state.smart_entry_collector.stop()
    await state.stability.stop()
    await state.user_stream.stop()
    await state.auto_trader.stop()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": state.trading_mode}
