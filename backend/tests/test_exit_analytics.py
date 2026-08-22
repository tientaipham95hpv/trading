import pytest

from app.services.exit_analytics import ExitAnalyticsService, normalize_exchange_closes


def test_exit_analytics_uses_only_grounded_realized_values_and_costs():
    trades = normalize_exchange_closes(
        [
            {"symbol": "BTCUSDT", "side": "SELL", "realizedPnl": "12", "clientOrderId": "bot-tp-1"},
            {"symbol": "BTCUSDT", "side": "SELL", "realizedPnl": "-5", "clientOrderId": "bot-sl-2"},
            {"symbol": "ETHUSDT", "side": "BUY", "realizedPnl": "0", "clientOrderId": "entry"},
        ]
    )
    income = [
        {"incomeType": "COMMISSION", "income": "-0.8"},
        {"incomeType": "COMMISSION", "income": "0.1"},
        {"incomeType": "FUNDING_FEE", "income": "-0.3"},
    ]

    result = ExitAnalyticsService().analyze(trades, income)

    assert result.read_only is True
    assert result.summary.close_fills == 2
    assert result.summary.realized_pnl == pytest.approx(7)
    assert result.summary.commission == pytest.approx(0.7)
    assert result.summary.net_realized_pnl == pytest.approx(6)
    assert {row.key for row in result.by_close_reason} == {"Stop Loss", "Take Profit"}
    assert result.by_side[0].key == "LONG"


def test_unverifiable_r_and_excursions_are_explicitly_unavailable():
    result = ExitAnalyticsService().analyze([], [])

    assert result.realized_r is None
    assert result.realized_r_availability.coverage == 0
    assert result.realized_r_availability.available is False
    assert result.mae_availability.available is False
    assert result.mfe_availability.available is False
    assert result.missed_r_availability.available is False


def test_lifecycle_metrics_dedupe_partial_and_final_update_for_same_trade():
    events = [
        {
            "event_type": "OPEN",
            "lifecycle_id": "x",
            "symbol": "BTCUSDT",
            "side": "LONG",
            "risk_verifiable": True,
            "initial_risk": 20,
        },
        {
            "event_type": "PARTIAL_CLOSE",
            "lifecycle_id": "x",
            "event_at": "2026-01-01T00:01:00+00:00",
            "order_id": "10",
            "trade_id": "7",
            "realized_pnl": 10,
            "commission": 0.5,
            "reason": "TAKE_PROFIT",
        },
        {
            "event_type": "CLOSE_FILL",
            "lifecycle_id": "x",
            "event_at": "2026-01-01T00:01:00+00:00",
            "order_id": "10",
            "trade_id": "7",
            "realized_pnl": 10,
            "commission": 0.5,
            "reason": "TAKE_PROFIT",
            "lifecycle_state": "CLOSED",
            "side": "SELL",
        },
    ]
    result = ExitAnalyticsService().analyze([], [], lifecycle_events=events)
    assert result.lifecycle_summary.terminal_lifecycles == 1
    assert result.lifecycle_summary.verified_lifecycles == 1
    assert result.lifecycle_summary.coverage == 1
    assert result.lifecycle_summary.realized_pnl == pytest.approx(10)
    assert result.lifecycle_summary.commission == pytest.approx(0.5)
    assert result.lifecycle_summary.net_pnl == pytest.approx(9.5)
    assert result.lifecycle_summary.expectancy == pytest.approx(9.5)
    assert result.realized_r == pytest.approx(0.5)


def test_lifecycle_metrics_expose_missing_open_coverage_without_inference():
    events = [
        {
            "event_type": "CLOSE_FILL",
            "lifecycle_id": "legacy",
            "event_at": "2026-01-01T00:01:00+00:00",
            "order_id": "10",
            "trade_id": "7",
            "realized_pnl": -10,
            "commission": 0.5,
            "reason": "STOP_LOSS",
        }
    ]
    result = ExitAnalyticsService().analyze([], [], lifecycle_events=events)
    assert result.lifecycle_summary.terminal_lifecycles == 1
    assert result.lifecycle_summary.verified_lifecycles == 0
    assert result.lifecycle_summary.coverage == 0
    assert result.lifecycle_summary.expectancy is None
    assert result.lifecycle_summary.max_loss_streak is None


def test_realized_r_uses_only_matched_verifiable_lifecycle_evidence():
    events = [
        {
            "event_type": "OPEN",
            "lifecycle_id": "a-demo-BTC-1",
            "risk_verifiable": True,
            "entry_timestamp_verifiable": True,
            "initial_risk": 20,
        },
        {"event_type": "CLOSE_FILL", "lifecycle_id": "a-demo-BTC-1", "realized_pnl": 10},
        {"event_type": "CLOSE_FILL", "lifecycle_id": "legacy", "realized_pnl": 100},
    ]
    result = ExitAnalyticsService().analyze([], [], lifecycle_events=events)
    assert result.realized_r == pytest.approx(0.5)
    assert result.realized_r_availability.available is True
    assert result.realized_r_availability.coverage == pytest.approx(0.5)


