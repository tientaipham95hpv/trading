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


def test_realized_r_uses_only_matched_verifiable_lifecycle_evidence():
    events = [
        {
            "event_type": "OPEN",
            "lifecycle_id": "a-demo-BTC-1",
            "risk_verifiable": True,
            "initial_risk": 20,
        },
        {"event_type": "CLOSE_FILL", "lifecycle_id": "a-demo-BTC-1", "realized_pnl": 10},
        {"event_type": "CLOSE_FILL", "lifecycle_id": "legacy", "realized_pnl": 100},
    ]
    result = ExitAnalyticsService().analyze([], [], lifecycle_events=events)
    assert result.realized_r == pytest.approx(0.5)
    assert result.realized_r_availability.available is True
    assert result.realized_r_availability.coverage == pytest.approx(0.5)
