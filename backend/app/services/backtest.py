import hashlib
import json
import math
from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise, product
from statistics import mean, pstdev
from uuid import uuid4

from app.domain.models import (
    BacktestMetrics,
    BacktestOptimizerCandidate,
    BacktestOptimizerFold,
    BacktestOptimizerReport,
    BacktestOptimizerRequest,
    BacktestPoint,
    BacktestRunReport,
    BacktestRunRequest,
    BacktestSegment,
    BacktestSignalFunnel,
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


@dataclass(frozen=True)
class _SignalFeature:
    long_score: int
    short_score: int
    regime: MarketRegime
    atr: float
    close: float
    ema20: float | None
    reasons: tuple[str, ...]


_MTF_INTERVALS = ("15m", "1h", "4h")
_INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


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

    def run(
        self, candles: dict[str, list[Candle]], request: BacktestRunRequest
    ) -> BacktestRunReport:
        candles = self._validate_mtf_data(candles)
        trigger_candles = candles["15m"]
        if len(trigger_candles) < 250:
            raise ValueError("Cần ít nhất 250 nến đã đóng để backtest")
        ordered = trigger_candles
        dataset_hash = self._dataset_fingerprint(candles)
        features = self._precompute_mtf_features(candles)
        report = BacktestRunReport(
            id=str(uuid4()),
            symbol=request.symbol.upper(),
            interval=request.interval,
            candle_count=len(ordered),
            dataset_start=ordered[0].open_time,
            dataset_end=ordered[-1].close_time,
            dataset_fingerprint=dataset_hash,
            baseline=self._simulate(ordered, request, request.baseline, features),
            candidate=(
                self._simulate(ordered, request, request.candidate, features)
                if request.candidate
                else None
            ),
            candidate_applied=False,
        )
        self.latest = report
        return report

    def optimize(
        self, candles: dict[str, list[Candle]], request: BacktestOptimizerRequest
    ) -> BacktestOptimizerReport:
        candles = self._validate_mtf_data(candles)
        trigger_candles = candles["15m"]
        if len(trigger_candles) < 250:
            raise ValueError("Cần ít nhất 250 nến đã đóng để tối ưu")
        ordered = trigger_candles
        dataset_hash = self._dataset_fingerprint(candles)
        baseline = request.run.baseline
        features = self._precompute_mtf_features(candles)
        configs = []
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
            configs.append(config)

        # The first OOS begins only after the configured initial train + validation
        # region. Each later fold uses an expanding history, with the same-size
        # validation block immediately before its test. Nothing at/after test_start
        # participates in selection.
        first_test = int(
            len(ordered) * (request.run.train_fraction + request.run.validation_fraction)
        )
        test_size = max(1, math.ceil((len(ordered) - first_test) / request.folds))
        validation_size = max(1, int(len(ordered) * request.run.validation_fraction))
        folds = []
        candidate_rows: list[
            tuple[float, bool, list[str], float, BacktestSegment, BacktestStrategyReport]
        ] = []
        # A locked OOS prefix is exactly the scoring prefix of the next fold.
        # Cache by immutable config fingerprint + prefix length so that simulation
        # is reused without letting any candle at/after the requested end leak in.
        simulation_cache: dict[tuple[str, int], BacktestStrategyReport] = {}

        def simulate_prefix(config: BacktestStrategyConfig, end: int) -> BacktestStrategyReport:
            fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
            key = (fingerprint, end)
            if key not in simulation_cache:
                simulation_cache[key] = self._simulate(ordered[:end], request.run, config, features)
            return simulation_cache[key]

        for number in range(request.folds):
            test_start = first_test + number * test_size
            if test_start >= len(ordered):
                break
            test_end = min(len(ordered), test_start + test_size)
            validation_start = max(211, test_start - validation_size)
            scored_fold = []
            for config in configs:
                report = simulate_prefix(config, test_start)
                validation = self._segment_for_range(
                    report.trades,
                    ordered,
                    validation_start,
                    test_start,
                    request.run.initial_capital,
                    "VALIDATION",
                )
                eligible = validation.metrics.trades >= request.minimum_validation_trades
                score = self._validation_score(validation)
                scored_fold.append((eligible, score, config, report, validation))
            scored_fold.sort(key=lambda row: (row[0], row[1]), reverse=True)
            eligible, score, config, report, validation = scored_fold[0]
            reasons = (
                []
                if eligible
                else [
                    (
                        f"Validation chỉ có {validation.metrics.trades}/"
                        f"{request.minimum_validation_trades} giao dịch"
                    )
                ]
            )
            locked_report = simulate_prefix(config, test_end)
            test = self._segment_for_range(
                locked_report.trades,
                ordered,
                test_start,
                test_end,
                request.run.initial_capital,
                f"OOS-{number + 1}",
            )
            folds.append(
                BacktestOptimizerFold(
                    number=number + 1,
                    train_start=0,
                    train_end=validation_start,
                    validation_start=validation_start,
                    validation_end=test_start,
                    test_start=test_start,
                    test_end=test_end,
                    selected_config=config,
                    selected_config_fingerprint=hashlib.sha256(
                        config.model_dump_json().encode()
                    ).hexdigest(),
                    validation_score=score,
                    validation_trades=validation.metrics.trades,
                    test=test,
                )
            )
        # Gate every candidate on its own chronological, stitched OOS trades. The
        # config is fixed before each test range and each simulation ends at that
        # range boundary, so later candles cannot influence entries or forced exits.
        for config in configs:
            validation_report = simulate_prefix(config, first_test)
            validation = self._segment_for_range(
                validation_report.trades,
                ordered,
                max(211, first_test - validation_size),
                first_test,
                request.run.initial_capital,
                "VALIDATION",
            )
            score = self._validation_score(validation)
            reasons = []
            if validation.metrics.trades < request.minimum_validation_trades:
                reasons.append(
                    f"Validation chỉ có {validation.metrics.trades}/"
                    f"{request.minimum_validation_trades} giao dịch"
                )

            stitched_trades: list[BacktestTrade] = []
            profitable_windows = 0
            evaluated_windows = 0
            for fold in folds:
                report = simulate_prefix(config, fold.test_end)
                fold_trades = self._trades_for_range(
                    report.trades, ordered, fold.test_start, fold.test_end
                )
                stitched_trades.extend(fold_trades)
                fold_metrics, _, _ = self._trade_metrics(fold_trades, request.run.initial_capital)
                profitable_windows += fold_metrics.pnl > 0
                evaluated_windows += 1
            metrics, average_r, drawdown = self._trade_metrics(
                stitched_trades, request.run.initial_capital
            )
            metrics.out_of_sample_trades = metrics.trades
            stitched = BacktestSegment(
                name="STITCHED_OOS",
                start_time=(ordered[folds[0].test_start].open_time if folds else None),
                end_time=(ordered[folds[-1].test_end - 1].close_time if folds else None),
                metrics=metrics,
                average_r=average_r,
                max_drawdown_percent=drawdown,
            )
            if metrics.trades < request.minimum_oos_trades:
                reasons.append(
                    f"Stitched OOS chỉ có {metrics.trades}/{request.minimum_oos_trades} giao dịch"
                )
            if not metrics.profit_factor > 1.2:
                reasons.append("Stitched OOS profit factor phải > 1.2")
            if not metrics.expectancy > 0:
                reasons.append("Stitched OOS expectancy phải > 0")
            if drawdown > request.max_oos_drawdown_percent:
                reasons.append(
                    f"Stitched OOS drawdown {drawdown:.2f}% vượt ngưỡng "
                    f"{request.max_oos_drawdown_percent:.2f}%"
                )
            candidate_rows.append(
                (
                    score,
                    not reasons,
                    reasons,
                    profitable_windows / evaluated_windows if evaluated_windows else 0.0,
                    stitched,
                    validation_report,
                )
            )

        candidate_rows.sort(key=lambda row: (row[1], row[0]), reverse=True)
        candidates = [
            BacktestOptimizerCandidate(
                rank=index,
                score=score,
                eligible=eligible,
                rejection_reasons=reasons,
                profitable_walk_forward_ratio=profitable_ratio,
                stitched_oos=stitched,
                report=strategy,
            )
            for index, (
                score,
                eligible,
                reasons,
                profitable_ratio,
                stitched,
                strategy,
            ) in enumerate(candidate_rows, 1)
        ]
        result = BacktestOptimizerReport(
            id=str(uuid4()),
            symbol=request.run.symbol.upper(),
            interval=request.run.interval,
            dataset_fingerprint=dataset_hash,
            evaluated_candidates=len(candidates),
            eligible_candidates=sum(item.eligible for item in candidates),
            minimum_oos_trades=request.minimum_oos_trades,
            max_oos_drawdown_percent=request.max_oos_drawdown_percent,
            candidates=candidates,
            folds=folds,
            candidate_applied=False,
        )
        self.latest_optimizer = result
        return result

    @staticmethod
    def _trades_for_range(trades, candles, start, end):
        return [
            trade
            for trade in trades
            if candles[start].open_time <= trade.entry_time <= candles[end - 1].close_time
        ]

    def _segment_for_range(self, trades, candles, start, end, capital, name):
        selected = self._trades_for_range(trades, candles, start, end)
        metrics, average_r, drawdown = self._trade_metrics(selected, capital)
        return BacktestSegment(
            name=name,
            start_time=candles[start].open_time,
            end_time=candles[end - 1].close_time,
            metrics=metrics,
            average_r=average_r,
            max_drawdown_percent=drawdown,
        )

    @staticmethod
    def _validation_score(segment: BacktestSegment) -> float:
        return (
            segment.average_r * 40
            + min(segment.metrics.profit_factor, 5) * 10
            + segment.metrics.pnl / 100
            - segment.max_drawdown_percent * 2
        )

    def _precompute_features(self, candles: list[Candle]) -> dict[int, _SignalFeature]:
        features: dict[int, _SignalFeature] = {}
        for index in range(210, len(candles) - 1):
            history = candles[: index + 1]
            indicators = calculate_indicators(history)
            regime = detect_regime(history, indicators)
            long_score, short_score, reasons = score_market(history, indicators, regime)
            features[index] = _SignalFeature(
                long_score=long_score,
                short_score=short_score,
                regime=regime,
                atr=indicators.atr or candles[index].close * 0.01,
                close=candles[index].close,
                ema20=indicators.ema20,
                reasons=tuple(reasons),
            )
        return features

    @staticmethod
    def _dataset_fingerprint(candles: dict[str, list[Candle]]) -> str:
        payload = {
            frame: [
                [c.open_time, c.close_time, c.open, c.high, c.low, c.close, c.volume]
                for c in candles[frame]
            ]
            for frame in _MTF_INTERVALS
        }
        return hashlib.sha256(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _validate_mtf_data(candles: dict[str, list[Candle]]) -> dict[str, list[Candle]]:
        if not isinstance(candles, dict) or any(frame not in candles for frame in _MTF_INTERVALS):
            raise ValueError("Backtest MTF cần đủ nến đóng 15m, 1h và 4h")
        ordered: dict[str, list[Candle]] = {}
        for frame in _MTF_INTERVALS:
            rows = sorted(candles[frame], key=lambda candle: candle.open_time)
            if len(rows) < 212:
                raise ValueError(f"Không đủ nến đóng {frame} để tính MTF causal")
            if any(row.close_time < row.open_time for row in rows):
                raise ValueError(f"Nến {frame} có thời gian đóng không hợp lệ")
            if any(right.open_time <= left.close_time for left, right in pairwise(rows)):
                raise ValueError(f"Nến {frame} bị trùng hoặc sai thứ tự")
            ordered[frame] = rows
        return ordered

    def _precompute_mtf_features(
        self, candles: dict[str, list[Candle]]
    ) -> dict[int, tuple[_SignalFeature, _SignalFeature, _SignalFeature] | None]:
        frame_features = {
            frame: self._precompute_features(candles[frame]) for frame in _MTF_INTERVALS
        }
        closes = {frame: [row.close_time for row in candles[frame]] for frame in ("1h", "4h")}
        aligned: dict[int, tuple[_SignalFeature, _SignalFeature, _SignalFeature] | None] = {}
        for index, trigger in enumerate(candles["15m"]):
            m15 = frame_features["15m"].get(index)
            h1_index = bisect_right(closes["1h"], trigger.close_time) - 1
            h4_index = bisect_right(closes["4h"], trigger.close_time) - 1
            h1 = frame_features["1h"].get(h1_index)
            h4 = frame_features["4h"].get(h4_index)
            stale = (
                h1_index < 0
                or h4_index < 0
                or trigger.close_time - candles["1h"][h1_index].close_time >= _INTERVAL_MS["1h"]
                or trigger.close_time - candles["4h"][h4_index].close_time >= _INTERVAL_MS["4h"]
            )
            aligned[index] = None if stale or not (m15 and h1 and h4) else (m15, h1, h4)
        return aligned

    @staticmethod
    def _feature_action(feature: _SignalFeature, minimum_score: int) -> SignalAction:
        if feature.long_score >= minimum_score and feature.long_score > feature.short_score:
            return SignalAction.LONG
        if feature.short_score >= minimum_score and feature.short_score > feature.long_score:
            return SignalAction.SHORT
        return SignalAction.NO_TRADE

    def _mtf_action(
        self,
        features: tuple[_SignalFeature, _SignalFeature, _SignalFeature] | None,
        minimum_score: int,
    ) -> SignalAction:
        if features is None:
            return SignalAction.NO_TRADE
        m15, h1, h4 = features
        if h4.regime not in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN}:
            return SignalAction.NO_TRADE
        if h1.regime != h4.regime or h1.regime in {MarketRegime.HIGH_VOL, MarketRegime.PANIC}:
            return SignalAction.NO_TRADE
        expected = (
            SignalAction.LONG if h4.regime == MarketRegime.TRENDING_UP else SignalAction.SHORT
        )
        if self._feature_action(m15, minimum_score) != expected:
            return SignalAction.NO_TRADE
        if self._feature_action(h1, minimum_score) != expected:
            return SignalAction.NO_TRADE
        breakout = any("breakout" in reason.lower() for reason in h1.reasons)
        pullback = bool(h1.ema20 and abs(h1.close - h1.ema20) <= h1.atr)
        if not (breakout or pullback):
            return SignalAction.NO_TRADE
        if m15.ema20 and m15.atr and abs(m15.close - m15.ema20) / m15.atr > 2:
            return SignalAction.NO_TRADE
        return expected

    def _simulate(
        self,
        candles: list[Candle],
        request: BacktestRunRequest,
        config: BacktestStrategyConfig,
        features: dict[int, tuple[_SignalFeature, _SignalFeature, _SignalFeature] | None]
        | None = None,
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
                mtf = features.get(index) if features else None
                action = self._mtf_action(mtf, config.min_score)
                if action != SignalAction.NO_TRADE and mtf is not None:
                    atr = mtf[0].atr
                    distance = max(atr * config.stop_atr_multiplier, candle.close * 0.004)
                    pending = (Side(action.value), candle.close_time, distance)
        if position:
            final = candles[-1]
            trade = self._close(position, final.close, final.close_time, "Hết dữ liệu", request)
            trades.append(trade)
            curve.append(BacktestPoint(time=trade.exit_time, equity=equity + trade.net_pnl))
        report = self._report(candles, request, config, trades, curve)
        report.signal_funnel = self._signal_funnel(features or {}, config.min_score, len(candles))
        return report

    def _signal_funnel(
        self,
        features: dict[int, tuple[_SignalFeature, _SignalFeature, _SignalFeature] | None],
        minimum_score: int,
        candle_count: int,
    ) -> BacktestSignalFunnel:
        funnel = BacktestSignalFunnel(evaluated=max(0, candle_count - 211))
        for index in range(210, candle_count - 1):
            mtf = features.get(index)
            if mtf is None:
                continue
            funnel.mtf_aligned += 1
            m15, h1, h4 = mtf
            if h4.regime not in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN}:
                continue
            funnel.h4_trending += 1
            if h1.regime != h4.regime or h1.regime in {MarketRegime.HIGH_VOL, MarketRegime.PANIC}:
                continue
            funnel.h1_regime_aligned += 1
            expected = (
                SignalAction.LONG if h4.regime == MarketRegime.TRENDING_UP else SignalAction.SHORT
            )
            if self._feature_action(m15, minimum_score) != expected:
                continue
            funnel.trigger_score_passed += 1
            if self._feature_action(h1, minimum_score) != expected:
                continue
            funnel.h1_score_passed += 1
            breakout = any("breakout" in reason.lower() for reason in h1.reasons)
            pullback = bool(h1.ema20 and abs(h1.close - h1.ema20) <= h1.atr)
            if not (breakout or pullback):
                continue
            funnel.setup_passed += 1
            if m15.ema20 and m15.atr and abs(m15.close - m15.ema20) / m15.atr > 2:
                continue
            funnel.extension_passed += 1
            funnel.actionable += 1
        return funnel

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
        # Rolling-origin evaluation: after the initial train block, each chronological
        # test fold is evaluated exactly once.  The information set expands after a
        # fold completes; no future fold is used to score an earlier one.
        walk_forward = []
        first_test = boundaries[1]
        remaining = len(candles) - first_test
        fold_size = max(1, math.ceil(remaining / request.walk_forward_windows))
        for number in range(request.walk_forward_windows):
            start = first_test + number * fold_size
            if start >= len(candles):
                break
            end = min(len(candles), start + fold_size)
            selected = [
                trade
                for trade in trades
                if candles[start].open_time <= trade.entry_time <= candles[end - 1].close_time
            ]
            metric, avg_r, segment_dd = self._trade_metrics(selected, request.initial_capital)
            walk_forward.append(
                BacktestSegment(
                    name=f"WF-{number + 1}-TRAIN-0:{start}-TEST-{start}:{end}",
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
