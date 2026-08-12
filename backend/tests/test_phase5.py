import pytest

from app.domain.models import (
    EmergencyStopState,
    Side,
    StrategySignal,
    TradeRecord,
)
from app.services.backtest import BacktestService
from app.services.risk_engine import RiskEngine


def make_signal(**overrides):
    data = {
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "confidence": 0.7,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "take_profits": [105.0, 110.0],
        "leverage": 5,
        "risk_fraction": 0.005,
    }
    data.update(overrides)
    return StrategySignal(**data)


def test_risk_rejects_weekly_drawdown_correlation_and_stale_data():
    engine = RiskEngine()
    common = {
        "open_positions": 0,
        "daily_loss_fraction": 0,
        "emergency_stop": EmergencyStopState(active=False),
    }

    weekly = engine.evaluate(make_signal(), weekly_drawdown_fraction=0.08, **common)
    correlated = engine.evaluate(make_signal(), correlated_positions=2, **common)
    stale = engine.evaluate(make_signal(), data_age_seconds=181, **common)

    assert weekly.accepted is False
    assert weekly.guard.weekly_drawdown == 0.08
    assert correlated.accepted is False
    assert correlated.guard.correlation_risk is True
    assert stale.accepted is False
    assert stale.guard.stale_data is True


def test_risk_rejects_unlimited_dca_and_martingale():
    engine = RiskEngine()
    params = {
        "open_positions": 0,
        "daily_loss_fraction": 0,
        "emergency_stop": EmergencyStopState(active=False),
    }

    martingale = engine.evaluate(make_signal(metadata={"sizing": "martingale"}), **params)
    dca = engine.evaluate(make_signal(metadata={"sizing": "unlimited_dca"}), **params)

    assert martingale.accepted is False
    assert dca.accepted is False


def test_backtest_metrics_include_required_costs_and_ratios():
    trades = [
        TradeRecord(
            id="1",
            symbol="BTCUSDT",
            side=Side.LONG,
            entry_price=100,
            exit_price=110,
            quantity=1,
            gross_pnl=10,
            fee=1,
            slippage=0.2,
            funding=0.1,
            net_pnl=8.7,
            reason="TP",
        ),
        TradeRecord(
            id="2",
            symbol="ETHUSDT",
            side=Side.SHORT,
            entry_price=100,
            exit_price=105,
            quantity=1,
            gross_pnl=-5,
            fee=1,
            slippage=0.2,
            funding=0.1,
            net_pnl=-6.3,
            reason="SL",
        ),
    ]

    metrics = BacktestService().metrics(trades, walk_forward_windows=2, out_of_sample_trades=1)

    assert metrics.pnl == pytest.approx(2.4)
    assert metrics.profit_factor > 1
    assert metrics.fees == 2
    assert metrics.slippage == 0.4
    assert metrics.funding == 0.2
    assert metrics.walk_forward_windows == 2
    assert metrics.out_of_sample_trades == 1
    assert metrics.no_lookahead_bias is True
