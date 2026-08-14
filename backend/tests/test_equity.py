import pytest

from app.services.equity import EquityTracker, equity_metrics


class FakeStorage:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.history: list[dict] = []

    async def save_equity_snapshot(self, payload: dict) -> None:
        self.saved.append(payload)

    async def equity_history(self, mode: str, *, limit: int = 500) -> list[dict]:
        return self.history[:limit]

    async def log(self, message: str, payload=None, level: str = "INFO") -> None:
        pass


class FakeBalance:
    def __init__(self) -> None:
        self.balance = 1000.0
        self.margin_balance = 1010.0
        self.unrealized_pnl = 10.0


class FakeSnapshot:
    def __init__(self) -> None:
        self.balance = FakeBalance()
        self.positions = [object()]


class FakeAdapter:
    async def snapshot(self) -> FakeSnapshot:
        return FakeSnapshot()


class FakeState:
    def __init__(self) -> None:
        self.trading_mode = type("Mode", (), {"value": "DEMO"})()
        self.storage = FakeStorage()
        self._exchange = FakeAdapter()

    def _active_exchange(self) -> FakeAdapter:
        return self._exchange


async def test_capture_saves_snapshot_payload() -> None:
    state = FakeState()
    tracker = EquityTracker(state)
    payload = await tracker.capture()
    assert payload is not None
    assert payload["mode"] == "DEMO"
    assert payload["equity"] == 1010.0
    assert state.storage.saved[-1]["open_positions"] == 1


def test_equity_metrics_drawdown_and_return() -> None:
    curve = [100.0, 120.0, 90.0, 110.0]
    metrics = equity_metrics(curve)
    assert metrics["peak_equity"] == 120.0
    assert metrics["equity"] == 110.0
    assert metrics["max_drawdown_percent"] == pytest.approx(25.0)
    assert metrics["current_drawdown_percent"] == pytest.approx(8.333333)
    assert metrics["return_percent"] == pytest.approx(10.0)


def test_equity_metrics_empty_curve() -> None:
    metrics = equity_metrics([])
    assert metrics["equity"] == 0.0
    assert metrics["max_drawdown_percent"] == 0.0


async def test_analytics_uses_stored_history() -> None:
    state = FakeState()
    state.storage.history = [
        {"equity": 100.0, "taken_at": "2026-08-14T00:00:00+00:00"},
        {"equity": 90.0, "taken_at": "2026-08-14T01:00:00+00:00"},
        {"equity": 105.0, "taken_at": "2026-08-14T02:00:00+00:00"},
    ]
    tracker = EquityTracker(state)
    result = await tracker.analytics("DEMO")
    assert result["samples"] == 3
    assert result["max_drawdown_percent"] == pytest.approx(10.0)
    assert result["first_at"] == "2026-08-14T00:00:00+00:00"
