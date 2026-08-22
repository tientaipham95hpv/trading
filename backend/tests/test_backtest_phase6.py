import pytest

from app.domain.models import BacktestRunRequest, BacktestStrategyConfig, Candle, MarketRegime, Side
from app.services.backtest import BacktestService, _Position, _SignalFeature


def candle(
    index: int,
    *,
    open_: float = 100,
    high: float = 101,
    low: float = 99,
    close: float = 100,
    interval_ms: int = 900_000,
) -> Candle:
    start = index * interval_ms
    return Candle(
        open_time=start,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000,
        close_time=start + interval_ms - 1,
    )


def mtf(rows: list[Candle]) -> dict[str, list[Candle]]:
    count = len(rows)
    final_close = rows[-1].close_time

    def higher(interval_ms: int) -> list[Candle]:
        result = []
        first_open = final_close + 1 - count * interval_ms
        for index in range(count):
            start = first_open + index * interval_ms
            result.append(
                Candle(
                    open_time=start,
                    open=100 + index * 0.04,
                    high=102 + index * 0.04,
                    low=99 + index * 0.04,
                    close=101 + index * 0.04,
                    volume=1000,
                    close_time=start + interval_ms - 1,
                )
            )
        return result

    return {"15m": rows, "1h": higher(3_600_000), "4h": higher(14_400_000)}


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
    monkeypatch.setattr("app.services.backtest.score_market", lambda *_: (80, 0, ["Breakout"]))
    monkeypatch.setattr("app.services.backtest.detect_regime", lambda *_: MarketRegime.TRENDING_UP)
    report = BacktestService().run(
        mtf(rows),
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
    assert [segment.name for segment in report.baseline.walk_forward] == [
        "WF-1-TRAIN-0:156-TEST-156:191",
        "WF-2-TRAIN-0:191-TEST-191:226",
        "WF-3-TRAIN-0:226-TEST-226:260",
    ]
    assert report.baseline.walk_forward[0].end_time < report.baseline.walk_forward[1].start_time
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
        minimum_oos_trades=100,
        max_candidates=2,
    )
    report = BacktestService().optimize(mtf(rows), request)
    assert report.evaluated_candidates == 2
    assert report.candidate_applied is False
    assert [item.rank for item in report.candidates] == [1, 2]
    assert all(item.report.config.name.startswith("Candidate") for item in report.candidates)
    assert all(not item.eligible for item in report.candidates)
    assert all(item.stitched_oos.metrics.out_of_sample_trades < 100 for item in report.candidates)
    assert all(
        any("Stitched OOS" in reason for reason in item.rejection_reasons)
        for item in report.candidates
    )
    assert all(0 <= item.profitable_walk_forward_ratio <= 1 for item in report.candidates)


def test_optimizer_reuses_locked_prefix_without_changing_selection(monkeypatch):
    from app.domain.models import BacktestOptimizerRequest

    monkeypatch.setattr("app.services.backtest.score_market", lambda *_: (80, 0, []))
    rows = [candle(i, open_=100, high=103, low=99, close=102) for i in range(300)]
    request = BacktestOptimizerRequest(
        run=BacktestRunRequest(slippage_bps=0),
        min_scores=[75, 85],
        stop_atr_multipliers=[1.2],
        risk_fractions=[0.0025],
        folds=3,
        minimum_validation_trades=1,
    )
    service = BacktestService()
    original_simulate = service._simulate
    calls: list[tuple[str, int]] = []

    def counted(candles, run, config, features=None):
        calls.append((config.model_dump_json(), len(candles)))
        return original_simulate(candles, run, config, features)

    monkeypatch.setattr(service, "_simulate", counted)
    report = service.optimize(mtf(rows), request)

    assert len(calls) == len(set(calls))
    assert [fold.test_end for fold in report.folds[:-1]] == [
        fold.test_start for fold in report.folds[1:]
    ]
    assert all(fold.validation_end == fold.test_start for fold in report.folds)


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


