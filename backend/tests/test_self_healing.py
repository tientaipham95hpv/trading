from types import SimpleNamespace

import pytest

from app.domain.models import (
    BotState,
    ExchangeConnectionState,
    ExchangePosition,
    ExchangeSnapshot,
    TradingMode,
)
from app.services.self_healing import SelfHealingWatchdog


class FakeStorage:
    def __init__(self) -> None:
        self.logs: list[tuple[str, dict[str, object], str]] = []

    async def log(self, message: str, payload=None, level: str = "INFO") -> None:
        self.logs.append((message, payload or {}, level))


class FakeExecution:
    def __init__(self, positions=None) -> None:
        self.positions = positions or []

    def open_positions(self):
        return list(self.positions)


class FakeAutoTrader:
    def _unprotected_exchange_positions(self, snapshot: ExchangeSnapshot) -> list[str]:
        return []


class FakeAdapter:
    def __init__(self, snapshots: list[ExchangeSnapshot]) -> None:
        self.snapshots = snapshots
        self.calls = 0

    async def snapshot(self) -> ExchangeSnapshot:
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index].model_copy(deep=True)

    async def reconcile(self, local_positions) -> ExchangeSnapshot:
        index = min(max(self.calls - 1, 0), len(self.snapshots) - 1)
        return self.snapshots[index].model_copy(deep=True)


class FakeState:
    def __init__(
        self,
        snapshots: list[ExchangeSnapshot],
        *,
        reason: str | None,
        mode: TradingMode = TradingMode.DEMO,
    ) -> None:
        self.settings = SimpleNamespace(self_heal_enabled=True)
        self.trading_mode = mode
        self.auto_resume_requested = True
        self.emergency_stop = SimpleNamespace(active=False)
        self.bot_state = BotState.SAFE_MODE if reason else BotState.STOPPED
        self.safe_mode = bool(reason)
        self.safe_mode_reason = reason
        self.demo_exchange = FakeAdapter(snapshots)
        self.execution = FakeExecution()
        self.auto_trader = FakeAutoTrader()
        self.user_stream = SimpleNamespace(connected=True)
        self.storage = FakeStorage()
        self.saved = 0
        self.cleared = 0

    def clear_safe_mode_after_verified_reconciliation(self) -> None:
        self.safe_mode = False
        self.safe_mode_reason = None
        self.bot_state = BotState.PAUSED
        self.cleared += 1

    def save_runtime_config(self) -> None:
        self.saved += 1


def flat_snapshot() -> ExchangeSnapshot:
    return ExchangeSnapshot(
        mode=TradingMode.DEMO,
        connection=ExchangeConnectionState.CONNECTED,
        safe_mode=True,
        safe_mode_reason="sticky latch",
    )


@pytest.mark.asyncio
async def test_recovers_transient_safe_mode_only_after_two_flat_checks() -> None:
    state = FakeState(
        [flat_snapshot(), flat_snapshot()],
        reason="Entry bot-owned không thuộc execution instance: a-demo-BTCUSDT-old",
    )
    watchdog = SelfHealingWatchdog(state, verification_delay_seconds=0)  # type: ignore[arg-type]

    result = await watchdog.recover_once()

    assert result["status"] == "RECOVERED"
    assert state.demo_exchange.calls == 2
    assert state.cleared == 1
    assert state.bot_state == BotState.RUNNING
    assert state.saved == 1
    assert state.storage.logs[-1][0] == "Self-healing resumed DEMO bot"


@pytest.mark.asyncio
async def test_dangerous_safe_mode_requires_manual_intervention() -> None:
    state = FakeState(
        [flat_snapshot()],
        reason="Position không có SL: BTCUSDT",
    )
    watchdog = SelfHealingWatchdog(state, verification_delay_seconds=0)  # type: ignore[arg-type]

    result = await watchdog.recover_once()

    assert result["status"] == "MANUAL_REQUIRED"
    assert state.demo_exchange.calls == 0
    assert state.cleared == 0
    assert state.bot_state == BotState.SAFE_MODE


@pytest.mark.asyncio
async def test_never_recovers_when_exchange_has_exposure() -> None:
    snapshot = flat_snapshot()
    snapshot.positions = [
        ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=0.1, entry_price=100)
    ]
    state = FakeState(
        [snapshot],
        reason="SAFE_MODE: user stream reconnect lỗi 5 lần liên tiếp",
    )
    watchdog = SelfHealingWatchdog(state, verification_delay_seconds=0)  # type: ignore[arg-type]

    result = await watchdog.recover_once()

    assert result == {"status": "VERIFY_FAILED", "reason": "Còn vị thế trên exchange"}
    assert state.cleared == 0


@pytest.mark.asyncio
async def test_clears_transient_latch_but_waits_for_user_stream_before_resume() -> None:
    state = FakeState(
        [flat_snapshot(), flat_snapshot()],
        reason="SAFE_MODE: user stream reconnect lỗi 5 lần liên tiếp",
    )
    state.user_stream.connected = False
    watchdog = SelfHealingWatchdog(state, verification_delay_seconds=0)  # type: ignore[arg-type]

    pending = await watchdog.recover_once()

    assert pending["status"] == "RECOVERY_PENDING"
    assert state.cleared == 1
    assert state.bot_state == BotState.PAUSED
    assert state.saved == 0

    state.user_stream.connected = True
    resumed = await watchdog.recover_once()

    assert resumed["status"] == "RECOVERED"
    assert state.bot_state == BotState.RUNNING
    assert state.saved == 1


@pytest.mark.asyncio
async def test_never_auto_resumes_live() -> None:
    state = FakeState(
        [flat_snapshot()],
        reason="SAFE_MODE: user stream reconnect lỗi 5 lần liên tiếp",
        mode=TradingMode.LIVE,
    )
    watchdog = SelfHealingWatchdog(state, verification_delay_seconds=0)  # type: ignore[arg-type]

    result = await watchdog.recover_once()

    assert result == {"status": "BLOCKED", "reason": "Không tự resume LIVE"}
    assert state.demo_exchange.calls == 0
    assert state.cleared == 0


@pytest.mark.asyncio
async def test_explicit_operator_stop_disables_recovery() -> None:
    state = FakeState([flat_snapshot()], reason=None)
    state.auto_resume_requested = False
    watchdog = SelfHealingWatchdog(state, verification_delay_seconds=0)  # type: ignore[arg-type]

    result = await watchdog.recover_once()

    assert result["status"] == "IDLE"
    assert state.demo_exchange.calls == 0
