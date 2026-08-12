from app.domain.models import BacktestRunRequest, BacktestStrategyConfig, Candle, Side
from app.services.backtest import BacktestService, _Position


def candle(
    index: int, *, open_: float = 100, high: float = 101, low: float = 99, close: float = 100
) -> Candle:
    start = index * 900_000
    return Candle(
        open_time=start,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000,
        close_time=start + 899_999,
    )


def position() -> _Position:
    return _Position(
        side=Side.LONG,
        signal_time=1,
        entry_time=2,
        entry=100,
        stop=95,
        initial_stop_distance=5,
        targets=[105, 109, 113],
        quantity=10,
        remaining=10,
        initial_risk=50,
        entry_fee=0,
        entry_slippage=0,
    )


def test_ambiguous_intrabar_uses_stop_before_take_profit():
    result = BacktestService()._process_candle(
        position(), candle(3, high=106, low=94), BacktestRunRequest(), BacktestStrategyConfig()
    )
    assert result is not None and result.reason == "Stop Loss" and result.gross_pnl < 0


def test_partial_tp_moves_stop_to_break_even_and_never_widens():
    service, trade = BacktestService(), position()
    request = BacktestRunRequest(slippage_bps=0, taker_fee_rate=0, funding_rate_per_8h=0)
    assert (
        service._process_candle(
            trade, candle(3, high=106, low=96, close=105), request, BacktestStrategyConfig()
        )
        is None
    )
    assert trade.remaining == 6 and trade.stop == 100
    old_stop = trade.stop
    service._process_candle(
        trade, candle(4, high=110, low=101, close=109), request, BacktestStrategyConfig()
    )
    assert trade.stop >= old_stop


def test_next_open_entry_and_candidate_isolation(monkeypatch):
    rows = [
        candle(
            i, open_=100 + i * 0.01, high=102 + i * 0.01, low=99 + i * 0.01, close=101 + i * 0.01
        )
        for i in range(260)
    ]
    monkeypatch.setattr("app.services.backtest.score_market", lambda *_: (80, 0, []))
    report = BacktestService().run(
        rows,
        BacktestRunRequest(
            candidate=BacktestStrategyConfig(name="Candidate", min_score=90), slippage_bps=0
        ),
    )
    assert report.candidate_applied is False
    assert report.baseline.config.name == "Baseline"
    assert report.candidate is not None and report.candidate.config.name == "Candidate"
    first = report.baseline.trades[0]
    assert first.entry_time > first.signal_time
    assert len(report.baseline.segments) == 3
    assert report.baseline.metrics.walk_forward_windows == 3
    assert report.dataset_fingerprint


def test_costs_reduce_net_pnl():
    trade = position()
    request = BacktestRunRequest(taker_fee_rate=0.001, slippage_bps=10, funding_rate_per_8h=0.001)
    result = BacktestService()._close(trade, 105, trade.entry_time + 28_800_000, "test", request)
    assert result.fees > 0 and result.funding > 0 and result.slippage > 0
    assert result.net_pnl < result.gross_pnl


def test_optimizer_is_bounded_ranked_and_never_applied(monkeypatch):
    from app.domain.models import BacktestOptimizerRequest

    rows = [candle(i, open_=100, high=103, low=99, close=102) for i in range(280)]
    monkeypatch.setattr("app.services.backtest.score_market", lambda *_: (80, 0, []))
    request = BacktestOptimizerRequest(
        run=BacktestRunRequest(slippage_bps=0),
        min_scores=[70, 75],
        stop_atr_multipliers=[1.0],
        risk_fractions=[0.003],
        minimum_oos_trades=1,
        max_candidates=2,
    )
    report = BacktestService().optimize(rows, request)
    assert report.evaluated_candidates == 2
    assert report.candidate_applied is False
    assert [item.rank for item in report.candidates] == [1, 2]
    assert all(item.report.config.name.startswith("Candidate") for item in report.candidates)


def test_optimizer_rejects_oversized_grid():
    from app.domain.models import BacktestOptimizerRequest

    try:
        BacktestOptimizerRequest(
            min_scores=[60, 65, 70],
            stop_atr_multipliers=[1.0, 1.2, 1.5],
            risk_fractions=[0.003, 0.005],
            max_candidates=10,
        )
    except ValueError as exc:
        assert "vượt giới hạn" in str(exc)
    else:
        raise AssertionError("Optimizer phải từ chối lưới vượt giới hạn")
