from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.domain.models import (
    ExchangeConnectionState,
    ExchangeOrder,
    ExchangePosition,
    ExchangeSnapshot,
    PerformanceSnapshot,
    TradingMode,
)
from app.services.stability import DemoStabilityService


class FakeAdapter:
    def __init__(self, snapshot, income):
        self.snapshot_cache = snapshot
        self._income = income

    async def snapshot(self):
        return self.snapshot_cache

    async def income_history(self, limit=1000):
        return self._income


class FakeAutoTrader:
    @staticmethod
    def _unprotected_exchange_positions(snapshot):
        stops = {order.symbol for order in snapshot.orders if order.order_type == "STOP_MARKET"}
        return [position.symbol for position in snapshot.positions if position.symbol not in stops]


class FakeStream:
    def snapshot(self):
        return {"connected": True, "consecutive_failures": 0, "reconnects": 1, "events": 10}


def state_for(income, *, days=8):
    now = datetime.now(UTC)
    snapshot = ExchangeSnapshot(
        mode=TradingMode.DEMO,
        connection=ExchangeConnectionState.CONNECTED,
        positions=[ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=1, entry_price=100)],
        orders=[ExchangeOrder(symbol="BTCUSDT", order_id=1, client_order_id="a-demo-BTCUSDT-group-sl-0", side="SELL", order_type="STOP_MARKET", status="NEW")],
        last_reconciled_at=now - timedelta(seconds=20),
    )
    return SimpleNamespace(
        demo_exchange=FakeAdapter(snapshot, income),
        execution=SimpleNamespace(performance=lambda: PerformanceSnapshot(balance=0, equity=0, realized_pnl=0, unrealized_pnl=0, fees_paid=0, funding_paid=0, win_rate=0, total_trades=0, open_positions=0)),
        performance_reset_at=now - timedelta(days=days),
        user_stream=FakeStream(), auto_trader=FakeAutoTrader(), safe_mode=False,
    )


@pytest.mark.asyncio
async def test_stability_requires_enough_demo_evidence():
    report = await DemoStabilityService(state_for([{"incomeType": "REALIZED_PNL", "income": "2", "time": int(datetime.now(UTC).timestamp() * 1000)}], days=1)).report()
    assert report.verdict == "COLLECTING_DATA"
    assert report.checks["sample_size"].passed is False
    assert report.checks["sl_protection"].passed is True


@pytest.mark.asyncio
async def test_stability_ready_after_sufficient_healthy_sample():
    timestamp = int(datetime.now(UTC).timestamp() * 1000)
    income = [{"incomeType": "REALIZED_PNL", "income": "2", "time": timestamp} for _ in range(40)]
    income += [{"incomeType": "REALIZED_PNL", "income": "-1", "time": timestamp} for _ in range(10)]
    report = await DemoStabilityService(state_for(income)).report()
    assert report.verdict == "READY"
    assert report.score == 100
    assert report.metrics["profit_factor"] == 8
