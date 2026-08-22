"""Isolated, causal, read-only Strategy V3 trend-pullback research engine."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any

from app.domain.models import Candle


@dataclass(frozen=True)
class Config:
    id: str
    slope_min: float
    pullback_atr: float
    stop_atr: float
    target_r: float
    max_hold: int


CONFIGS = (
    Config("A", 0.0010, 0.50, 1.5, 2.0, 24),
    Config("B", 0.0010, 0.75, 1.5, 2.0, 24),
    Config("C", 0.0015, 0.50, 2.0, 2.0, 30),
    Config("D", 0.0015, 0.75, 2.0, 2.5, 30),
)


def fingerprint(config: Config) -> str:
    return hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()


def dataset_fingerprint(candles: list[Candle]) -> str:
    rows = [[c.open_time, c.open, c.high, c.low, c.close, c.volume, c.close_time] for c in candles]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    value = sum(values[:period]) / period
    out[period - 1] = value
    alpha = 2 / (period + 1)
    for index in range(period, len(values)):
        value += alpha * (values[index] - value)
        out[index] = value
    return out


def _atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(candles)
    tr = [0.0]
    for previous, current in itertools.pairwise(candles):
        tr.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    for index in range(period, len(candles)):
        out[index] = sum(tr[index - period + 1 : index + 1]) / period
    return out


def features(candles: list[Candle]) -> dict[str, list[float | None]]:
    closes = [row.close for row in candles]
    return {
        "ema20": _ema(closes, 20),
        "ema50": _ema(closes, 50),
        "ema200": _ema(closes, 200),
        "atr": _atr(candles),
    }


def simulate(candles: list[Candle], config: Config, start: int, end: int) -> list[dict[str, Any]]:
    """Signal in [start,end); entries/exits clipped to end, using only closed signal bars."""
    feat = features(candles)
    trades: list[dict[str, Any]] = []
    index = max(start, 205)
    while index < end - 1:
        atr = feat["atr"][index]
        e20 = feat["ema20"][index]
        e50 = feat["ema50"][index]
        e200 = feat["ema200"][index]
        old20 = feat["ema20"][index - 5]
        if None in (atr, e20, e50, e200, old20) or not atr:
            index += 1
            continue
        slope = (float(e20) - float(old20)) / (5 * float(atr))
        candle, prior = candles[index], candles[index - 1]
        long_trend = e20 > e50 > e200 and slope >= config.slope_min
        short_trend = e20 < e50 < e200 and slope <= -config.slope_min
        band = config.pullback_atr * float(atr)
        recent = range(index - 2, index + 1)
        long_pullback = any(
            candles[j].low <= float(feat["ema20"][j] or -math.inf) + band for j in recent
        )
        short_pullback = any(
            candles[j].high >= float(feat["ema20"][j] or math.inf) - band for j in recent
        )
        side = None
        if (
            long_trend
            and long_pullback
            and candle.close > prior.high
            and candle.close > candle.open
            and candle.close > e50
        ):
            side = "LONG"
        elif (
            short_trend
            and short_pullback
            and candle.close < prior.low
            and candle.close < candle.open
            and candle.close < e50
        ):
            side = "SHORT"
        if side is None:
            index += 1
            continue
        entry_index = index + 1
        raw_entry = candles[entry_index].open
        entry = raw_entry * (1.0002 if side == "LONG" else 0.9998)
        distance = config.stop_atr * float(atr)
        stop = entry - distance if side == "LONG" else entry + distance
        target = (
            entry + config.target_r * distance
            if side == "LONG"
            else entry - config.target_r * distance
        )
        exit_index = min(end - 1, entry_index + config.max_hold - 1)
        reason = "TIME"
        raw_exit = candles[exit_index].close
        for cursor in range(entry_index, exit_index + 1):
            row = candles[cursor]
            stop_hit = row.low <= stop if side == "LONG" else row.high >= stop
            target_hit = row.high >= target if side == "LONG" else row.low <= target
            if stop_hit:
                exit_index, raw_exit, reason = cursor, stop, "STOP"
                break
            if target_hit:
                exit_index, raw_exit, reason = cursor, target, "TARGET"
                break
        exit_price = raw_exit * (0.9998 if side == "LONG" else 1.0002)
        risk_budget = 100.0
        quantity = risk_budget / distance
        gross = (exit_price - entry) * quantity * (1 if side == "LONG" else -1)
        fees = quantity * (entry + exit_price) * 0.0005
        hours = max(
            1 / 60, (candles[exit_index].close_time - candles[entry_index].open_time) / 3_600_000
        )
        funding = quantity * entry * 0.0001 * hours / 8
        net = gross - fees - funding
        trades.append(
            {
                "side": side,
                "signal_time": candle.close_time,
                "entry_time": candles[entry_index].open_time,
                "exit_time": candles[exit_index].close_time,
                "net_pnl": net,
                "r_multiple": net / risk_budget,
                "fees": fees,
                "slippage": quantity * (abs(entry - raw_entry) + abs(exit_price - raw_exit)),
                "funding": funding,
                "reason": reason,
            }
        )
        index = exit_index + 1
    return trades


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnl = [float(row["net_pnl"]) for row in trades]
    wins, losses = sum(max(0.0, x) for x in pnl), -sum(min(0.0, x) for x in pnl)
    equity = peak = drawdown = 0.0
    streak = current = 0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        current = current + 1 if value < 0 else 0
        streak = max(streak, current)
    return {
        "trades": len(trades),
        "pnl": sum(pnl),
        "pf": wins / losses if losses else (math.inf if wins else 0.0),
        "expectancy": mean(pnl) if pnl else 0.0,
        "avg_r": mean([float(x["r_multiple"]) for x in trades]) if trades else 0.0,
        "win_rate": sum(x > 0 for x in pnl) / len(pnl) if pnl else 0.0,
        "max_drawdown": drawdown,
        "max_loss_streak": streak,
        "fees": sum(float(x["fees"]) for x in trades),
        "slippage": sum(float(x["slippage"]) for x in trades),
        "funding": sum(float(x["funding"]) for x in trades),
    }


def select(
    candles: list[Candle], start: int, end: int
) -> tuple[Config, list[dict[str, Any]], bool]:
    rows = []
    for config in CONFIGS:
        trades = simulate(candles, config, start, end)
        stat = metrics(trades)
        score = float(stat["avg_r"]) - 0.25 * float(stat["max_drawdown"]) / 100
        rows.append((config, trades, stat, score))
    eligible = [row for row in rows if row[2]["trades"] >= 5]
    pool = eligible or rows
    pool.sort(
        key=lambda row: (
            (-row[3], row[0].id) if eligible else (-row[2]["trades"], -row[3], row[0].id)
        )
    )
    return (
        pool[0][0],
        [{"config": asdict(r[0]), "metrics": r[2], "score": r[3]} for r in rows],
        bool(eligible),
    )
