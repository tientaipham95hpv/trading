"""Equity history capture and analytics.

Recorder chạy nền, lưu equity snapshot theo mode; analytics tính drawdown/return
từ lịch sử đã lưu để dashboard/iOS vẽ đường cong equity thay vì chỉ nhìn PNL cộng dồn.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.services.exchange import ExchangeError


class EquityTracker:
    CAPTURE_INTERVAL_SECONDS = 60

    def __init__(self, app_state: Any) -> None:
        self.state = app_state
        self.task: asyncio.Task[None] | None = None
        self.running = False

    def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self.running:
            try:
                await self.capture()
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError, ExchangeError) as exc:
                await self.state.storage.log(
                    "Equity capture error", {"error": str(exc)}, level="ERROR"
                )
            await asyncio.sleep(self.CAPTURE_INTERVAL_SECONDS)

    async def capture(self) -> dict[str, Any] | None:
        """Chụp equity snapshot của mode đang chạy; trả về payload đã lưu hoặc None."""
        adapter = self.state._active_exchange()
        mode = self.state.trading_mode.value
        try:
            snapshot = await adapter.snapshot()
        except ExchangeError as exc:
            await self.state.storage.log(
                "Equity capture bỏ qua do exchange lỗi", {"error": str(exc)}, level="WARNING"
            )
            return None
        payload = {
            "mode": mode,
            "equity": snapshot.balance.margin_balance or snapshot.balance.balance,
            "balance": snapshot.balance.balance,
            "margin_balance": snapshot.balance.margin_balance,
            "unrealized_pnl": snapshot.balance.unrealized_pnl,
            "open_positions": len(snapshot.positions),
            "source": "SNAPSHOT",
        }
        await self.state.storage.save_equity_snapshot(payload)
        return payload

    async def history(self, mode: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return await self.state.storage.equity_history(mode, limit=limit)

    async def analytics(self, mode: str) -> dict[str, Any]:
        points = await self.state.storage.equity_history(mode, limit=5000)
        equity_curve = [point["equity"] for point in points]
        metrics = equity_metrics(equity_curve)
        metrics["mode"] = mode
        metrics["samples"] = len(points)
        metrics["first_at"] = points[0]["taken_at"] if points else None
        metrics["last_at"] = points[-1]["taken_at"] if points else None
        return metrics


def equity_metrics(equity_curve: list[float]) -> dict[str, Any]:
    """Tính peak, drawdown và return từ chuỗi equity theo thời gian."""
    if not equity_curve:
        return {
            "equity": 0.0,
            "peak_equity": 0.0,
            "current_drawdown_percent": 0.0,
            "max_drawdown_percent": 0.0,
            "return_percent": 0.0,
        }
    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
    first = equity_curve[0]
    last = equity_curve[-1]
    return {
        "equity": last,
        "peak_equity": peak,
        "current_drawdown_percent": round((peak - last) / peak * 100, 6) if peak > 0 else 0.0,
        "max_drawdown_percent": round(max_drawdown * 100, 6),
        "return_percent": round((last - first) / first * 100, 6) if first > 0 else 0.0,
    }
