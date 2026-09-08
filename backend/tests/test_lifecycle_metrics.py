from datetime import UTC, datetime, timedelta

import pytest

from app.services.lifecycle_metrics import closed_lifecycle_outcomes


def _event(at, lifecycle_id, symbol, event_type, **extra):
    return {
        "event_at": at.isoformat(),
        "lifecycle_id": lifecycle_id,
        "symbol": symbol,
        "event_type": event_type,
        **extra,
    }


def test_filled_tp_order_does_not_close_an_exchange_position_still_open():
    now = datetime.now(UTC)
    events = [
        _event(
            now,
            "a-demo-BTC-1",
            "BTCUSDT",
            "OPEN",
            risk_verifiable=True,
            entry_price=100,
            initial_quantity=10,
            side="LONG",
        ),
        _event(
            now + timedelta(seconds=1),
            "a-demo-BTC-1",
            "BTCUSDT",
            "ENTRY_FILL",
            realized_pnl=0,
            commission=0.1,
            last_fill_quantity=10,
            last_fill_price=100,
        ),
        _event(
            now + timedelta(minutes=1),
            "a-demo-BTC-1",
            "BTCUSDT",
            "CLOSE_FILL",
            reason="TAKE_PROFIT",
            realized_pnl=2,
            commission=0.05,
            last_fill_quantity=4,
            last_fill_price=101,
        ),
    ]

    assert closed_lifecycle_outcomes(events, open_symbols={"BTCUSDT"}) == []


def test_flat_snapshot_closes_segment_and_attributes_orphan_local_close_fill():
    now = datetime.now(UTC)
    events = [
        _event(
            now,
            "a-demo-BTC-1",
            "BTCUSDT",
            "OPEN",
            risk_verifiable=True,
            entry_price=100,
            initial_quantity=10,
            side="LONG",
        ),
        _event(
            now + timedelta(seconds=1),
            "a-demo-BTC-1",
            "BTCUSDT",
            "ENTRY_FILL",
            realized_pnl=0,
            commission=0.1,
            last_fill_quantity=10,
            last_fill_price=100,
        ),
        _event(
            now + timedelta(minutes=1),
            "a-demo-BTC-1",
            "BTCUSDT",
            "CLOSE_FILL",
            reason="TAKE_PROFIT",
            realized_pnl=2,
            commission=0.05,
            last_fill_quantity=4,
            last_fill_price=101,
        ),
        # Local stop replacement uses a new client id and was historically
        # classified as ENTRY_FILL even though its realized PnL proves it closed.
        _event(
            now + timedelta(minutes=2),
            "a-demo-BTC-1-loc-orphan",
            "BTCUSDT",
            "ENTRY_FILL",
            reason="ENTRY",
            realized_pnl=-1,
            commission=0.03,
            last_fill_quantity=6,
            last_fill_price=99.8,
        ),
    ]

    outcomes = closed_lifecycle_outcomes(events, open_symbols=set())
    assert len(outcomes) == 1
    assert outcomes[0]["lifecycle_id"] == "a-demo-BTC-1"
    assert outcomes[0]["gross_pnl"] == 1
    assert outcomes[0]["fee"] == 0.18
    assert outcomes[0]["net_pnl"] == pytest.approx(0.82)
    assert outcomes[0]["exit_price"] == 99.8


def test_next_verified_open_closes_previous_segment_but_keeps_latest_open():
    now = datetime.now(UTC)
    events = [
        _event(
            now,
            "first",
            "ETHUSDT",
            "OPEN",
            risk_verifiable=True,
            entry_price=100,
            initial_quantity=1,
            side="LONG",
        ),
        _event(
            now + timedelta(minutes=1),
            "first",
            "ETHUSDT",
            "CLOSE_FILL",
            realized_pnl=-1,
            commission=0,
            last_fill_quantity=1,
            last_fill_price=99,
        ),
        _event(
            now + timedelta(minutes=2),
            "second",
            "ETHUSDT",
            "OPEN",
            risk_verifiable=True,
            entry_price=101,
            initial_quantity=1,
            side="LONG",
        ),
        _event(
            now + timedelta(minutes=2, seconds=1),
            "second",
            "ETHUSDT",
            "ENTRY_FILL",
            realized_pnl=0,
            commission=0.01,
            last_fill_quantity=1,
            last_fill_price=101,
        ),
    ]

    outcomes = closed_lifecycle_outcomes(events, open_symbols={"ETHUSDT"})
    assert [item["lifecycle_id"] for item in outcomes] == ["first"]
