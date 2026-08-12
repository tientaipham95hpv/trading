import hashlib
import json
from typing import Any

from app.domain.models import Candle, ScannerResult, SignalAction


class SmartEntryAnalytics:
    """Deterministic, observational entry-quality classifier.

    It consumes only the scanner snapshot already produced from closed candles. The
    result is evidence, never an execution input.
    """

    VERSION = "SMART_ENTRY_SHADOW_V1"

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
        identity = {
            "version": cls.VERSION,
            "mode": mode,
            "symbol": result.symbol,
            "timeframe": result.timeframe.value,
            "side": result.action.value,
            "decision_at": decision_at,
            "price": result.price,
            "stop_loss": result.stop_loss,
            "scores": [result.long_score, result.short_score],
            "risk_reward": result.risk_reward,
        }
        fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "event_key": f"{cls.VERSION}:{fingerprint}",
            "fingerprint": fingerprint,
            "version": cls.VERSION,
            "mode": mode,
            "symbol": result.symbol,
            "timeframe": result.timeframe.value,
            "side": result.action.value,
            "decision": decision,
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

        rows = []
        for item in items:
            for outcome in item.get("outcomes", {}).values():
                if outcome is not None:
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
            "confidence_status": metrics(rows)["confidence_status"],
            "minimum_sample": cls.MIN_SAMPLE,
            "overall": metrics(rows),
            "dimensions": dimensions,
            "note": "Thống kê mô tả shadow-only; không tối ưu threshold và không thay đổi Baseline.",
        }
