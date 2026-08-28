from datetime import UTC, datetime

from app.domain.models import TradingMode
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