def test_optimizer_fold_selection_does_not_look_at_its_oos(monkeypatch):
    from app.domain.models import BacktestOptimizerRequest

    monkeypatch.setattr("app.services.backtest.score_market", lambda *_: (80, 0, []))
    rows = [candle(i, open_=100, high=103, low=99, close=102) for i in range(300)]
    request = BacktestOptimizerRequest(
        run=BacktestRunRequest(slippage_bps=0),
        min_scores=[75, 85],
        stop_atr_multipliers=[1.2, 1.8],
        risk_fractions=[0.0025],
        folds=3,
        minimum_validation_trades=1,
        minimum_oos_trades=100,
    )
    original = BacktestService().optimize(mtf(rows), request)
    first = original.folds[0]
    changed = list(rows)
    for index in range(first.test_start, first.test_end):
        changed[index] = candle(index, open_=500, high=900, low=10, close=700)
    rerun = BacktestService().optimize(mtf(changed), request)

    assert rerun.folds[0].selected_config_fingerprint == first.selected_config_fingerprint
    assert rerun.folds[0].validation_score == first.validation_score
    assert first.validation_end == first.test_start
    assert original.selection_policy == "ROLLING_TRAIN_VALIDATION_OOS_V2_FAIL_CLOSED"


def test_backtest_symbol_universe_is_fail_closed_and_normalized():
    assert BacktestRunRequest(symbol=" ethusdt ").symbol == "ETHUSDT"
    with pytest.raises(ValueError, match="BTCUSDT, ETHUSDT và SOLUSDT"):
        BacktestRunRequest(symbol="BNBUSDT")


def test_optimizer_requires_at_least_100_stitched_oos_trades():
    from app.domain.models import BacktestOptimizerRequest

    with pytest.raises(ValueError):
        BacktestOptimizerRequest(minimum_oos_trades=99)


def test_mtf_alignment_uses_only_higher_candles_closed_by_signal(monkeypatch):
    rows = [candle(i) for i in range(260)]
    data = mtf(rows)

    def indexed_features(candles):
        return {
            index: _SignalFeature(
                long_score=index,
                short_score=0,
                regime=MarketRegime.TRENDING_UP,
                atr=1,
                close=row.close,
                ema20=row.close,
                reasons=("Breakout",),
            )
            for index, row in enumerate(candles)
        }

    service = BacktestService()
    monkeypatch.setattr(service, "_precompute_features", indexed_features)
    aligned = service._precompute_mtf_features(data)
    signal_index = 230
    signal_time = rows[signal_index].close_time
    features = aligned[signal_index]
    assert features is not None
    _, h1, h4 = features
    expected_h1 = max(
        index for index, row in enumerate(data["1h"]) if row.close_time <= signal_time
    )
    expected_h4 = max(
        index for index, row in enumerate(data["4h"]) if row.close_time <= signal_time
    )
    assert h1.long_score == expected_h1
    assert h4.long_score == expected_h4
    assert data["1h"][expected_h1 + 1].close_time > signal_time
    assert data["4h"][expected_h4 + 1].close_time > signal_time


def test_mtf_fails_closed_for_missing_or_stale_higher_timeframes():
    rows = [candle(i) for i in range(260)]
    service = BacktestService()
    with pytest.raises(ValueError, match="đủ nến đóng 15m, 1h và 4h"):
        service.run({"15m": rows}, BacktestRunRequest())

    data = mtf(rows)
    # Move all 4h evidence into the future: no 4h candle is causally available.
    data["4h"] = [
        row.model_copy(
            update={"open_time": row.open_time + 10**12, "close_time": row.close_time + 10**12}
        )
        for row in data["4h"]
    ]
    report = service.run(data, BacktestRunRequest())
    assert report.baseline.trades == []


def test_signal_funnel_is_monotonic_and_candidate_specific(monkeypatch):
    rows = [candle(i, open_=100, high=103, low=99, close=102) for i in range(280)]
    monkeypatch.setattr("app.services.backtest.score_market", lambda *_: (80, 0, ["Breakout"]))
    monkeypatch.setattr("app.services.backtest.detect_regime", lambda *_: MarketRegime.TRENDING_UP)
    report = BacktestService().run(
        mtf(rows),
        BacktestRunRequest(candidate=BacktestStrategyConfig(name="Strict", min_score=90)),
    )
    baseline = report.baseline.signal_funnel
    # `rejection_reasons` is diagnostic metadata, not a monotonic funnel stage.
    values = list(baseline.model_dump(exclude={"rejection_reasons"}).values())
    assert values == sorted(values, reverse=True)
    assert baseline.actionable > 0
    assert report.candidate is not None
    assert report.candidate.signal_funnel.actionable == 0


def test_history_days_is_research_only_and_bounded():
    assert BacktestRunRequest(history_days=365).history_days == 365
    with pytest.raises(ValueError):
        BacktestRunRequest(history_days=731)