from app.domain.models import Candle
from app.services.exit_analytics import excursion_requests


def _candle(open_time: int, high: float, low: float) -> Candle:
    return Candle(
        open_time=open_time,
        open=100,
        high=high,
        low=low,
        close=100,
        volume=1,
        close_time=open_time + 59_999,
    )


def test_long_excursion_uses_only_complete_closed_candles():
    events = [
        {
            "event_type": "OPEN",
            "lifecycle_id": "x",
            "symbol": "BTCUSDT",
            "event_at": "2026-01-01T00:00:10+00:00",
            "risk_verifiable": True,
            "entry_timestamp_verifiable": True,
            "initial_risk": 10,
            "entry_price": 100,
            "initial_stop_loss": 90,
            "initial_quantity": 1,
            "side": "LONG",
            "timeframe": "1m",
        },
        {
            "event_type": "CLOSE_FILL",
            "lifecycle_id": "x",
            "event_at": "2026-01-01T00:03:30+00:00",
            "reason": "MARKET_CLOSE",
            "realized_pnl": 15,
        },
    ]
    start = 1_767_225_660_000
    candles = [
        _candle(start, 110, 95),
        _candle(start + 60_000, 125, 98),
        _candle(start + 120_000, 120, 99),
    ]
    result = ExitAnalyticsService().analyze(
        [], [], lifecycle_events=events, lifecycle_candles={"x": candles}
    )
    assert result.excursion.lifecycles == 1
    assert result.excursion.mae_r == pytest.approx(0.5)
    assert result.excursion.mfe_r == pytest.approx(2.5)
    assert result.excursion.missed_r == pytest.approx(1.0)
    assert result.mae_availability.coverage == 1


def test_excursion_rejects_partial_candle_coverage():
    events = [
        {
            "event_type": "OPEN",
            "lifecycle_id": "x",
            "symbol": "BTCUSDT",
            "event_at": "2026-01-01T00:00:10+00:00",
            "risk_verifiable": True,
            "entry_timestamp_verifiable": True,
            "initial_risk": 10,
            "entry_price": 100,
            "initial_stop_loss": 90,
            "side": "LONG",
            "timeframe": "1m",
        },
        {
            "event_type": "CLOSE_FILL",
            "lifecycle_id": "x",
            "event_at": "2026-01-01T00:03:30+00:00",
            "reason": "MARKET_CLOSE",
            "realized_pnl": 15,
        },
    ]
    result = ExitAnalyticsService().analyze(
        [],
        [],
        lifecycle_events=events,
        lifecycle_candles={"x": [_candle(1_767_225_660_000, 110, 95)]},
    )
    assert result.excursion.mae_r is None
    assert result.mae_availability.available is False
    assert result.mae_availability.coverage == 0


def test_excursion_request_requires_terminal_close_and_bounded_range():
    events = [
        {
            "event_type": "OPEN",
            "lifecycle_id": "x",
            "symbol": "BTCUSDT",
            "event_at": "2026-01-01T00:00:10+00:00",
            "risk_verifiable": True,
            "entry_timestamp_verifiable": True,
            "timeframe": "1m",
        },
        {
            "event_type": "CLOSE_FILL",
            "lifecycle_id": "x",
            "event_at": "2026-01-01T00:03:30+00:00",
            "reason": "MARKET_CLOSE",
        },
    ]
    request = excursion_requests(events)["x"]
    assert request[0:2] == ("BTCUSDT", "1m")
    assert request[-1] == 2


def test_excursion_requires_realized_pnl_evidence():
    events = [
        {
            "event_type": "OPEN",
            "lifecycle_id": "x",
            "symbol": "BTCUSDT",
            "event_at": "2026-01-01T00:00:10+00:00",
            "risk_verifiable": True,
            "entry_timestamp_verifiable": True,
            "initial_risk": 10,
            "entry_price": 100,
            "initial_stop_loss": 90,
            "side": "LONG",
            "timeframe": "1m",
        },
        {
            "event_type": "CLOSE_FILL",
            "lifecycle_id": "x",
            "event_at": "2026-01-01T00:02:30+00:00",
            "reason": "MARKET_CLOSE",
        },
    ]
    start = 1_767_225_660_000
    result = ExitAnalyticsService().analyze(
        [],
        [],
        lifecycle_events=events,
        lifecycle_candles={"x": [_candle(start, 120, 95), _candle(start + 60_000, 115, 98)]},
    )
    assert result.excursion.lifecycles == 0
    assert result.excursion.missed_r is None
