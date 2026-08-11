from fastapi import FastAPI

from app.api.routes import router
from app.services.app_state import state

app = FastAPI(title="Trading Automation API", version="1.0.0")
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    await state.storage.init()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": state.settings.trading_mode}
