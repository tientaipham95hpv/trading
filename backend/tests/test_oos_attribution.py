import math

import pytest

from app.domain.models import Candle
from app.services.oos_attribution import (
    build_side_exit_analysis,
    extract_oos,
    high_vol_flags,
    metrics,
)


def _payload():
    trades = [
        {
            "side": "LONG",
            "entry_time": 10,
            "exit_time": 11,
            "net_pnl": 2.0,
            "r_multiple": 1.0,
            "fees": 0.2,
            "slippage": 0.1,
            "funding": 0.0,
        },
        {
            "side": "SHORT",
            "entry_time": 20,
            "exit_time": 21,
            "net_pnl": -1.0,
            "r_multiple": -0.5,
            "fees": 0.2,
            "slippage": 0.1,
            "funding": 0.1,
        },
        {
            "side": "LONG",
            "entry_time": 30,
            "exit_time": 31,
            "net_pnl": 99.0,
            "r_multiple": 9.0,
            "fees": 1.0,
            "slippage": 1.0,
            "funding": 1.0,
        },
    ]
    return {
        "symbol": "BTCUSDT",
        "tf": "1h",
        "report": {
            "candidates": [
                {"report": {"config_fingerprint": "chosen", "trades": trades}},
                {"report": {"config_fingerprint": "other", "trades": trades}},
            ],
            "folds": [
                {
                    "number": 1,
                    "selected_config_fingerprint": "chosen",
                    "test": {"start_time": 10, "end_time": 20, "metrics": {"trades": 2}},
                }
            ],
        },
    }


def test_extract_oos_uses_selected_candidate_and_test_window_only():
    rows = extract_oos([_payload()])
    assert [row["entry_time"] for row in rows] == [10, 20]
    assert all(row["fold"] == 1 for row in rows)


def test_extract_oos_rejects_fold_count_mismatch():
    payload = _payload()
    payload["report"]["folds"][0]["test"]["metrics"]["trades"] = 3
    with pytest.raises(ValueError, match="mismatch"):
        extract_oos([payload])


def test_metrics_net_pf_and_streak():
    rows = extract_oos([_payload()])
    result = metrics(rows)
    assert result["net_pnl"] == 1
    assert result["pf"] == 2
    assert result["expectancy"] == 0.5
    assert result["avg_r"] == 0.25
    assert result["win_rate"] == 0.5
    assert result["max_loss_streak"] == 1
    assert not math.isinf(result["pf"])


def test_high_vol_threshold_uses_exactly_100_prior_closed_candles():
    candles = []
    for index in range(116):
        spread = 10.0 if index == 115 else 1.0
        candles.append(
            Candle(
                open_time=index * 10,
                close_time=index * 10 + 9,
                open=100,
                high=100 + spread,
                low=100,
                close=100,
                volume=1,
            )
        )
    flags = high_vol_flags(candles)
    assert flags[113] is False  # only 99 prior ATR observations
    assert flags[114] is True  # first index with exactly 100 prior observations
    assert flags[115] is True


def test_high_vol_flag_has_no_future_leakage():
    candles = [
        Candle(
            open_time=i * 10,
            close_time=i * 10 + 9,
            open=100,
            high=101 + (i % 5),
            low=99,
            close=100,
            volume=1,
        )
        for i in range(130)
    ]
    before = high_vol_flags(candles)[120]
    candles[129] = candles[129].model_copy(update={"high": 10000})
    assert high_vol_flags(candles)[120] == before


def test_side_exit_analysis_keeps_empty_regime_cells_explicit():
    rows = extract_oos([_payload()])
    for row in rows:
        row["reason"] = "Stop Loss"
        row["symbol"] = "BTCUSDT"
        row["timeframe"] = "1h"
        row["regime"] = {
            name: False for name in ("trend", "range", "high_vol", "panic", "oversold")
        }
    report = build_side_exit_analysis(rows)
    assert report["by_side_exit"]["LONG/Stop Loss"]["trades"] == 1
    assert report["stop_loss_by_side_regime"]["SHORT"]["panic"]["trades"] == 0
    assert report["consistency"]["LONG"]["nonempty_dataset_folds"] == 1
