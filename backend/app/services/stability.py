from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.models import DemoStabilityReport, StabilityCheck, TradingMode


class DemoStabilityService:
    """Build a conservative, read-only LIVE readiness report from runtime evidence."""

    MIN_TRADES = 50
    MIN_SAMPLE_DAYS = 7

    def __init__(self, app_state: Any) -> None:
        self.state = app_state
        self.last_report: DemoStabilityReport | None = None

    async def report(self) -> DemoStabilityReport:
        adapter = self.state.demo_exchange
        snapshot = adapter.snapshot_cache
        performance = self.state.execution.performance()
        try:
            snapshot = await adapter.snapshot()
            income = await adapter.income_history(limit=1000)
            if self.state.performance_reset_at:
                reset_ms = int(self.state.performance_reset_at.timestamp() * 1000)
                income = [row for row in income if int(row.get("time") or 0) >= reset_ms]
            values = [float(row.get("income") or 0) for row in income if str(row.get("incomeType")) == "REALIZED_PNL"]
            trade_count = len(values)
            realized_pnl = sum(values)
            win_rate = sum(value > 0 for value in values) / trade_count if trade_count else 0.0
            gross_profit = sum(value for value in values if value > 0)
            gross_loss = abs(sum(value for value in values if value < 0))
            profit_factor = gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0)
        except (OSError, RuntimeError, ValueError):  # report remains available during exchange incidents
            trade_count = performance.total_trades
            realized_pnl = performance.realized_pnl
            win_rate = performance.win_rate
            profit_factor = performance.profit_factor

        now = datetime.now(UTC)
        started_at = self.state.performance_reset_at
        sample_days = max(0.0, (now - started_at).total_seconds() / 86400) if started_at else 0.0
        stream = self.state.user_stream.snapshot()
        order_ids = [order.client_order_id for order in snapshot.orders if order.client_order_id]
        positions = [position for position in snapshot.positions if abs(position.quantity) > 0]
        unprotected = self.state.auto_trader._unprotected_exchange_positions(snapshot)
        owned_orders = [order for order in snapshot.orders if order.client_order_id.startswith("a-demo-")]
        reconcile_age = (now - snapshot.last_reconciled_at).total_seconds() if snapshot.last_reconciled_at else None

        checks = {
            "sample_size": self._check(trade_count >= self.MIN_TRADES, trade_count, f">= {self.MIN_TRADES} realized trades", f"Đã ghi nhận {trade_count}/{self.MIN_TRADES} giao dịch đóng"),
            "sample_duration": self._check(sample_days >= self.MIN_SAMPLE_DAYS, round(sample_days, 2), f">= {self.MIN_SAMPLE_DAYS} ngày", f"Thời gian quan sát {sample_days:.2f}/{self.MIN_SAMPLE_DAYS} ngày"),
            "positive_expectancy": self._check(trade_count >= self.MIN_TRADES and realized_pnl > 0 and profit_factor > 1.0, round(realized_pnl, 4), "PNL > 0 và profit factor > 1 sau đủ mẫu", f"PNL {realized_pnl:.4f}, profit factor {profit_factor:.2f}"),
            "sl_protection": self._check(not unprotected, len(unprotected), "0 vị thế thiếu protective SL", "Tất cả vị thế có SL" if not unprotected else f"Thiếu SL: {', '.join(unprotected)}"),
            "user_stream": self._check(bool(stream["connected"]) and int(stream["consecutive_failures"]) == 0, int(stream["consecutive_failures"]), "connected và 0 lỗi liên tiếp", f"connected={stream['connected']}, reconnects={stream['reconnects']}"),
            "reconciliation": self._check(reconcile_age is not None and reconcile_age <= 120 and not snapshot.safe_mode, round(reconcile_age, 1) if reconcile_age is not None else None, "reconcile <= 120 giây, không SAFE_MODE", "Chưa có reconcile" if reconcile_age is None else f"Reconcile cách đây {reconcile_age:.1f}s"),
            "duplicate_orders": self._check(len(order_ids) == len(set(order_ids)), len(order_ids) - len(set(order_ids)), "0 clientOrderId trùng trong open orders", f"Kiểm tra {len(order_ids)} open orders"),
            "order_ownership": self._check(len(owned_orders) == len(snapshot.orders), len(snapshot.orders) - len(owned_orders), "100% open orders thuộc group do bot tạo", f"Bot-owned {len(owned_orders)}/{len(snapshot.orders)} orders"),
            "safe_mode": self._check(not snapshot.safe_mode and not self.state.safe_mode, bool(snapshot.safe_mode or self.state.safe_mode), "SAFE_MODE=false", snapshot.safe_mode_reason or "Không có cảnh báo an toàn"),
        }
        score = round(100 * sum(check.passed for check in checks.values()) / len(checks))
        blockers = [f"{name}: {check.detail}" for name, check in checks.items() if not check.passed]
        collecting = not checks["sample_size"].passed or not checks["sample_duration"].passed
        self.last_report = DemoStabilityReport(
            mode=TradingMode.DEMO, sample_started_at=started_at, score=score,
            verdict="READY" if not blockers else "COLLECTING_DATA" if collecting else "NOT_READY",
            checks=checks, blockers=blockers,
            metrics={"trades": trade_count, "realized_pnl": round(realized_pnl, 6), "win_rate": round(win_rate, 6), "profit_factor": round(profit_factor, 6), "sample_days": round(sample_days, 3), "positions": len(positions), "orders": len(snapshot.orders), "user_stream_events": int(stream["events"]), "user_stream_reconnects": int(stream["reconnects"])},
        )
        return self.last_report

    @staticmethod
    def _check(passed: bool, value: Any, requirement: str, detail: str) -> StabilityCheck:
        return StabilityCheck(passed=passed, value=value, requirement=requirement, detail=detail)
