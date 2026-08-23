import pytest

from app.api.routes import _exchange_performance, _performance_income_rows
from app.domain.models import (
    EmergencyStopState,
    ExchangeOrder,
    ExchangePosition,
    ExchangeSnapshot,
    Side,
    StrategySignal,
    TradeRecord,
    TradingMode,
)
from app.services.auto_trader import AutoTrader
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


def test_exchange_performance_exposes_capital_return_and_trade_outcomes():
    snapshot = ExchangeSnapshot(
        mode=TradingMode.DEMO,
        balance={
            "asset": "USDT",
            "balance": 10_075,
            "available": 9_000,
            "margin_balance": 10_095,
            "unrealized_pnl": 20,
        },
    )
    income = [
        {"incomeType": "REALIZED_PNL", "income": "100"},
        {"incomeType": "REALIZED_PNL", "income": "-20"},
        {"incomeType": "COMMISSION", "income": "-5"},
    ]

    performance = _exchange_performance(snapshot, income)

    assert performance.initial_capital == pytest.approx(10_000)
    assert performance.net_pnl == pytest.approx(75)
    assert performance.equity_pnl == pytest.approx(95)
    assert performance.non_trading_balance_change == pytest.approx(0)
    assert performance.return_percent == pytest.approx(0.75)
    assert performance.equity_return_percent == pytest.approx(0.95)
    assert performance.realized_pnl_events == 2
    assert performance.winning_realized_pnl_events == 1
    assert performance.losing_realized_pnl_events == 1
    assert performance.breakeven_realized_pnl_events == 0
    # Legacy aliases remain stable for existing API clients.
    assert performance.total_trades == 2
    assert performance.winning_trades == 1
    assert performance.losing_trades == 1
    assert performance.breakeven_trades == 0


def test_exchange_performance_keeps_snapshotted_initial_capital():
    snapshot = ExchangeSnapshot(
        mode=TradingMode.LIVE,
        balance={
            "asset": "USDT",
            "balance": 1_025,
            "available": 1_025,
            "margin_balance": 1_025,
            "unrealized_pnl": 0,
        },
    )

    performance = _exchange_performance(
        snapshot,
        [{"incomeType": "REALIZED_PNL", "income": "25"}],
        initial_capital=1_000,
    )

    assert performance.initial_capital == 1_000
    assert performance.net_pnl == 25
    assert performance.non_trading_balance_change == 0
    assert performance.return_percent == pytest.approx(2.5)


async def test_performance_income_fetches_realized_pnl_with_typed_limit():
    class Adapter:
        def __init__(self):
            self.calls = []

        async def income_history(self, *, income_type=None, limit=100, start_time=None):
            self.calls.append((income_type, limit, start_time))
            if income_type == "REALIZED_PNL":
                return [
                    {"incomeType": "REALIZED_PNL", "income": "1", "time": "9999999999999"}
                    for _ in range(250)
                ]
            if income_type == "COMMISSION":
                return [{"incomeType": "COMMISSION", "income": "-0.1", "time": "9999999999999"}]
            if income_type == "FUNDING_FEE":
                return [{"incomeType": "FUNDING_FEE", "income": "0.01", "time": "9999999999999"}]
            return []

    adapter = Adapter()

    rows = await _performance_income_rows(adapter)

    assert [call[:2] for call in adapter.calls] == [
        ("REALIZED_PNL", 500),
        ("COMMISSION", 500),
        ("FUNDING_FEE", 500),
    ]
    assert sum(row["incomeType"] == "REALIZED_PNL" for row in rows) == 250


def test_exchange_watchdog_treats_open_orders_as_busy_symbols():
    snapshot = ExchangeSnapshot(
        mode=TradingMode.DEMO,
        positions=[
            ExchangePosition(
                symbol="BTCUSDT",
                side="LONG",
                quantity=1,
                entry_price=100,
                mark_price=101,
            )
        ],
        orders=[
            ExchangeOrder(
                symbol="UNIUSDT",
                order_id=1,
                client_order_id="orphan",
                side="SELL",
                order_type="STOP_MARKET",
                status="NEW",
                stop_price=95,
            )
        ],
    )

    assert AutoTrader._busy_exchange_symbols(snapshot) == {"BTCUSDT", "UNIUSDT"}


def test_auto_trader_rejection_summary_uses_actual_reasons_without_ai_label():
    summary = AutoTrader._rejection_summary(
        {
            "Bỏ qua khung nhiễu 1m/5m": 2,
            "Tránh vùng biến động cao/panic": 1,
        }
    )

    assert summary == (
        "Có tín hiệu nhưng chưa đủ điều kiện: "
        "Bỏ qua khung nhiễu 1m/5m (2); Tránh vùng biến động cao/panic (1)"
    )
    assert "AI" not in summary


def test_exchange_watchdog_detects_position_without_protective_stop():
    snapshot = ExchangeSnapshot(
        mode=TradingMode.DEMO,
        positions=[
            ExchangePosition(
                symbol="BTCUSDT",
                side="LONG",
                quantity=1,
                entry_price=100,
                mark_price=101,
            ),
            ExchangePosition(
                symbol="ETHUSDT",
                side="SHORT",
                quantity=1,
                entry_price=100,
                mark_price=99,
            ),
        ],
        orders=[
            ExchangeOrder(
                symbol="BTCUSDT",
                order_id=1,
                client_order_id="sl",
                side="SELL",
                order_type="STOP_MARKET",
                status="NEW",
                stop_price=98,
            ),
            ExchangeOrder(
                symbol="ETHUSDT",
                order_id=2,
                client_order_id="wrong",
                side="SELL",
                order_type="STOP_MARKET",
                status="NEW",
                stop_price=95,
            ),
        ],
    )

    assert AutoTrader._unprotected_exchange_positions(snapshot) == ["ETHUSDT"]
