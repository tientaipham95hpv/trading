from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.domain.models import TradingMode
from app.services.auto_trader import AutoTrader
from app.services.user_stream import _lifecycle_fact


def test_lifecycle_fact_is_grounded_in_filled_exit_event():
    fact = _lifecycle_fact(
        TradingMode.DEMO,
        {
            "E": 1_700_000_000_000,
            "o": {
                "s": "BTCUSDT",
                "c": "a-demo-BTCUSDT-abc-tp-0",
                "X": "FILLED",
                "i": 12,
                "t": 34,
                "S": "SELL",
                "l": "0.1",
                "z": "0.1",
                "L": "50000",
                "rp": "10",
                "n": "0.2",
                "N": "USDT",
            },
        },
    )
    assert fact is not None
    assert fact["event_type"] == "CLOSE_FILL"
    assert fact["reason"] == "TAKE_PROFIT"
    assert fact["realized_pnl"] == 10


def test_lifecycle_storage_model_keeps_mode_and_event_identity():
    from app.services.storage import LifecycleAnalyticsEventRow

    row = LifecycleAnalyticsEventRow(
        event_key="DEMO:x:OPEN",
        mode="DEMO",
        lifecycle_id="x",
        symbol="BTCUSDT",
        event_type="OPEN",
        event_at=datetime.now(UTC),
        payload={"risk_verifiable": True},
    )
    assert row.event_key == "DEMO:x:OPEN"
    assert row.mode == "DEMO"
    assert row.payload["risk_verifiable"] is True


def test_managed_entry_fill_is_recorded_with_exact_fee_and_price():
    fact = _lifecycle_fact(
        TradingMode.DEMO,
        {
            "E": 1_700_000_000_000,
            "o": {
                "s": "BTCUSDT",
                "c": "a-demo-BTCUSDT-abc",
                "X": "FILLED",
                "i": 10,
                "t": 11,
                "S": "BUY",
                "l": "0.2",
                "z": "0.2",
                "L": "50025",
                "rp": "0",
                "n": "0.4",
                "N": "USDT",
            },
        },
    )

    assert fact is not None
    assert fact["event_type"] == "ENTRY_FILL"
    assert fact["lifecycle_id"] == "a-demo-BTCUSDT-abc"
    assert fact["last_fill_price"] == 50025
    assert fact["commission"] == 0.4
    assert fact["order_status"] == "FILLED"


def test_partial_entry_fill_is_marked_so_open_repair_waits_for_final_fill():
    fact = _lifecycle_fact(
        TradingMode.DEMO,
        {
            "o": {
                "s": "COTIUSDT",
                "c": "a-demo-COTIUSDT-abc",
                "X": "PARTIALLY_FILLED",
                "i": 10,
                "t": 11,
                "S": "BUY",
                "l": "1515",
                "z": "1515",
                "L": "0.012887",
            }
        },
    )

    assert fact is not None
    assert fact["event_type"] == "ENTRY_FILL"
    assert fact["order_status"] == "PARTIALLY_FILLED"


def test_break_even_stop_fill_maps_back_to_original_lifecycle():
    fact = _lifecycle_fact(
        TradingMode.DEMO,
        {
            "E": 1_700_000_000_000,
            "o": {
                "s": "BTCUSDT",
                "c": "a-demo-BTCUSDT-abc-be-1700000000000",
                "X": "FILLED",
                "i": 55,
                "t": 66,
                "S": "SELL",
                "l": "0.1",
                "z": "0.1",
                "L": "50100",
                "rp": "1",
                "n": "0.2",
            },
        },
    )
    assert fact is not None
    assert fact["reason"] == "STOP_LOSS"
    assert fact["lifecycle_id"] == "a-demo-BTCUSDT-abc"


def test_environment_blacklist_cannot_be_cleared_by_runtime_settings():
    trader = AutoTrader(
        SimpleNamespace(settings=SimpleNamespace(scanner_blacklist="XMRUSDT, ZECUSDT"))
    )

    assert trader._configured_hard_blacklist() == {"XMRUSDT", "ZECUSDT"}


@pytest.mark.asyncio
async def test_unknown_managed_entry_is_closed_and_enters_safe_mode(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.services.auto_trader.asyncio.sleep", no_sleep)

    class Storage:
        def __init__(self):
            self.logs = []

        async def lifecycle_open_event(self, **_kwargs):
            return None

        async def log(self, message, payload, **_kwargs):
            self.logs.append((message, payload))

    class Adapter:
        def __init__(self):
            self.closed = []

        def submitted_plan(self, _symbol):
            return None

        async def close_unknown_managed_position_fail_closed(self, symbol, *, lifecycle_id):
            self.closed.append((symbol, lifecycle_id))

    storage = Storage()
    safe_mode_reasons = []
    state = SimpleNamespace(
        trading_mode=TradingMode.DEMO,
        storage=storage,
        enter_safe_mode=safe_mode_reasons.append,
    )
    adapter = Adapter()

    await AutoTrader(state).repair_lifecycle_open_from_entry_fill(
        adapter,
        {
            "lifecycle_id": "a-demo-XMRUSDT-unknown",
            "symbol": "XMRUSDT",
        },
    )

    assert adapter.closed == [("XMRUSDT", "a-demo-XMRUSDT-unknown")]
    assert safe_mode_reasons == [
        "Entry bot-owned không thuộc execution instance: a-demo-XMRUSDT-unknown"
    ]
    assert storage.logs[0][0] == "Unknown managed entry closed fail-closed"
