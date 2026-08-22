from datetime import UTC, datetime, timedelta

from app.domain.models import Candle, Timeframe
from app.services.data_quality import MarketDataQualityGate


def candles(
    count: int = 250,
    *,
    now: datetime = datetime(2026, 8, 13, tzinfo=UTC),
    timeframe: Timeframe = Timeframe.M15,
) -> list[Candle]:
    step = 900_000 if timeframe == Timeframe.M15 else 3_600_000
    latest_close = int(now.timestamp() * 1000) - 1
    first_open = latest_close - count * step + 1
    return [
        Candle(
            open_time=first_open + index * step,
            open=100,
            high=102,
            low=99,
            close=101,
            volume=10,
            quote_volume=1_000,
            close_time=first_open + (index + 1) * step - 1,
        )
        for index in range(count)
    ]


def test_data_quality_accepts_complete_continuous_closed_evidence():
    now = datetime(2026, 8, 13, tzinfo=UTC)
    assessment = MarketDataQualityGate.evaluate(candles(now=now), Timeframe.M15, now=now)

    assert assessment.accepted is True
    assert assessment.status == "PASS"
    assert assessment.confidence == 1
    assert assessment.sample_size == 250
    assert assessment.reasons == []


def test_data_quality_fails_closed_for_gap_and_insufficient_sample():
    now = datetime(2026, 8, 13, tzinfo=UTC)
    evidence = candles(199, now=now)
    evidence[100] = evidence[100].model_copy(
        update={
            "open_time": evidence[100].open_time + 1,
            "close_time": evidence[100].close_time + 1,
        }
    )

    assessment = MarketDataQualityGate.evaluate(evidence, Timeframe.M15, now=now)

    assert assessment.accepted is False
    assert assessment.complete is False
    assert assessment.continuous is False
    assert assessment.confidence < assessment.minimum_confidence
    assert len(assessment.reasons) == 2


def test_data_quality_rejects_stale_or_forming_only_tail():
    now = datetime(2026, 8, 13, tzinfo=UTC)
    stale = MarketDataQualityGate.evaluate(
        candles(now=now - timedelta(hours=2)), Timeframe.M15, now=now
    )
    evidence = candles(200, now=now)
    evidence.append(
        evidence[-1].model_copy(
            update={
                "open_time": int(now.timestamp() * 1000),
                "close_time": int(now.timestamp() * 1000) + 899_999,
            }
        )
    )
    forming_tail = MarketDataQualityGate.evaluate(evidence, Timeframe.M15, now=now)

    assert stale.accepted is False
    assert stale.fresh is False
    assert forming_tail.accepted is True
    assert forming_tail.sample_size == 200
