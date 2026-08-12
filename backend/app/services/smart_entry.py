import hashlib
import json
from typing import Any

from app.domain.models import ScannerResult, SignalAction


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
