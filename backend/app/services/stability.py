from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.domain.models import DemoStabilityReport, StabilityCheck, TradingMode
from app.services.exchange import ExchangeError


class DemoStabilityService:
    """Build a conservative, read-only LIVE readiness report from runtime evidence."""

    MIN_TRADES = 30
    MAX_VALIDATION_TRADES = 50
    MIN_SAMPLE_DAYS = 7
    MIN_PROFIT_FACTOR = 1.2

    def __init__(self, app_state: Any) -> None:
        self.state = app_state
        self.last_report: DemoStabilityReport | None = None
        self.task: asyncio.Task[None] | None = None
        self.running = False

    def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._monitor())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _monitor(self) -> None:
        while self.running:
            try:
                await self.report()
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                await self.state.storage.log(
                    "Stability monitor error", {"error": str(exc)}, level="ERROR"
                )
            await asyncio.sleep(45)

    def _demo_reset_at(self) -> datetime | None:
        getter = getattr(self.state, "performance_reset_at_for", None)
        if callable(getter):
            return getter(TradingMode.DEMO)
        return getattr(self.state, "performance_reset_at", None)

    async def report(self) -> DemoStabilityReport:
        adapter = self.state.demo_exchange
        snapshot = adapter.snapshot_cache
        performance = self.state.execution.performance()
        try:
            snapshot = await adapter.snapshot()
            lifecycle_reader = getattr(
                self.state.storage, "lifecycle_analytics_events", None
            )
            if not callable(lifecycle_reader):
                raise TypeError("Lifecycle audit storage is unavailable")
            events = await lifecycle_reader(mode=TradingMode.DEMO.value, limit=5000)
            reset_at = self._demo_reset_at()
            if reset_at:
                events = [
                    event
                    for event in events
                    if datetime.fromisoformat(str(event.get("event_at"))) >= reset_at
                ]
            grouped: dict[str, list[dict[str, object]]] = {}
            for event in events:
                lifecycle_id = str(event.get("lifecycle_id") or "")
                if lifecycle_id:
                    grouped.setdefault(lifecycle_id, []).append(event)
            outcomes: list[tuple[datetime, float]] = []
            for lifecycle_events in grouped.values():
                verified_open = next(
                    (
                        event
                        for event in lifecycle_events
                        if event.get("event_type") == "OPEN"
                        and event.get("risk_verifiable") is True
                        and float(event.get("entry_price") or 0) > 0
                    ),
                    None,
                )
                if verified_open is None:
                    continue
                final_events = [
                    event
                    for event in lifecycle_events
                    if event.get("event_type") == "CLOSE_FILL"
                ]
                if not final_events:
                    continue
                close_events = [
                    event
                    for event in lifecycle_events
                    if event.get("event_type") in {"PARTIAL_CLOSE", "CLOSE_FILL"}
                ]
                entry_events = [
                    event
                    for event in lifecycle_events
                    if event.get("event_type") == "ENTRY_FILL"
                ]
                closed_at = max(
                    datetime.fromisoformat(str(event.get("event_at")))
                    for event in final_events
                )
                net_pnl = sum(
                    float(event.get("realized_pnl") or 0)
                    - abs(float(event.get("commission") or 0))
                    for event in close_events
                ) - sum(abs(float(event.get("commission") or 0)) for event in entry_events)
                outcomes.append((closed_at, net_pnl))
            values = [value for _, value in sorted(outcomes)[-self.MAX_VALIDATION_TRADES :]]
            trade_count = len(values)
            realized_pnl = sum(values)
            win_rate = sum(value > 0 for value in values) / trade_count if trade_count else 0.0
            gross_profit = sum(value for value in values if value > 0)
            gross_loss = abs(sum(value for value in values if value < 0))
            profit_factor = (
                gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0)
            )
        except (
            TypeError,
            ExchangeError,
            TimeoutError,
            OSError,
            RuntimeError,
            ValueError,
        ):  # report remains available during exchange incidents
            trade_count = performance.total_trades
            realized_pnl = performance.realized_pnl
            win_rate = performance.win_rate
            profit_factor = performance.profit_factor

        now = datetime.now(UTC)
        started_at = self._demo_reset_at()
        sample_days = max(0.0, (now - started_at).total_seconds() / 86400) if started_at else 0.0
        stream = self.state.user_stream.snapshot()
        order_ids = [order.client_order_id for order in snapshot.orders if order.client_order_id]
        positions = [position for position in snapshot.positions if abs(position.quantity) > 0]
        unprotected = self.state.auto_trader._unprotected_exchange_positions(snapshot)
        owned_orders = [
            order for order in snapshot.orders if order.client_order_id.startswith("a-demo-")
        ]
        reconcile_age = (
            (now - snapshot.last_reconciled_at).total_seconds()
            if snapshot.last_reconciled_at
            else None
        )

        checks = {
            "sample_size": self._check(
                trade_count >= self.MIN_TRADES,
                trade_count,
                f">= {self.MIN_TRADES} realized trades",
                f"Forward-test từ lần reset DEMO: {trade_count}/{self.MIN_TRADES} giao dịch đóng",
            ),
            "sample_duration": self._check(
                sample_days >= self.MIN_SAMPLE_DAYS,
                round(sample_days, 2),
                f">= {self.MIN_SAMPLE_DAYS} ngày",
                f"Thời gian quan sát {sample_days:.2f}/{self.MIN_SAMPLE_DAYS} ngày",
            ),
            "positive_expectancy": self._check(
                trade_count >= self.MIN_TRADES
                and realized_pnl > 0
                and profit_factor > self.MIN_PROFIT_FACTOR,
                round(realized_pnl / trade_count, 6) if trade_count else 0.0,
                f"expectancy > 0 và profit factor > {self.MIN_PROFIT_FACTOR} sau 30–50 lệnh",
                f"PNL {realized_pnl:.4f}, profit factor {profit_factor:.2f}",
            ),
            "sl_protection": self._check(
                not unprotected,
                len(unprotected),
                "0 vị thế thiếu protective SL",
                "Tất cả vị thế có SL" if not unprotected else f"Thiếu SL: {', '.join(unprotected)}",
            ),
            "user_stream": self._check(
                bool(stream["connected"]) and int(stream["consecutive_failures"]) == 0,
                int(stream["consecutive_failures"]),
                "connected và 0 lỗi liên tiếp",
                f"connected={stream['connected']}, reconnects={stream['reconnects']}",
            ),
            "reconciliation": self._check(
                reconcile_age is not None and reconcile_age <= 120 and not snapshot.safe_mode,
                round(reconcile_age, 1) if reconcile_age is not None else None,
                "reconcile <= 120 giây, không SAFE_MODE",
                "Chưa có reconcile"
                if reconcile_age is None
                else f"Reconcile cách đây {reconcile_age:.1f}s",
            ),
            "duplicate_orders": self._check(
                len(order_ids) == len(set(order_ids)),
                len(order_ids) - len(set(order_ids)),
                "0 clientOrderId trùng trong open orders",
                f"Kiểm tra {len(order_ids)} open orders",
            ),
            "order_ownership": self._check(
                len(owned_orders) == len(snapshot.orders),
                len(snapshot.orders) - len(owned_orders),
                "100% open orders thuộc group do bot tạo",
                f"Bot-owned {len(owned_orders)}/{len(snapshot.orders)} orders",
            ),
            "safe_mode": self._check(
                not snapshot.safe_mode and not self.state.safe_mode,
                bool(snapshot.safe_mode or self.state.safe_mode),
                "SAFE_MODE=false",
                snapshot.safe_mode_reason or "Không có cảnh báo an toàn",
            ),
        }
        score = round(100 * sum(check.passed for check in checks.values()) / len(checks))
        blockers = [f"{name}: {check.detail}" for name, check in checks.items() if not check.passed]
        collecting = not checks["sample_size"].passed or not checks["sample_duration"].passed
        self.last_report = DemoStabilityReport(
            mode=TradingMode.DEMO,
            sample_started_at=started_at,
            score=score,
            verdict="READY" if not blockers else "COLLECTING_DATA" if collecting else "NOT_READY",
            checks=checks,
            blockers=blockers,
            metrics={
                "trades": trade_count,
                "realized_pnl": round(realized_pnl, 6),
                "win_rate": round(win_rate, 6),
                "profit_factor": round(profit_factor, 6),
                "sample_days": round(sample_days, 3),
                "positions": len(positions),
                "orders": len(snapshot.orders),
                "user_stream_events": int(stream["events"]),
                "user_stream_reconnects": int(stream["reconnects"]),
            },
        )
        # A completed validation sample that degrades to non-positive expectancy
        # or PF <= 1 is paused fail-closed. This never enables LIVE.
        if trade_count >= self.MIN_TRADES and (realized_pnl <= 0 or profit_factor <= 1.0):
            self.state.enter_safe_mode(
                "DEMO forward-test suy giảm mạnh sau đủ 30 lệnh; pause entry để rà soát"
            )
        payload = self.last_report.model_dump(mode="json")
        await self.state.storage.save_stability_snapshot(payload)
        changes = await self.state.storage.sync_incidents(self._active_incidents(checks))
        for change in changes:
            severity = str(change["severity"])
            await self.state.storage.log(
                f"Stability incident {str(change['event']).lower()}: {change['key']}",
                change,
                level="CRITICAL" if severity == "CRITICAL" else "WARNING",
            )
        return self.last_report

    @staticmethod
    def _active_incidents(checks: dict[str, StabilityCheck]) -> dict[str, dict[str, Any]]:
        severity = {
            "sl_protection": "CRITICAL",
            "user_stream": "CRITICAL",
            "reconciliation": "WARNING",
            "duplicate_orders": "CRITICAL",
            "order_ownership": "WARNING",
            "safe_mode": "CRITICAL",
        }
        return {
            key: {
                "severity": severity[key],
                "message": check.detail,
                "payload": {"requirement": check.requirement, "value": check.value},
            }
            for key, check in checks.items()
            if key in severity and not check.passed
        }

    @staticmethod
    def _check(passed: bool, value: Any, requirement: str, detail: str) -> StabilityCheck:
        return StabilityCheck(passed=passed, value=value, requirement=requirement, detail=detail)
