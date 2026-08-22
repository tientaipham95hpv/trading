#!/usr/bin/env python3
"""Run the frozen, advisory-only V3 trend-pullback experiment."""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.oos_attribution import fetch_candles
from app.services.strategy_v3_trend_pullback import (dataset_fingerprint, fingerprint,
                                                     metrics, select, simulate)


def grouped(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return {name: metrics(items) for name, items in sorted(groups.items())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--prior-ledger", type=Path, default=Path("reports/oos_attribution.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/strategy-v3-candles"))
    args = parser.parse_args()
    old = json.loads(args.prior_ledger.read_text())
    old_times = [int(row[k]) for row in old["trades"] for k in ("signal_time", "entry_time", "exit_time") if row.get(k)]
    old_min = min(old_times)
    fetch_end = old_min - 1
    datasets, all_oos, folds = {}, [], []
    selected_ids = []
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        for timeframe in ("1h", "4h"):
            candles = fetch_candles(symbol, timeframe, fetch_end, args.cache_dir)
            candles = [row for row in candles if row.close_time < old_min and row.close_time <= fetch_end]
            if len(candles) < 1200 or max(row.close_time for row in candles) >= old_min:
                raise RuntimeError(f"Cannot prove sufficient disjoint closed data: {symbol}/{timeframe}")
            name = f"{symbol}/{timeframe}"
            datasets[name] = {"candles": len(candles), "start": candles[0].open_time, "end": candles[-1].close_time,
                              "fingerprint": dataset_fingerprint(candles), "strictly_before_prior_locked_min": old_min,
                              "disjoint": candles[-1].close_time < old_min}
            usable_start = 205
            block = (len(candles) - usable_start) // 5
            for number in range(3):
                validation_start = usable_start + number * block
                test_start = validation_start + block
                test_end = test_start + block
                config, candidates, eligible = select(candles, validation_start, test_start)
                locked = fingerprint(config)
                trades = simulate(candles, config, test_start, test_end)
                tagged = [dict(row, dataset=name, symbol=symbol, timeframe=timeframe, fold=number + 1,
                               config=config.id) for row in trades]
                all_oos.extend(tagged)
                selected_ids.append(config.id)
                folds.append({"dataset": name, "fold": number + 1, "train": [candles[0].open_time, candles[validation_start - 1].close_time],
                              "validation": [candles[validation_start].open_time, candles[test_start - 1].close_time],
                              "oos": [candles[test_start].open_time, candles[test_end - 1].close_time],
                              "selected_config": asdict(config), "config_fingerprint": locked,
                              "selection_eligible": eligible, "validation_candidates": candidates,
                              "oos_metrics": metrics(tagged)})
    aggregate = metrics(all_oos)
    by_chrono_fold = grouped(all_oos, "fold")
    profitable = sum(row["pnl"] > 0 for row in by_chrono_fold.values())
    by_symbol = grouped(all_oos, "symbol")
    positive_total = sum(max(0.0, row["pnl"]) for row in by_symbol.values())
    concentration = max((max(0.0, row["pnl"]) / positive_total for row in by_symbol.values()), default=1.0)
    other_symbols_positive = sum(sorted((row["pnl"] for row in by_symbol.values()), reverse=True)[1:]) > 0
    checks = {"minimum_30_trades": aggregate["trades"] >= 30, "pf_above_1_2": aggregate["pf"] > 1.2,
              "positive_expectancy": aggregate["expectancy"] > 0, "positive_avg_r": aggregate["avg_r"] > 0,
              "two_of_three_chrono_folds_profitable": profitable >= 2,
              "not_one_symbol_dependent": concentration <= 0.70 and other_symbols_positive}
    counts = Counter(selected_ids)
    report = {"status": "ADVISORY_ONLY_READ_ONLY", "decision": "PROMOTE" if all(checks.values()) else "REJECT",
              "promotion_checks": checks, "prior_locked_ledger": {"trades": len(old["trades"]), "minimum_timestamp": old_min,
              "used_for_logic_or_selection": False}, "datasets": datasets, "aggregate_oos": aggregate,
              "by_dataset": grouped(all_oos, "dataset"), "by_symbol": by_symbol, "by_side": grouped(all_oos, "side"),
              "by_chronological_fold": by_chrono_fold, "profitable_chronological_folds": profitable,
              "selection_stability": {"counts": dict(counts), "unique": len(counts), "modal_share": max(counts.values()) / len(selected_ids)},
              "folds": folds, "oos_trades": all_oos,
              "tests": {"causality": all(row["signal_time"] < row["entry_time"] <= row["exit_time"] for row in all_oos),
                        "disjointness": all(row["disjoint"] for row in datasets.values())}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=True))
    print(json.dumps({k: report[k] for k in ("decision", "promotion_checks", "aggregate_oos", "by_dataset")}, indent=2))


if __name__ == "__main__":
    main()
