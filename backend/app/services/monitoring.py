"""Monitoring service - Real-time tracking cho trading bot."""

from datetime import UTC, datetime
from typing import Any


class MonitoringService:
    def __init__(self) -> None:
        self.alerts: list[dict[str, Any]] = []
        self.last_equity_check: float | None = None
        self.peak_equity: float | None = None
        self.max_drawdown_alert_sent = False

    def update_performance(
        self, performance: Any, *, send_alert_callback: Any = None
    ) -> dict[str, Any]:
        """Cập nhật performance và kiểm tra drawdown alert."""
        equity = performance.equity
        initial = performance.initial_capital

        # Track peak equity
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
            self.max_drawdown_alert_sent = False

        # Calculate current drawdown
        drawdown = 0.0
        drawdown_pct = 0.0
        if self.peak_equity and self.peak_equity > 0:
            drawdown = self.peak_equity - equity
            drawdown_pct = (drawdown / self.peak_equity) * 100

        # Alert if drawdown > 5%
        if drawdown_pct > 5.0 and not self.max_drawdown_alert_sent:
            alert = {
                "timestamp": datetime.now(UTC).isoformat(),
                "type": "DRAWDOWN_WARNING",
                "message": f"⚠️ Drawdown vượt 5%: {drawdown_pct:.2f}%",
                "drawdown": drawdown,
                "drawdown_pct": drawdown_pct,
                "peak_equity": self.peak_equity,
                "current_equity": equity,
            }
            self.alerts.append(alert)
            self.max_drawdown_alert_sent = True

            # Send telegram alert if callback provided
            if send_alert_callback:
                import asyncio

                asyncio.create_task(send_alert_callback(alert))

        return {
            "equity": equity,
            "initial_capital": initial,
            "pnl": equity - initial,
            "pnl_pct": ((equity - initial) / initial * 100) if initial > 0 else 0.0,
            "peak_equity": self.peak_equity,
            "current_drawdown": drawdown,
            "current_drawdown_pct": drawdown_pct,
            "win_rate": performance.win_rate * 100,
            "total_trades": performance.total_trades,
            "profit_factor": performance.profit_factor,
            "sharpe": performance.sharpe,
            "max_drawdown": performance.max_drawdown,
        }

    def dashboard(self, performance: Any, *, mode: str = "UNKNOWN") -> dict[str, Any]:
        """Generate dashboard data."""
        metrics = self.update_performance(performance)

        return {
            "mode": mode,
            "timestamp": datetime.now(UTC).isoformat(),
            "metrics": metrics,
            "recent_alerts": self.alerts[-10:],  # Last 10 alerts
            "health": self._health_status(metrics),
        }

    @staticmethod
    def _health_status(metrics: dict[str, Any]) -> dict[str, Any]:
        """Đánh giá health status."""
        drawdown_pct = metrics.get("current_drawdown_pct", 0.0)
        win_rate = metrics.get("win_rate", 0.0)
        profit_factor = metrics.get("profit_factor", 0.0)

        issues = []
        if drawdown_pct > 10.0:
            issues.append("CRITICAL_DRAWDOWN")
        elif drawdown_pct > 5.0:
            issues.append("HIGH_DRAWDOWN")

        if win_rate < 40.0 and metrics.get("total_trades", 0) > 10:
            issues.append("LOW_WIN_RATE")

        if profit_factor < 1.0 and metrics.get("total_trades", 0) > 10:
            issues.append("NEGATIVE_PROFIT_FACTOR")

        if not issues:
            status = "HEALTHY"
        elif "CRITICAL_DRAWDOWN" in issues:
            status = "CRITICAL"
        else:
            status = "WARNING"

        return {
            "status": status,
            "issues": issues,
            "checks": {
                "drawdown_ok": drawdown_pct <= 5.0,
                "win_rate_ok": win_rate >= 40.0 or metrics.get("total_trades", 0) < 10,
                "profit_factor_ok": profit_factor >= 1.0 or metrics.get("total_trades", 0) < 10,
            },
        }
