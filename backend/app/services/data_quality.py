from datetime import UTC, datetime
from itertools import pairwise

from app.domain.models import Candle, DataQualityAssessment, Timeframe

_TIMEFRAME_MS = {
    Timeframe.M1: 60_000,
    Timeframe.M5: 300_000,
    Timeframe.M15: 900_000,
    Timeframe.H1: 3_600_000,
    Timeframe.H4: 14_400_000,
}


class MarketDataQualityGate:
    """Deterministic, fail-closed quality gate for scanner candle evidence."""

    MINIMUM_CANDLES = 200
    MINIMUM_CONFIDENCE = 0.90

    @classmethod
    def evaluate(
        cls,
        candles: list[Candle],
        timeframe: Timeframe,
        *,
        now: datetime | None = None,
        stale_data_seconds: int = 180,
    ) -> DataQualityAssessment:
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
        now_ms = int(checked_at.timestamp() * 1000)
        interval_ms = _TIMEFRAME_MS[timeframe]
        closed = [candle for candle in candles if candle.close_time < now_ms]
        reasons: list[str] = []

        complete = len(closed) >= cls.MINIMUM_CANDLES
        if not complete:
            reasons.append(f"Chỉ có {len(closed)}/{cls.MINIMUM_CANDLES} nến đã đóng")

        chronological = all(
            current.open_time > previous.open_time for previous, current in pairwise(closed)
        )
        continuous = chronological and all(
            current.open_time == previous.open_time + interval_ms
            for previous, current in pairwise(closed)
        )
        if closed and not chronological:
            reasons.append("Nến không theo thứ tự thời gian")
        elif len(closed) > 1 and not continuous:
            reasons.append("Chuỗi nến có khoảng trống hoặc sai timeframe")

        valid = bool(closed) and all(cls._valid_candle(candle) for candle in closed)
        if not valid:
            reasons.append("OHLC hoặc volume không hợp lệ")

        age_seconds = max(0.0, (now_ms - closed[-1].close_time) / 1000) if closed else None
        # A newly closed bar can naturally be almost one timeframe old.
        freshness_limit = interval_ms / 1000 + stale_data_seconds
        fresh = age_seconds is not None and age_seconds <= freshness_limit
        if not fresh:
            reasons.append("Nến đóng mới nhất đã quá cũ")

        confidence = round(
            (0.35 if complete else 0.0)
            + (0.25 if continuous else 0.0)
            + (0.20 if valid else 0.0)
            + (0.20 if fresh else 0.0),
            2,
        )
        accepted = confidence >= cls.MINIMUM_CONFIDENCE and not reasons
        return DataQualityAssessment(
            accepted=accepted,
            status="PASS" if accepted else "BLOCKED",
            confidence=confidence,
            minimum_confidence=cls.MINIMUM_CONFIDENCE,
            sample_size=len(closed),
            minimum_candles=cls.MINIMUM_CANDLES,
            latest_closed_at=(
                datetime.fromtimestamp(closed[-1].close_time / 1000, tz=UTC) if closed else None
            ),
            age_seconds=age_seconds,
            complete=complete,
            continuous=continuous,
            valid=valid,
            fresh=fresh,
            reasons=reasons,
            checked_at=checked_at,
        )

    @staticmethod
    def _valid_candle(candle: Candle) -> bool:
        return (
            candle.open_time >= 0
            and candle.close_time >= candle.open_time
            and candle.open > 0
            and candle.high > 0
            and candle.low > 0
            and candle.close > 0
            and candle.low <= min(candle.open, candle.close)
            and candle.high >= max(candle.open, candle.close)
            and candle.high >= candle.low
            and candle.volume >= 0
            and candle.quote_volume >= 0
        )
