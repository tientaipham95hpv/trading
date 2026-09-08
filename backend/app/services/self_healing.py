from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.models import BotState, ExchangeConnectionState, TradingMode
from app.services.exchange import ExchangeCredentialsError, ExchangeError


class SelfHealingWatchdog:
    """Conservatively recover a requested DEMO run after transient failures.

    Recovery is deliberately flat-account only. It never clears an emergency
    stop, never auto-resumes LIVE, and never bypasses position/SL uncertainty.
    """

    RECOVERABLE_REASON_PREFIXES = (
        "Entry bot-owned không thuộc execution instance:",
        "SAFE_MODE: user stream reconnect lỗi",
        "Reconcile không chắc chắn:",
        "Startup reconcile không chắc chắn:",
    )

    def __init__(
        self,
        app_state: Any,
        *,
        interval_seconds: float = 30,
        verification_delay_seconds: float = 2,
        max_attempts: int = 3,
        attempt_window_seconds: int = 1800,
    ) -> None:
        self.state = app_state
        self.interval_seconds = interval_seconds
        self.verification_delay_seconds = verification_delay_seconds
        self.max_attempts = max_attempts
        self.attempt_window_seconds = attempt_window_seconds
        self.task: asyncio.Task[None] | None = None
        self.running = False
        self.last_check_at: datetime | None = None
        self.last_recovery_at: datetime | None = None
        self.last_status = "IDLE"
        self.last_reason = "Chưa chạy self-healing"
        self.recoveries = 0
        self._attempts: deque[datetime] = deque()
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def snapshot(self) -> dict[str, object]:
        self._prune_attempts(datetime.now(UTC))
        return {
            "enabled": bool(self.state.settings.self_heal_enabled),
            "running": self.running and self.task is not None and not self.task.done(),
            "auto_resume_requested": bool(self.state.auto_resume_requested),
            "last_check_at": self.last_check_at.isoformat() if self.last_check_at else None,
            "last_recovery_at": self.last_recovery_at.isoformat()
            if self.last_recovery_at
            else None,
            "last_status": self.last_status,
            "last_reason": self.last_reason,
            "recoveries": self.recoveries,
            "attempts_in_window": len(self._attempts),
            "max_attempts": self.max_attempts,
            "attempt_window_seconds": self.attempt_window_seconds,
        }

    async def _run(self) -> None:
        await self.state.storage.log(
            "Self-healing watchdog started",
            {
                "enabled": self.state.settings.self_heal_enabled,
                "max_attempts": self.max_attempts,
                "attempt_window_seconds": self.attempt_window_seconds,
            },
        )
        while self.running:
            try:
                await self.recover_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - watchdog must remain alive
                self.last_status = "ERROR"
                self.last_reason = str(exc)
                await self.state.storage.log(
                    "Self-healing watchdog error", {"error": str(exc)}, level="ERROR"
                )
            await asyncio.sleep(self.interval_seconds)

    async def recover_once(self) -> dict[str, object]:
        if self._lock.locked():
            return self._result("BUSY", "Một vòng self-healing khác đang chạy")
        async with self._lock:
            self.last_check_at = datetime.now(UTC)
            if not self.state.settings.self_heal_enabled:
                return self._result("DISABLED", "Self-healing đang tắt")
            if self.state.trading_mode != TradingMode.DEMO:
                return self._result("BLOCKED", "Không tự resume LIVE")
            if not self.state.auto_resume_requested:
                return self._result("IDLE", "Operator không yêu cầu bot tiếp tục chạy")
            if self.state.emergency_stop.active:
                return self._result("BLOCKED", "Emergency Stop đang bật")
            if self.state.bot_state == BotState.RUNNING and not self.state.safe_mode:
                return self._result("HEALTHY", "Bot đang RUNNING")

            reason = self.state.safe_mode_reason or ""
            if self.state.safe_mode and not self._recoverable_reason(reason):
                return self._result("MANUAL_REQUIRED", reason or "SAFE_MODE không rõ nguyên nhân")
            if not self.state.safe_mode and not self.state.user_stream.connected:
                return self._result("WAITING_STREAM", "Chờ user stream connected trước khi resume")

            now = datetime.now(UTC)
            self._prune_attempts(now)
            if len(self._attempts) >= self.max_attempts:
                return self._result(
                    "RATE_LIMITED",
                    f"Đã thử {self.max_attempts} lần trong {self.attempt_window_seconds // 60} phút",
                )
            self._attempts.append(now)

            first = await self._verify_flat_account()
            if not first[0]:
                return self._result("VERIFY_FAILED", first[1])
            if self.verification_delay_seconds:
                await asyncio.sleep(self.verification_delay_seconds)
            second = await self._verify_flat_account()
            if not second[0]:
                return self._result("VERIFY_FAILED", second[1])

            previous_reason = self.state.safe_mode_reason
            if self.state.safe_mode:
                self.state.clear_safe_mode_after_verified_reconciliation()
            if not self.state.user_stream.connected:
                # Clearing a proven-stale transient latch lets UserStreamWatchdog
                # reconnect. Entry remains PAUSED until a later cycle sees it connected.
                self._attempts.pop()
                await self.state.storage.log(
                    "Self-healing cleared transient latch; waiting for user stream",
                    {"previous_reason": previous_reason, "verification_passes": 2},
                    level="WARNING",
                )
                return self._result(
                    "RECOVERY_PENDING", "Đã xác minh tài khoản phẳng; chờ user stream connected"
                )
            self.state.bot_state = BotState.RUNNING
            self.state.save_runtime_config()
            self.recoveries += 1
            self.last_recovery_at = datetime.now(UTC)
            result = self._result("RECOVERED", "Đã xác minh tài khoản phẳng hai lần và resume DEMO")
            await self.state.storage.log(
                "Self-healing resumed DEMO bot",
                {
                    "previous_reason": previous_reason,
                    "verification_passes": 2,
                    "positions": 0,
                    "orders": 0,
                    "attempts_in_window": len(self._attempts),
                },
                level="WARNING",
            )
            return result

    async def _verify_flat_account(self) -> tuple[bool, str]:
        adapter = self.state.demo_exchange
        try:
            snapshot = await adapter.snapshot()
            local_open = list(self.state.execution.open_positions())
            snapshot = await adapter.reconcile(
                [position.model_dump(mode="json") for position in local_open]
            )
        except (ExchangeCredentialsError, ExchangeError, OSError, TimeoutError) as exc:
            return False, f"Không xác minh được exchange: {exc}"

        if snapshot.connection not in {
            ExchangeConnectionState.CONNECTED,
            ExchangeConnectionState.SAFE_MODE,
        }:
            return False, f"Exchange chưa kết nối: {snapshot.connection.value}"
        if local_open:
            return False, "Còn vị thế local đang mở"
        if snapshot.positions:
            return False, "Còn vị thế trên exchange"
        if snapshot.orders:
            return False, "Còn lệnh mở trên exchange"
        unprotected = self.state.auto_trader._unprotected_exchange_positions(snapshot)
        if unprotected:
            return False, f"Vị thế chưa có SL: {', '.join(sorted(unprotected))}"
        if self.state.emergency_stop.active:
            return False, "Emergency Stop đang bật"
        return True, "Tài khoản phẳng và reconciliation sạch"

    def _recoverable_reason(self, reason: str) -> bool:
        return any(reason.startswith(prefix) for prefix in self.RECOVERABLE_REASON_PREFIXES)

    def _prune_attempts(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.attempt_window_seconds)
        while self._attempts and self._attempts[0] < cutoff:
            self._attempts.popleft()

    def _result(self, status: str, reason: str) -> dict[str, object]:
        self.last_status = status
        self.last_reason = reason
        return {"status": status, "reason": reason}
