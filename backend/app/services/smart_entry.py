import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.domain.models import Candle, ScannerResult, SignalAction


class SmartEntryAnalytics:
    """Deterministic, observational entry-quality classifier.

    It consumes only the scanner snapshot already produced from closed candles. The
    result is evidence, never an execution input.
    """

    # V2 keys evidence by the closed candle being audited, rather than by a
    # volatile scanner snapshot. This is deliberately audit-only.
    VERSION = "SMART_ENTRY_SHADOW_V2"

    @classmethod
    def evaluate(cls, result: ScannerResult, *, mode: str) -> dict[str, Any]:
        side_score = result.long_score if result.action == SignalAction.LONG else result.short_score
        reasons: list[str] = []
        available = result.action != SignalAction.NO_TRADE and result.stop_loss is not None
        if result.action == SignalAction.NO_TRADE:
            reasons.append("Scanner chưa xác nhận hướng vào lệnh")
        if result.stop_loss is None:
            reasons.append("Không có Stop Loss để xác minh rủi ro ban đầu")
        if result.risk_reward is None:
            reasons.append("Chưa xác minh được tỷ lệ lợi nhuận/rủi ro")
        if result.indicators.atr is None or result.indicators.atr <= 0:
            reasons.append("Thiếu ATR từ nến đã đóng")

        quality = side_score
        if result.risk_reward is not None:
            quality += 5 if result.risk_reward >= 1.5 else -10
        if result.indicators.adx is not None:
            quality += 5 if result.indicators.adx >= 20 else -5
        quality = max(0, min(100, quality))
        decision = "WOULD_ENTER" if available and not reasons and quality >= 70 else "WOULD_SKIP"
        if decision == "WOULD_SKIP" and not reasons:
            reasons.append("Điểm chất lượng entry shadow chưa đạt 70")

        decision_at = result.scanned_at.isoformat()
        closed_candle_time = cls._closed_candle_time(result.scanned_at, result.timeframe.value)
        audit_identity = {
            "version": cls.VERSION,
            "symbol": result.symbol,
            "timeframe": result.timeframe.value,
            "side": result.action.value,
            "closed_candle_time": closed_candle_time,
        }
        audit_fingerprint = hashlib.sha256(
            json.dumps(audit_identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        # Snapshot details are immutable provenance for the first observation.
        provenance_identity = {
            **audit_identity,
            "decision_at": decision_at,
            "price": result.price,
            "stop_loss": result.stop_loss,
            "scores": [result.long_score, result.short_score],
            "risk_reward": result.risk_reward,
        }
        provenance_fingerprint = hashlib.sha256(
            json.dumps(provenance_identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        decision_label, decision_description = cls.decision_presentation(decision)
        return {
            "event_key": f"{cls.VERSION}:{audit_fingerprint}",
            "fingerprint": audit_fingerprint,
            "audit_key": f"{result.symbol}:{result.timeframe.value}:{result.action.value}:{closed_candle_time}",
            "closed_candle_time": closed_candle_time,
            "provenance": {
                "schema": "SMART_ENTRY_PROVENANCE_V1",
                "fingerprint": provenance_fingerprint,
                "scanner_scanned_at": decision_at,
                "source": "closed_candle_scanner_snapshot",
            },
            "version": cls.VERSION,
            "mode": mode,
            "symbol": result.symbol,
            "timeframe": result.timeframe.value,
            "side": result.action.value,
            # Keep the enum stable for storage/clients; presentation is Vietnamese.
            "decision": decision,
            "decision_label": decision_label,
            "decision_description": decision_description,
            "available": available,
            "quality_score": quality,
            "reasons": reasons,
            "decision_at": decision_at,
            "entry_price": result.price,
            "stop_loss": result.stop_loss,
            "take_profits": result.take_profits,
            "risk_reward": result.risk_reward,
            "scanner": result.model_dump(mode="json"),
            "outcomes": {"4": None, "12": None, "24": None},
            "outcome_note": "Chỉ bổ sung sau khi đủ nến đóng sau thời điểm quyết định",
            "shadow_only": True,
        }

    @staticmethod
    def _closed_candle_time(scanned_at: datetime, timeframe: str) -> str:
        """Canonical UTC close boundary of the closed candle being audited."""
        interval_ms = SmartEntryOutcomeAnalytics._interval_ms(timeframe)
        timestamp_ms = int(scanned_at.timestamp() * 1000)
        return datetime.fromtimestamp((timestamp_ms // interval_ms) * interval_ms / 1000, UTC).isoformat()

    @staticmethod
    def decision_presentation(decision: str) -> tuple[str, str]:
        """Vietnamese display text for a shadow decision; never an execution instruction."""
        if decision == "WOULD_ENTER":
            return (
                "SẼ VÀO LỆNH (mô phỏng)",
                "Candidate đạt điều kiện của Smart Entry Shadow. Chỉ ghi nhận để theo dõi, không gửi lệnh.",
            )
        return (
            "BỎ QUA (mô phỏng)",
            "Candidate chưa đạt điều kiện Smart Entry Shadow hoặc thiếu dữ liệu xác minh. Không gửi lệnh.",
        )


class SmartEntryOutcomeAnalytics:
    """Build immutable post-decision outcomes from a complete closed-candle prefix."""

    VERSION = "SMART_ENTRY_OUTCOME_V1"
    HORIZONS = (4, 12, 24)

    @classmethod
    def evaluate(cls, decision: dict[str, Any], candles: list[Candle]) -> list[dict[str, Any]]:
        interval_ms = cls._interval_ms(str(decision["timeframe"]))
        decision_ms = cls._timestamp_ms(str(decision["decision_at"]))
        expected_open = ((decision_ms + interval_ms - 1) // interval_ms) * interval_ms
        ordered = sorted(candles, key=lambda candle: candle.open_time)
        cls._validate_prefix(ordered, expected_open, interval_ms)
        outcomes: list[dict[str, Any]] = []
        for horizon in cls.HORIZONS:
            if len(ordered) < horizon:
                continue
            window = ordered[:horizon]
            entry = float(decision["entry_price"])
            direction = 1.0 if decision["side"] == SignalAction.LONG.value else -1.0
            close_return = direction * (window[-1].close - entry) / entry
            favorable = max(
                direction * (candle.high - entry) / entry
                if direction > 0
                else direction * (candle.low - entry) / entry
                for candle in window
            )
            adverse = min(
                direction * (candle.low - entry) / entry
                if direction > 0
                else direction * (candle.high - entry) / entry
                for candle in window
            )
            identity = {
                "version": cls.VERSION,
                "decision_event_key": decision["event_key"],
                "horizon": horizon,
                "last_close_time": window[-1].close_time,
            }
            fingerprint = hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            outcomes.append(
                {
                    "event_key": f"{cls.VERSION}:{fingerprint}",
                    "fingerprint": fingerprint,
                    "version": cls.VERSION,
                    "decision_event_key": decision["event_key"],
                    "mode": decision["mode"],
                    "symbol": decision["symbol"],
                    "decision": decision["decision"],
                    "side": decision["side"],
                    "timeframe": decision["timeframe"],
                    "regime": decision.get("scanner", {}).get("regime", "UNKNOWN"),
                    "decision_closed_candle_time": decision.get("closed_candle_time", decision["decision_at"]),
                    "horizon": horizon,
                    "entry_price": entry,
                    "close_price": window[-1].close,
                    "return_fraction": close_return,
                    "mfe_fraction": max(0.0, favorable),
                    "mae_fraction": min(0.0, adverse),
                    "first_open_time": window[0].open_time,
                    "last_close_time": window[-1].close_time,
                    "candle_count": horizon,
                    "coverage": 1.0,
                    "available": True,
                    "reason": "Đủ nến đóng liên tục sau quyết định",
                    "shadow_only": True,
                }
            )
        return outcomes

    @staticmethod
    def _timestamp_ms(value: str) -> int:
        from datetime import datetime

        return int(datetime.fromisoformat(value).timestamp() * 1000)

    @staticmethod
    def _interval_ms(value: str) -> int:
        unit = value[-1]
        amount = int(value[:-1])
        return amount * {"m": 60_000, "h": 3_600_000}[unit]

    @staticmethod
    def _validate_prefix(candles: list[Candle], expected_open: int, interval_ms: int) -> None:
        for index, candle in enumerate(candles):
            expected = expected_open + index * interval_ms
            if candle.open_time != expected or candle.close_time >= expected + interval_ms:
                raise ValueError("Chuỗi nến outcome không liên tục hoặc chứa nến chưa đóng")


class SmartEntryPerformanceReport:
    """Deterministic descriptive report; never recommends or changes thresholds."""

    MIN_SAMPLE = 30

    @classmethod
    def build(cls, items: list[dict[str, Any]]) -> dict[str, Any]:
        from statistics import median

        # Reporting is defensive as well as storage: never let a legacy row,
        # import, or accidental duplicate turn repeated observations into evidence.
        # V2's audit key is symbol + timeframe + side + closed-candle time.
        independent_items, duplicate_events_excluded = cls._independent_items(items)
        rows = []
        duplicate_outcomes_excluded = 0
        seen_outcomes: set[tuple[str, int]] = set()
        for item in independent_items:
            for outcome in item.get("outcomes", {}).values():
                if outcome is not None:
                    outcome_key = (str(item["event_key"]), int(outcome["horizon"]))
                    if outcome_key in seen_outcomes:
                        duplicate_outcomes_excluded += 1
                        continue
                    seen_outcomes.add(outcome_key)
                    rows.append({**outcome, "quality_score": item["quality_score"]})

        def metrics(group: list[dict[str, Any]]) -> dict[str, Any]:
            sample = len(group)
            returns = [float(row["return_fraction"]) for row in group]
            status = (
                "ĐỦ MẪU ĐỂ ĐÁNH GIÁ"
                if sample >= cls.MIN_SAMPLE
                else ("ĐANG THU THẬP" if sample else "CHƯA ĐỦ DỮ LIỆU")
            )
            return {
                "sample_size": sample,
                "confidence_status": status,
                "win_rate": sum(value > 0 for value in returns) / sample if sample else None,
                "average_return": sum(returns) / sample if sample else None,
                "median_return": median(returns) if sample else None,
                "average_mfe": sum(float(row["mfe_fraction"]) for row in group) / sample
                if sample
                else None,
                "average_mae": sum(float(row["mae_fraction"]) for row in group) / sample
                if sample
                else None,
            }

        dimensions: dict[str, dict[str, dict[str, Any]]] = {}
        selectors = {
            "horizon": lambda row: str(row["horizon"]),
            "decision": lambda row: str(row["decision"]),
            "side": lambda row: str(row["side"]),
            "symbol": lambda row: str(row["symbol"]),
            "timeframe": lambda row: str(row["timeframe"]),
            "regime": lambda row: str(row.get("regime", row.get("scanner", {}).get("regime", "UNKNOWN"))),
            "time_bucket_utc": lambda row: str(row.get("decision_closed_candle_time", row.get("first_open_time", "UNKNOWN")))[:10],
            "quality_band": lambda row: (
                "80-100"
                if row["quality_score"] >= 80
                else ("60-79" if row["quality_score"] >= 60 else "0-59")
            ),
        }
        for name, selector in selectors.items():
            keys = sorted({selector(row) for row in rows})
            dimensions[name] = {
                key: metrics([row for row in rows if selector(row) == key]) for key in keys
            }
        return {
            "sample_size": len(rows),
            "independent_decision_count": len(independent_items),
            "duplicate_events_excluded": duplicate_events_excluded,
            "duplicate_outcomes_excluded": duplicate_outcomes_excluded,
            "confidence_status": metrics(rows)["confidence_status"],
            "minimum_sample": cls.MIN_SAMPLE,
            "overall": metrics(rows),
            "dimensions": dimensions,
            "note": "Thống kê mô tả shadow-only trên mẫu độc lập; không tối ưu threshold và không thay đổi Baseline.",
            "preregistered_pass_criteria": {
                "expected_return_after_costs": "Phải dương sau phí/slippage; báo cáo hiện tại không xác nhận pass nếu chưa có chi phí chuẩn hóa.",
                "minimum_sample": cls.MIN_SAMPLE,
                "cross_symbol": "Không được phụ thuộc một symbol.",
                "time_stability": "Phải ổn định theo các lát thời gian độc lập.",
            },
        }

    @staticmethod
    def _independent_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        """Keep the first immutable observation for each audit unit."""
        unique: dict[str, dict[str, Any]] = {}
        excluded = 0
        for item in items:
            audit_key = str(item.get("audit_key") or item.get("event_key"))
            if audit_key in unique:
                excluded += 1
                continue
            unique[audit_key] = item
        return list(unique.values()), excluded


class SmartEntryOutcomeCollector:
    """Durably collect closed-candle outcomes away from read-only reporting."""

    MAX_ATTEMPTS = 6

    def __init__(self, app_state: Any, *, interval_seconds: int = 60, batch_size: int = 25) -> None:
        self.state = app_state
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self.task: asyncio.Task[None] | None = None
        self.running = False
        self.cycles = 0
        self.last_run_at: datetime | None = None
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.consecutive_failures = 0
        self.last_cycle = self._empty_cycle()

    @staticmethod
    def _empty_cycle() -> dict[str, int]:
        return {
            "decisions_scanned": 0,
            "decisions_pending": 0,
            "decisions_complete": 0,
            "decisions_retrying": 0,
            "decisions_permanent_error": 0,
            "decisions_failed": 0,
            "outcomes_saved": 0,
        }

    def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.running and self.task is not None and not self.task.done(),
            "interval_seconds": self.interval_seconds,
            "batch_size": self.batch_size,
            "cycles": self.cycles,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "last_cycle": self.last_cycle,
        }

    async def _run(self) -> None:
        await self.state.storage.log(
            "Smart Entry outcome collector started",
            {"interval_seconds": self.interval_seconds, "batch_size": self.batch_size},
        )
        while self.running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                self.consecutive_failures += 1
                await self.state.storage.log(
                    "Smart Entry outcome collector cycle error",
                    {"error": str(exc), "consecutive_failures": self.consecutive_failures},
                    level="ERROR",
                )
            await asyncio.sleep(self.interval_seconds)

    async def run_once(self, *, now: datetime | None = None) -> dict[str, int]:
        self.cycles += 1
        self.last_run_at = now or datetime.now(UTC)
        stats = self._empty_cycle()
        cycle_errors: list[str] = []
        for mode in ("DEMO", "LIVE"):
            decisions = await self.state.storage.pending_smart_entry_events(
                mode=mode, now=self.last_run_at, limit=self.batch_size
            )
            if not decisions:
                continue
            outcomes = await self.state.storage.smart_entry_outcomes(
                mode=mode, decision_keys=[str(item["event_key"]) for item in decisions]
            )
            completed_by_key: dict[str, set[int]] = {}
            for outcome in outcomes:
                completed_by_key.setdefault(str(outcome["decision_event_key"]), set()).add(
                    int(outcome["horizon"])
                )
            for decision in decisions:
                await asyncio.sleep(0)
                stats["decisions_scanned"] += 1
                key = str(decision["event_key"])
                completed = completed_by_key.get(key, set())
                interval_ms = SmartEntryOutcomeAnalytics._interval_ms(str(decision["timeframe"]))
                decision_ms = SmartEntryOutcomeAnalytics._timestamp_ms(str(decision["decision_at"]))
                first_open = ((decision_ms + interval_ms - 1) // interval_ms) * interval_ms
                available_count = min(
                    24,
                    max(0, (int(self.last_run_at.timestamp() * 1000) - first_open) // interval_ms),
                )
                if available_count < 4:
                    stats["decisions_pending"] += 1
                    next_due_ms = first_open + 4 * interval_ms
                    await self.state.storage.set_smart_entry_collection_state(
                        decision_event_key=key,
                        mode=mode,
                        status="NOT_MATURED",
                        next_retry_at=datetime.fromtimestamp(next_due_ms / 1000, UTC),
                    )
                    continue
                try:
                    candles = await self.state.market_client.closed_klines_range(
                        str(decision["symbol"]),
                        str(decision["timeframe"]),
                        start_time=first_open,
                        end_time=first_open + available_count * interval_ms,
                        limit=available_count,
                    )
                    for outcome in SmartEntryOutcomeAnalytics.evaluate(decision, candles):
                        if int(
                            outcome["horizon"]
                        ) not in completed and await self.state.storage.save_smart_entry_outcome(
                            outcome
                        ):
                            stats["outcomes_saved"] += 1
                            completed.add(int(outcome["horizon"]))
                    complete = len(completed) == len(SmartEntryOutcomeAnalytics.HORIZONS)
                    stats["decisions_complete" if complete else "decisions_pending"] += 1
                    next_horizon = next(
                        (h for h in SmartEntryOutcomeAnalytics.HORIZONS if h not in completed), None
                    )
                    next_retry_at = (
                        datetime.fromtimestamp(
                            (first_open + next_horizon * interval_ms) / 1000, UTC
                        )
                        if next_horizon is not None
                        else None
                    )
                    await self.state.storage.set_smart_entry_collection_state(
                        decision_event_key=key,
                        mode=mode,
                        status="COMPLETE" if complete else "PENDING",
                        next_retry_at=next_retry_at,
                    )
                except (ValueError, httpx.HTTPError) as exc:
                    previous = await self.state.storage.smart_entry_collection_state(key)
                    attempts = int(previous["attempts"]) + 1 if previous else 1
                    permanent = attempts >= self.MAX_ATTEMPTS
                    retry_at = (
                        None
                        if permanent
                        else self.last_run_at
                        + timedelta(seconds=min(3600, 30 * 2 ** (attempts - 1)))
                    )
                    await self.state.storage.set_smart_entry_collection_state(
                        decision_event_key=key,
                        mode=mode,
                        status="PERMANENT_ERROR" if permanent else "RETRYING",
                        attempts=attempts,
                        next_retry_at=retry_at,
                        last_error=str(exc),
                    )
                    stats["decisions_failed"] += 1
                    stats["decisions_permanent_error" if permanent else "decisions_retrying"] += 1
                    cycle_errors.append(f"{key}: {exc}")
        self.last_cycle = stats
        if cycle_errors:
            self.last_error = cycle_errors[-1]
            self.consecutive_failures += 1
            await self.state.storage.log(
                "Smart Entry outcome collection incomplete",
                {"failures": len(cycle_errors), "last_error": self.last_error, "stats": stats},
                level="WARNING",
            )
        else:
            self.last_error = None
            self.consecutive_failures = 0
            self.last_success_at = self.last_run_at
        return stats
