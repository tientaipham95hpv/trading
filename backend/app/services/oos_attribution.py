"""Leak-free attribution for optimizer fold test trades.

Trades are reconstructed from the candidate selected by each fold fingerprint, then
filtered only by that fold's test timestamps. Entry regimes use candles closed at or
before signal_time (never the entry candle unless it had already closed).
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.domain.models import BacktestRunRequest, BacktestStrategyConfig, Candle
from app.services.backtest import BacktestService
from app.services.indicators import calculate_indicators

HIGH_VOL_LOOKBACK = 100
HIGH_VOL_PERCENTILE = 0.80


def high_vol_flags(candles: list[Candle]) -> dict[int, bool]:
    """Flag signal candles using only that close and the 100 earlier closes."""
    true_ranges = [0.0]
    for previous, current in pairwise(candles):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    atr_pct: list[float | None] = [None] * len(candles)
    for index in range(14, len(candles)):
        atr_pct[index] = sum(true_ranges[index - 13 : index + 1]) / 14 / candles[index].close
    flags = {}
    for index, current in enumerate(atr_pct):
        prior = [
            value
            for value in atr_pct[max(0, index - HIGH_VOL_LOOKBACK) : index]
            if value is not None
        ]
        if current is None or len(prior) != HIGH_VOL_LOOKBACK:
            flags[index] = False
            continue
        ordered = sorted(prior)
        # Nearest-rank percentile: p80 of exactly 100 prior observations.
        threshold = ordered[math.ceil(HIGH_VOL_PERCENTILE * len(ordered)) - 1]
        flags[index] = current >= threshold
    return flags


def gated_features(features: dict[int, Any], flags: dict[int, bool]) -> dict[int, Any]:
    """Suppress entry scores at high volatility without changing exits or sizing."""
    return {
        index: replace(feature, long_score=0, short_score=0) if flags.get(index) else feature
        for index, feature in features.items()
    }


def extract_oos(
    payloads: list[dict[str, Any]],
    fold_trades: dict[tuple[str, str, int], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    result = []
    seen: set[tuple[Any, ...]] = set()
    for payload in payloads:
        report = payload["report"]
        candidates = {
            row["report"]["config_fingerprint"]: row["report"]["trades"]
            for row in report["candidates"]
        }
        for fold in report["folds"]:
            segment = fold["test"]
            trades = (
                fold_trades[(payload["symbol"], payload["tf"], fold["number"])]
                if fold_trades is not None
                else candidates[fold["selected_config_fingerprint"]]
            )
            selected = [
                trade
                for trade in trades
                if segment["start_time"] <= trade["entry_time"] <= segment["end_time"]
            ]
            if len(selected) != segment["metrics"]["trades"]:
                raise ValueError(
                    f"Fold {payload['symbol']}/{payload['tf']}/{fold['number']} mismatch"
                )
            for trade in selected:
                key = (
                    payload["symbol"],
                    payload["tf"],
                    fold["number"],
                    trade["entry_time"],
                    trade["exit_time"],
                    trade["side"],
                )
                if key in seen:
                    raise ValueError(f"Duplicate OOS trade: {key}")
                seen.add(key)
                result.append(
                    {
                        **trade,
                        "symbol": payload["symbol"],
                        "timeframe": payload["tf"],
                        "fold": fold["number"],
                    }
                )
    return result


def fetch_candles(symbol: str, timeframe: str, end_time: int, cache_dir: Path) -> list[Candle]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{symbol}_{timeframe}_{end_time}.json"
    if path.exists():
        rows = json.loads(path.read_text())
    else:
        rows: list[list[Any]] = []
        cursor = end_time
        while len(rows) < 5000:
            query = urllib.parse.urlencode(
                {
                    "symbol": symbol,
                    "interval": timeframe,
                    "limit": min(1000, 5000 - len(rows)),
                    "endTime": cursor,
                }
            )
            with urllib.request.urlopen(
                f"https://fapi.binance.com/fapi/v1/klines?{query}", timeout=30
            ) as response:
                page = json.load(response)
            if not page:
                break
            rows = page + rows
            cursor = int(page[0][0]) - 1
        path.write_text(json.dumps(rows, separators=(",", ":")))
    return [
        Candle(
            open_time=int(r[0]),
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=float(r[5]),
            close_time=int(r[6]),
            quote_volume=float(r[7]),
        )
        for r in rows
    ]


def attach_regimes(
    trades: list[dict[str, Any]], candles_by_dataset: dict[tuple[str, str], list[Candle]]
) -> None:
    for trade in trades:
        candles = candles_by_dataset[(trade["symbol"], trade["timeframe"])]
        history = [c for c in candles if c.close_time <= trade["signal_time"]][-250:]
        if len(history) < 201:
            trade["regime"] = {"mapped": False}
            continue
        ind = calculate_indicators(history)
        close = history[-1].close
        atr_pct = (ind.atr or 0) / close
        prior_atr = []
        for end in range(max(15, len(history) - 100), len(history) - 1):
            snap = calculate_indicators(history[: end + 1])
            prior_atr.append((snap.atr or 0) / history[end].close)
        threshold = sorted(prior_atr)[int(0.8 * (len(prior_atr) - 1))]
        ret3 = close / history[-4].close - 1
        trend = bool(
            ind.adx is not None
            and ind.adx >= 25
            and ind.ema20
            and ind.ema50
            and abs(ind.ema20 / ind.ema50 - 1) >= 0.003
        )
        trade["regime"] = {
            "mapped": True,
            "trend": trend,
            "range": not trend,
            "high_vol": atr_pct >= threshold,
            "panic": ret3 <= -2.5 * atr_pct,
            "oversold": bool(ind.rsi is not None and ind.rsi <= 30),
            "rsi": ind.rsi,
            "adx": ind.adx,
            "atr_pct": atr_pct,
            "ret3": ret3,
        }


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(max(0.0, row["net_pnl"]) for row in rows)
    losses = -sum(min(0.0, row["net_pnl"]) for row in rows)
    ordered = sorted(rows, key=lambda row: (row["entry_time"], row["symbol"], row["timeframe"]))
    streak = current = 0
    for row in ordered:
        current = current + 1 if row["net_pnl"] < 0 else 0
        streak = max(streak, current)
    n = len(rows)
    return {
        "trades": n,
        "net_pnl": sum(r["net_pnl"] for r in rows),
        "pf": wins / losses if losses else math.inf,
        "expectancy": sum(r["net_pnl"] for r in rows) / n if n else 0,
        "avg_r": sum(r["r_multiple"] for r in rows) / n if n else 0,
        "win_rate": sum(r["net_pnl"] > 0 for r in rows) / n if n else 0,
        "fees": sum(r["fees"] for r in rows),
        "slippage": sum(r["slippage"] for r in rows),
        "funding": sum(r["funding"] for r in rows),
        "max_loss_streak": streak,
    }


def grouped(trades: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups["/".join(str(trade[field]) for field in fields)].append(trade)
    return {key: metrics(rows) for key, rows in sorted(groups.items())}


def build_side_exit_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Build descriptive side/exit diagnostics without turning them into a trading rule."""
    stop_rows = [trade for trade in trades if "STOP" in trade["reason"].upper()]
    regime_names = ("trend", "range", "high_vol", "panic", "oversold")
    stop_by_side_regime = {}
    for side in ("LONG", "SHORT"):
        side_rows = [trade for trade in stop_rows if trade["side"] == side]
        stop_by_side_regime[side] = {
            "all": metrics(side_rows),
            **{
                regime: metrics(
                    [trade for trade in side_rows if trade.get("regime", {}).get(regime)]
                )
                for regime in regime_names
            },
        }

    cells = grouped(trades, ("symbol", "timeframe", "fold", "side"))
    consistency = {}
    for side in ("LONG", "SHORT"):
        side_cells = {key: value for key, value in cells.items() if key.endswith(f"/{side}")}
        consistency[side] = {
            "datasets_profitable": sum(
                value["net_pnl"] > 0
                for key, value in grouped(trades, ("symbol", "timeframe", "side")).items()
                if key.endswith(f"/{side}")
            ),
            "datasets_total": sum(
                key.endswith(f"/{side}") for key in grouped(trades, ("symbol", "timeframe", "side"))
            ),
            "nonempty_dataset_folds": len(side_cells),
            "dataset_folds_profitable": sum(value["net_pnl"] > 0 for value in side_cells.values()),
            "largest_loss_cell": min(side_cells.items(), key=lambda item: item[1]["net_pnl"]),
        }
    return {
        "note": "Descriptive OOS attribution only; regime labels were not validation-selected.",
        "by_side": grouped(trades, ("side",)),
        "by_side_exit": grouped(trades, ("side", "reason")),
        "by_side_dataset": grouped(trades, ("side", "symbol", "timeframe")),
        "by_side_dataset_fold": cells,
        "stop_loss_by_side_regime": stop_by_side_regime,
        "consistency": consistency,
    }


