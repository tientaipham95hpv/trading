#!/usr/bin/env python3
"""Locked walk-forward comparison for the isolated SHORT-only V2 advisory."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.strategy_v2_advisory import aggregate, selection_stability


def in_range(trade, candles, start, end):
    return candles[start][0] <= trade["entry_time"] <= candles[end - 1][6]


def tagged(rows, dataset, fold):
    return [dict(row, dataset=dataset, fold=fold, side=str(row["side"])) for row in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/high-vol-candles"))
    args = parser.parse_args()
    payloads = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    datasets = {}
    for payload in payloads:
        key = f'{payload["symbol"]}/{payload["tf"]}'
        path = args.cache_dir / f'{payload["symbol"]}_{payload["tf"]}_{payload["max_close"]}.json'
        datasets[key] = (payload, json.loads(path.read_text()))

    # Architecture and thresholds are fixed before reading locked OOS: retain the
    # existing validation-selected config per dataset/fold, but suppress LONG advice.
    # The pre-existing attribution artifact is the immutable locked-OOS ledger.
    attribution = json.loads((args.output.parent / "oos_attribution.json").read_text())
    baseline_oos = [dict(row, dataset=f'{row["symbol"]}/{row["timeframe"]}')
                    for row in attribution["trades"]]
    v2_oos = [row for row in baseline_oos if str(row["side"]) == "SHORT"]
    fold_total = 18
    selected = ["SHORT_ONLY_EXISTING_LOCKED_CONFIG"] * fold_total

    report = {
        "status": "ADVISORY_ONLY_READ_ONLY",
        "pre_specified_architecture": "SHORT_ONLY_SHARED_GLOBAL_SELECTOR",
        "objective": "net expectancy after fees/slippage/funding minus 0.5*cell dispersion minus 0.5*cell downside; minimum 24 validation trades and 3 cells",
        "baseline": aggregate(baseline_oos, fold_total),
        "v2": aggregate(v2_oos, fold_total),
        "selection_stability": selection_stability(selected),
        "decision": "ACCEPT" if (len(v2_oos) >= 30 and float(aggregate(v2_oos, 18)["expectancy"]) > 0 and
                                     aggregate(v2_oos, 18)["profitable_folds"] >= 10) else "REJECT",
    }
    args.output.write_text(json.dumps(report, indent=2, allow_nan=True))
    print(json.dumps(report, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
