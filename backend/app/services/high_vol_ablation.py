"""Causal walk-forward ablation of a single high-volatility entry gate."""

from __future__ import annotations

import hashlib
from typing import Any

from app.domain.models import BacktestRunRequest, BacktestStrategyConfig, Candle
from app.services.backtest import BacktestService
from app.services.oos_attribution import gated_features, high_vol_flags, metrics


def _fingerprint(config: BacktestStrategyConfig) -> str:
    return hashlib.sha256(config.model_dump_json().encode()).hexdigest()


def _rows(report: Any, candles: list[Candle], start: int, end: int) -> list[dict[str, Any]]:
    low, high = candles[start].open_time, candles[end - 1].close_time
    return [
        trade.model_dump(mode="json") for trade in report.trades if low <= trade.entry_time <= high
    ]


def build_ablation(
    payloads: list[dict[str, Any]], datasets: dict[tuple[str, str], list[Candle]]
) -> dict[str, Any]:
    service = BacktestService()
    selected_rows: dict[str, list[dict[str, Any]]] = {"baseline": [], "gate": []}
    fixed_rows: dict[str, list[dict[str, Any]]] = {"baseline": [], "gate": []}
    fold_results = []
    for payload in payloads:
        symbol, timeframe = payload["symbol"], payload["tf"]
        candles = datasets[(symbol, timeframe)]
        request = BacktestRunRequest(symbol=symbol, interval=timeframe, limit=len(candles))
        features = service._precompute_features(candles)
        gate_features = gated_features(features, high_vol_flags(candles))
        configs = [
            BacktestStrategyConfig.model_validate(row["report"]["config"])
            for row in payload["report"]["candidates"]
        ]
        cache: dict[tuple[str, str, int], Any] = {}

        def simulate(
            config: BacktestStrategyConfig,
            variant: str,
            end: int,
            *,
            cache: dict[tuple[str, str, int], Any] = cache,
            candles: list[Candle] = candles,
            request: BacktestRunRequest = request,
            features: dict[int, Any] = features,
            gate_features: dict[int, Any] = gate_features,
        ) -> Any:
            key = (_fingerprint(config), variant, end)
            if key not in cache:
                cache[key] = service._simulate(
                    candles[:end], request, config, gate_features if variant == "gate" else features
                )
            return cache[key]

        for fold in payload["report"]["folds"]:
            start, end = fold["test_start"], fold["test_end"]
            validation_start = fold["validation_start"]
            choices = []
            for config in configs:
                for variant in ("baseline", "gate"):
                    report = simulate(config, variant, start)
                    segment = service._segment_for_range(
                        report.trades,
                        candles,
                        validation_start,
                        start,
                        request.initial_capital,
                        "VALIDATION",
                    )
                    eligible = segment.metrics.trades >= 5
                    choices.append(
                        (
                            eligible,
                            service._validation_score(segment),
                            config,
                            variant,
                            segment.metrics.trades,
                        )
                    )
            choices.sort(key=lambda row: (row[0], row[1]), reverse=True)
            eligible, score, config, variant, validation_trades = choices[0]
            test_rows = _rows(simulate(config, variant, end), candles, start, end)
            for row in test_rows:
                row.update(symbol=symbol, timeframe=timeframe, fold=fold["number"])
            selected_rows[variant].extend(test_rows)

            fixed_config = BacktestStrategyConfig.model_validate(fold["selected_config"])
            paired = {}
            for fixed_variant in ("baseline", "gate"):
                rows = _rows(simulate(fixed_config, fixed_variant, end), candles, start, end)
                for row in rows:
                    row.update(symbol=symbol, timeframe=timeframe, fold=fold["number"])
                fixed_rows[fixed_variant].extend(rows)
                paired[fixed_variant] = metrics(rows)
            base_keys = {
                (r["signal_time"], r["side"])
                for r in _rows(simulate(fixed_config, "baseline", end), candles, start, end)
            }
            gate_keys = {
                (r["signal_time"], r["side"])
                for r in _rows(simulate(fixed_config, "gate", end), candles, start, end)
            }
            fold_results.append(
                {
                    "dataset": f"{symbol}/{timeframe}",
                    "fold": fold["number"],
                    "selected_variant": variant,
                    "selected_config": config.model_dump(),
                    "validation_score": score,
                    "validation_trades": validation_trades,
                    "eligible": eligible,
                    "oos": metrics(test_rows),
                    "paired_fixed_rule": paired,
                    "paired_removed_trades": len(base_keys - gate_keys),
                }
            )

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        overall = metrics(rows)
        grouped = {}
        for row in rows:
            grouped.setdefault(f"{row['symbol']}/{row['timeframe']}/F{row['fold']}", []).append(row)
        per_fold = {key: metrics(value) for key, value in sorted(grouped.items())}
        overall["folds_profitable"] = sum(value["net_pnl"] > 0 for value in per_fold.values())
        overall["folds_total"] = len(per_fold)
        return {"overall": overall, "per_dataset_fold": per_fold}

    return {
        "definition": "Block entry when signal-time ATR14/close >= nearest-rank p80 of exactly 100 prior closed candles; current candle excluded from threshold",
        "selection": "For every fold, config and baseline/gate variant are ranked on validation only and locked before OOS",
        "selected_walk_forward": {
            "combined": summarize(selected_rows["baseline"] + selected_rows["gate"]),
            "by_selected_variant": {key: summarize(value) for key, value in selected_rows.items()},
        },
        "paired_fixed_rule": {key: summarize(value) for key, value in fixed_rows.items()},
        "folds": fold_results,
    }