def build_report(payloads: list[dict[str, Any]], cache_dir: Path) -> dict[str, Any]:
    datasets = {}
    fold_trades = {}
    service = BacktestService()
    for payload in payloads:
        key = (payload["symbol"], payload["tf"])
        candles = fetch_candles(payload["symbol"], payload["tf"], payload["max_close"], cache_dir)
        datasets[key] = candles
        request = BacktestRunRequest(
            symbol=payload["symbol"], interval=payload["tf"], limit=len(candles)
        )
        features = service._precompute_features(candles)
        reports = {}
        for fold in payload["report"]["folds"]:
            fingerprint = fold["selected_config_fingerprint"]
            if fingerprint not in reports:
                config = BacktestStrategyConfig.model_validate(fold["selected_config"])
                reports[fingerprint] = service._simulate(
                    candles, request, config, features
                ).model_dump()
            fold_trades[(payload["symbol"], payload["tf"], fold["number"])] = reports[fingerprint][
                "trades"
            ]
    trades = extract_oos(payloads, fold_trades)
    attach_regimes(trades, datasets)
    mapped = [t for t in trades if t["regime"]["mapped"]]
    hypotheses = {
        "short_after_panic_or_oversold": metrics(
            [
                t
                for t in mapped
                if t["side"] == "SHORT" and (t["regime"]["panic"] or t["regime"]["oversold"])
            ]
        ),
        "range_churn": metrics([t for t in mapped if t["regime"]["range"]]),
        "high_vol_stop_out": metrics(
            [t for t in mapped if t["regime"]["high_vol"] and "STOP" in t["reason"].upper()]
        ),
    }
    return {
        "definitions": {
            "causality": "indicators use candles with close_time <= signal_time",
            "trend": "ADX>=25 and abs(EMA20/EMA50-1)>=0.3%; otherwise range",
            "high_vol": "ATR14/close >= trailing 100-candle 80th percentile",
            "panic": "3-candle return <= -2.5*ATR14/close",
            "oversold": "RSI14<=30",
        },
        "overall": metrics(trades),
        "by_dataset": grouped(trades, ("symbol", "timeframe")),
        "by_side": grouped(trades, ("side",)),
        "by_exit_reason": grouped(trades, ("reason",)),
        "by_fold": grouped(trades, ("fold",)),
        "by_regime": {
            name: metrics([t for t in mapped if t["regime"].get(name)])
            for name in ("trend", "range", "high_vol", "panic", "oversold")
        },
        "hypotheses": hypotheses,
        "mapped_regimes": len(mapped),
        "trades": trades,
    }
