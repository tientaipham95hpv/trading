import hashlib
import json
import math
from dataclasses import dataclass
from itertools import product
from statistics import mean, pstdev
from uuid import uuid4

from app.domain.models import (
    BacktestMetrics,
    BacktestOptimizerCandidate,
    BacktestOptimizerReport,
    BacktestOptimizerRequest,
    BacktestPoint,
    BacktestRunReport,
    BacktestRunRequest,
    BacktestSegment,
    BacktestStrategyConfig,
    BacktestStrategyReport,
    BacktestTrade,
    Candle,
    MarketRegime,
    Side,
    SignalAction,
    TradeRecord,
)
from app.services.indicators import calculate_indicators
from app.services.scanner import detect_regime, score_market


@dataclass
class _Position:
    side: Side
    signal_time: int
    entry_time: int
    entry: float
    stop: float
    initial_stop_distance: float
    targets: list[float]
    quantity: float
    remaining: float
    initial_risk: float
    entry_fee: float
    entry_slippage: float
    realized: float = 0.0
    exit_fees: float = 0.0
    exit_slippage: float = 0.0
    next_target: int = 0


class BacktestService:
    def __init__(self) -> None:
        self.latest: BacktestRunReport | None = None
        self.latest_optimizer: BacktestOptimizerReport | None = None

    def run(self, candles: list[Candle], request: BacktestRunRequest) -> BacktestRunReport:
        if len(candles) < 250:
            raise ValueError("Cần ít nhất 250 nến đã đóng để backtest")
        ordered = sorted(candles, key=lambda row: row.open_time)
        dataset_hash = hashlib.sha256(
            json.dumps(
                [[c.open_time, c.open, c.high, c.low, c.close, c.volume] for c in ordered],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        report = BacktestRunReport(
            id=str(uuid4()),
            symbol=request.symbol.upper(),
            interval=request.interval,
            candle_count=len(ordered),
            dataset_start=ordered[0].open_time,
            dataset_end=ordered[-1].close_time,
            dataset_fingerprint=dataset_hash,
            baseline=self._simulate(ordered, request, request.baseline),
            candidate=(
                self._simulate(ordered, request, request.candidate) if request.candidate else None
            ),
            candidate_applied=False,
        )
        self.latest = report
        return report

    def optimize(
        self, candles: list[Candle], request: BacktestOptimizerRequest
    ) -> BacktestOptimizerReport:
        if len(candles) < 250:
            raise ValueError("Cần ít nhất 250 nến đã đóng để tối ưu")
        ordered = sorted(candles, key=lambda row: row.open_time)
        dataset_hash = hashlib.sha256(
            json.dumps(
                [[c.open_time, c.open, c.high, c.low, c.close, c.volume] for c in ordered],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        scored: list[tuple[float, bool, list[str], float, BacktestStrategyReport]] = []
        baseline = request.run.baseline
        for min_score, stop_atr, risk in product(
            sorted(set(request.min_scores)),
            sorted(set(request.stop_atr_multipliers)),
            sorted(set(request.risk_fractions)),
        ):
            config = baseline.model_copy(
                update={
                    "name": f"Candidate S{min_score}-ATR{stop_atr:g}-R{risk:.3%}",
                    "min_score": min_score,
                    "stop_atr_multiplier": stop_atr,
                    "risk_fraction": risk,
                }
            )
            report = self._simulate(ordered, request.run, config)
            validation = next(item for item in report.segments if item.name == "VALIDATION")
            oos = next(item for item in report.segments if item.name == "OUT_OF_SAMPLE")
            profitable_windows = sum(item.metrics.pnl > 0 for item in report.walk_forward)
            window_ratio = profitable_windows / len(report.walk_forward) if report.walk_forward else 0
            reasons = []
            if oos.metrics.trades < request.minimum_oos_trades:
                reasons.append(
                    f"OOS chỉ có {oos.metrics.trades}/{request.minimum_oos_trades} giao dịch"
                )
            if validation.metrics.pnl <= 0:
                reasons.append("Validation PNL không dương")
            if oos.metrics.pnl <= 0:
                reasons.append("OOS PNL không dương")
            if window_ratio < 0.5:
                reasons.append("Dưới 50% cửa sổ walk-forward có lãi")
            eligible = not reasons
            score = (
                oos.average_r * 35
                + validation.average_r * 25
                + min(oos.metrics.profit_factor, 5) * 8
                + min(validation.metrics.profit_factor, 5) * 5
                + window_ratio * 20
                - oos.max_drawdown_percent * 2
                - validation.max_drawdown_percent
            )
            scored.append((score, eligible, reasons, window_ratio, report))
        scored.sort(key=lambda item: (item[1], item[0]), reverse=True)
        candidates = [
            BacktestOptimizerCandidate(
                rank=index,
                score=score,
                eligible=eligible,
                rejection_reasons=reasons,
                profitable_walk_forward_ratio=window_ratio,
                report=strategy,
            )
            for index, (score, eligible, reasons, window_ratio, strategy) in enumerate(scored, 1)
        ]
        result = BacktestOptimizerReport(
            id=str(uuid4()),
            symbol=request.run.symbol.upper(),
            interval=request.run.interval,
            dataset_fingerprint=dataset_hash,
            evaluated_candidates=len(candidates),
            eligible_candidates=sum(item.eligible for item in candidates),
            minimum_oos_trades=request.minimum_oos_trades,
            candidates=candidates,
            candidate_applied=False,
        )
        self.latest_optimizer = result
        return result

    def _simulate(
        self, candles: list[Candle], request: BacktestRunRequest, config: BacktestStrategyConfig
    ) -> BacktestStrategyReport:
        if len(config.take_profit_r_multiples) != len(config.take_profit_fractions):
            raise ValueError("Số mốc TP và tỷ lệ chốt lời phải bằng nhau")
        if not math.isclose(sum(config.take_profit_fractions), 1.0, abs_tol=1e-6):
            raise ValueError("Tổng tỷ lệ partial TP phải bằng 1")
        trades: list[BacktestTrade] = []
        curve = [BacktestPoint(time=candles[0].open_time, equity=request.initial_capital)]
        equity = request.initial_capital
        position: _Position | None = None
        pending: tuple[Side, int, float] | None = None
        for index in range(210, len(candles)):
            candle = candles[index]
            if pending and position is None:
                side, signal_time, stop_distance = pending
                entry = self._slipped(candle.open, side, request.slippage_bps, entry=True)
                stop = entry - stop_distance if side == Side.LONG else entry + stop_distance
                risk_amount = equity * config.risk_fraction
                quantity = risk_amount / stop_distance
                targets = [
                    entry + stop_distance * value
                    if side == Side.LONG
                    else entry - stop_distance * value
                    for value in config.take_profit_r_multiples
                ]
                position = _Position(
                    side=side,
                    signal_time=signal_time,
                    entry_time=candle.open_time,
                    entry=entry,
                    stop=stop,
                    initial_stop_distance=stop_distance,
                    targets=targets,
                    quantity=quantity,
                    remaining=quantity,
                    initial_risk=risk_amount,
                    entry_fee=entry * quantity * request.taker_fee_rate,
                    entry_slippage=abs(entry - candle.open) * quantity,
                )
                pending = None
            if position:
                closed = self._process_candle(position, candle, request, config)
                if closed:
                    trades.append(closed)
                    equity += closed.net_pnl
                    curve.append(BacktestPoint(time=closed.exit_time, equity=equity))
                    position = None
            if position is None and pending is None and index < len(candles) - 1:
                history = candles[: index + 1]
                indicators = calculate_indicators(history)
                regime = detect_regime(history, indicators)
                long_score, short_score, _ = score_market(history, indicators, regime)
                action = SignalAction.NO_TRADE
                if long_score >= config.min_score and long_score > short_score:
                    action = SignalAction.LONG
                elif short_score >= config.min_score and short_score > long_score:
                    action = SignalAction.SHORT
                if action != SignalAction.NO_TRADE and regime != MarketRegime.PANIC:
                    atr = indicators.atr or candle.close * 0.01
                    distance = max(atr * config.stop_atr_multiplier, candle.close * 0.004)
                    pending = (Side(action.value), candle.close_time, distance)
        if position:
            final = candles[-1]
            trade = self._close(position, final.close, final.close_time, "Hết dữ liệu", request)
            trades.append(trade)
            curve.append(BacktestPoint(time=trade.exit_time, equity=equity + trade.net_pnl))
        return self._report(candles, request, config, trades, curve)

    def _process_candle(
        self,
        position: _Position,
        candle: Candle,
        request: BacktestRunRequest,
        config: BacktestStrategyConfig,
    ) -> BacktestTrade | None:
        # Conservative intrabar policy: SL always wins an ambiguous same-candle race.
        stop_hit = (
            candle.low <= position.stop
            if position.side == Side.LONG
            else candle.high >= position.stop
        )
        if stop_hit:
            return self._close(position, position.stop, candle.close_time, "Stop Loss", request)
        while position.next_target < len(position.targets):
            target = position.targets[position.next_target]
            hit = candle.high >= target if position.side == Side.LONG else candle.low <= target
            if not hit:
                break
            fraction = config.take_profit_fractions[position.next_target]
            exit_qty = min(position.remaining, position.quantity * fraction)
            fill = self._slipped(target, position.side, request.slippage_bps, entry=False)
            position.realized += self._gross(position.side, position.entry, fill, exit_qty)
            position.exit_fees += fill * exit_qty * request.taker_fee_rate
            position.exit_slippage += abs(fill - target) * exit_qty
            position.remaining -= exit_qty
            position.next_target += 1
            if position.next_target == 1:  # break-even, never wider
                position.stop = position.entry
            elif position.next_target >= 2:  # ATR-distance runner trailing, never wider
                if position.side == Side.LONG:
                    position.stop = max(
                        position.stop, candle.close - position.initial_stop_distance
                    )
                else:
                    position.stop = min(
                        position.stop, candle.close + position.initial_stop_distance
                    )
            if position.remaining <= position.quantity * 1e-9:
                return self._close(
                    position, fill, candle.close_time, "Hoàn tất Take Profit", request
                )
        return None

    def _close(
        self,
        position: _Position,
        raw_price: float,
        exit_time: int,
        reason: str,
        request: BacktestRunRequest,
    ) -> BacktestTrade:
        remaining = max(0.0, position.remaining)
        fill = (
            self._slipped(raw_price, position.side, request.slippage_bps, entry=False)
            if remaining
            else raw_price
        )
        gross = position.realized + self._gross(position.side, position.entry, fill, remaining)
        exit_fees = position.exit_fees + fill * remaining * request.taker_fee_rate
        held_ms = max(0, exit_time - position.entry_time)
        funding_periods = held_ms / 28_800_000
        funding = position.entry * position.quantity * request.funding_rate_per_8h * funding_periods
        slippage = (
            position.entry_slippage + position.exit_slippage + abs(fill - raw_price) * remaining
        )
        fees = position.entry_fee + exit_fees
        net = gross - fees - funding
        return BacktestTrade(
            side=position.side,
            signal_time=position.signal_time,
            entry_time=position.entry_time,
            exit_time=exit_time,
            entry_price=position.entry,
            exit_price=fill,
            quantity=position.quantity,
            gross_pnl=gross,
            fees=fees,
            funding=funding,
            slippage=slippage,
            net_pnl=net,
            r_multiple=net / position.initial_risk if position.initial_risk else 0,
            reason=reason,
        )

    def _report(self, candles, request, config, trades, curve) -> BacktestStrategyReport:
        metrics, average_r, dd_pct = self._trade_metrics(trades, request.initial_capital)
        boundaries = [
            0,
            int(len(candles) * request.train_fraction),
            int(len(candles) * (request.train_fraction + request.validation_fraction)),
            len(candles),
        ]
        segments = []
        for name, start, end in zip(
            ["TRAIN", "VALIDATION", "OUT_OF_SAMPLE"],
            boundaries[:-1],
            boundaries[1:],
            strict=True,
        ):
            start_time, end_time = candles[start].open_time, candles[end - 1].close_time
            selected = [t for t in trades if start_time <= t.entry_time <= end_time]
            metric, avg_r, segment_dd = self._trade_metrics(selected, request.initial_capital)
            if name == "OUT_OF_SAMPLE":
                metrics.out_of_sample_trades = len(selected)
            segments.append(
                BacktestSegment(
                    name=name,
                    start_time=start_time,
                    end_time=end_time,
                    metrics=metric,
                    average_r=avg_r,
                    max_drawdown_percent=segment_dd,
                )
            )
        walk_forward = []
        oos_start = boundaries[2]
        size = max(1, math.ceil((len(candles) - oos_start) / request.walk_forward_windows))
        for number, start in enumerate(range(oos_start, len(candles), size), 1):
            end = min(len(candles), start + size)
            selected = [
                t
                for t in trades
                if candles[start].open_time <= t.entry_time <= candles[end - 1].close_time
            ]
            metric, avg_r, segment_dd = self._trade_metrics(selected, request.initial_capital)
            walk_forward.append(
                BacktestSegment(
                    name=f"WF-{number}",
                    start_time=candles[start].open_time,
                    end_time=candles[end - 1].close_time,
                    metrics=metric,
                    average_r=avg_r,
                    max_drawdown_percent=segment_dd,
                )
            )
        metrics.walk_forward_windows = len(walk_forward)
        fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
        return BacktestStrategyReport(
            config=config,
            config_fingerprint=fingerprint,
            metrics=metrics,
            average_r=average_r,
            max_drawdown_percent=dd_pct,
            segments=segments,
            walk_forward=walk_forward,
            trades=trades,
            equity_curve=curve,
        )

    def _trade_metrics(
        self, trades: list[BacktestTrade], capital: float
    ) -> tuple[BacktestMetrics, float, float]:
        records = [
            TradeRecord(
                id=str(index),
                symbol="BACKTEST",
                side=trade.side,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                quantity=trade.quantity,
                gross_pnl=trade.gross_pnl,
                fee=trade.fees,
                slippage=trade.slippage,
                funding=trade.funding,
                net_pnl=trade.net_pnl,
                reason=trade.reason,
            )
            for index, trade in enumerate(trades)
        ]
        metrics = self.metrics(records)
        average_r = mean([trade.r_multiple for trade in trades]) if trades else 0.0
        dd_pct = metrics.drawdown / capital * 100 if capital else 0.0
        return metrics, average_r, dd_pct

    @staticmethod
    def _slipped(price: float, side: Side, bps: float, *, entry: bool) -> float:
        buy = (side == Side.LONG) == entry
        return price * (1 + bps / 10_000 if buy else 1 - bps / 10_000)

    @staticmethod
    def _gross(side: Side, entry: float, exit_price: float, quantity: float) -> float:
        return (exit_price - entry) * quantity * (1 if side == Side.LONG else -1)

    def metrics(
        self,
        trades: list[TradeRecord],
        *,
        fees: float = 0.0,
        slippage: float = 0.0,
        funding: float = 0.0,
        walk_forward_windows: int = 0,
        out_of_sample_trades: int = 0,
    ) -> BacktestMetrics:
        returns = [trade.net_pnl for trade in trades]
        wins = [value for value in returns if value > 0]
        losses = [abs(value) for value in returns if value <= 0]
        pnl = sum(returns)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for value in returns:
            equity += value
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        downside = [value for value in returns if value < 0]
        volatility = pstdev(returns) if len(returns) > 1 else 0.0
        downside_vol = pstdev(downside) if len(downside) > 1 else 0.0
        avg_return = mean(returns) if returns else 0.0
        return BacktestMetrics(
            pnl=pnl,
            profit_factor=(
                sum(wins) / sum(losses)
                if losses and sum(losses) > 0
                else (math.inf if wins else 0.0)
            ),
            drawdown=max_dd,
            sharpe=(avg_return / volatility) if volatility > 0 else 0.0,
            sortino=(avg_return / downside_vol) if downside_vol > 0 else 0.0,
            expectancy=avg_return,
            winrate=(len(wins) / len(trades)) if trades else 0.0,
            trades=len(trades),
            fees=fees or sum(trade.fee for trade in trades),
            slippage=slippage or sum(trade.slippage for trade in trades),
            funding=funding or sum(trade.funding for trade in trades),
            walk_forward_windows=walk_forward_windows,
            out_of_sample_trades=out_of_sample_trades,
            no_lookahead_bias=True,
        )
