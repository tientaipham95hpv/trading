"""Read-only Strategy V2 research helpers; intentionally disconnected from runtime."""

import math
from collections import Counter, defaultdict
from statistics import mean, pstdev
from typing import Any

MINIMUM_VALIDATION_TRADES = 24
MINIMUM_CELL_TRADES = 2
ROBUSTNESS_WEIGHT = 0.50


def metrics(trades: list[dict[str, Any]]) -> dict[str, float | int]:
    pnl = [float(row["net_pnl"]) for row in trades]
    wins = sum(value for value in pnl if value > 0)
    losses = -sum(value for value in pnl if value <= 0)
    return {
        "trades": len(trades),
        "net_pnl": sum(pnl),
        "pf": wins / losses if losses else (math.inf if wins else 0.0),
        "expectancy": mean(pnl) if pnl else 0.0,
        "avg_r": mean(float(row["r_multiple"]) for row in trades) if trades else 0.0,
    }


def robust_validation_objective(
    cells: dict[str, list[dict[str, Any]]], *, minimum_trades: int = MINIMUM_VALIDATION_TRADES
) -> tuple[float, bool, dict[str, Any]]:
    """Net expectancy minus dispersion/downside penalties across side/dataset/fold cells."""
    all_trades = [trade for rows in cells.values() for trade in rows]
    populated = [metrics(rows) for rows in cells.values() if len(rows) >= MINIMUM_CELL_TRADES]
    eligible = len(all_trades) >= minimum_trades and len(populated) >= 3
    expectancy = float(metrics(all_trades)["expectancy"])
    cell_expectancies = [float(row["expectancy"]) for row in populated]
    dispersion = pstdev(cell_expectancies) if len(cell_expectancies) > 1 else 0.0
    downside = mean(max(0.0, -value) for value in cell_expectancies) if populated else math.inf
    score = expectancy - ROBUSTNESS_WEIGHT * dispersion - ROBUSTNESS_WEIGHT * downside
    return (
        score if eligible else -math.inf,
        eligible,
        {
            "net_expectancy": expectancy,
            "dispersion_penalty": ROBUSTNESS_WEIGHT * dispersion,
            "downside_penalty": ROBUSTNESS_WEIGHT * downside,
            "trades": len(all_trades),
            "populated_cells": len(populated),
        },
    )


def aggregate(trades: list[dict[str, Any]], fold_total: int) -> dict[str, Any]:
    result = metrics(trades)
    folds = defaultdict(list)
    sides = defaultdict(list)
    datasets = defaultdict(list)
    for trade in trades:
        folds[f"{trade['dataset']}/F{trade['fold']}"].append(trade)
        sides[str(trade["side"])].append(trade)
        datasets[str(trade["dataset"])].append(trade)
    result.update(
        {
            "profitable_folds": sum(float(metrics(rows)["net_pnl"]) > 0 for rows in folds.values()),
            "folds_total": fold_total,
            "by_side": {key: metrics(rows) for key, rows in sorted(sides.items())},
            "by_dataset": {key: metrics(rows) for key, rows in sorted(datasets.items())},
        }
    )
    return result


def selection_stability(fingerprints: list[str]) -> dict[str, Any]:
    counts = Counter(fingerprints)
    return {
        "unique_configs": len(counts),
        "modal_share": max(counts.values()) / len(fingerprints) if fingerprints else 0.0,
        "counts": dict(sorted(counts.items())),
    }
