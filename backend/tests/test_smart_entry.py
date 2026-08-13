from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.domain.models import (
    IndicatorSnapshot,
    MarketRegime,
    ScannerResult,
    SignalAction,
    Timeframe,
)
from app.services.smart_entry import SmartEntryAnalytics, SmartEntryOutcomeCollector


def result(**updates):
    data = {
        "symbol": "BTCUSDT",
        "timeframe": Timeframe.M15,
        "regime": MarketRegime.TRENDING_UP,
        "long_score": 80,
        "short_score": 10,
        "action": SignalAction.LONG,
        "price": 100,
        "stop_loss": 98,
        "take_profits": [104],
        "risk_reward": 2,
        "indicators": IndicatorSnapshot(atr=2, adx=25),
        "scanned_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    data.update(updates)
    return ScannerResult(**data)


def test_smart_entry_is_deterministic_and_advisory():
    first = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    second = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    assert first == second
    assert first["decision"] == "WOULD_ENTER"
    assert first["shadow_only"] is True
    assert first["outcomes"] == {"4": None, "12": None, "24": None}


def test_smart_entry_fails_safe_without_initial_risk():
    item = SmartEntryAnalytics.evaluate(result(stop_loss=None), mode="DEMO")
    assert item["decision"] == "WOULD_SKIP"
    assert item["available"] is False
    assert any("Stop Loss" in reason for reason in item["reasons"])


from app.domain.models import Candle
from app.services.smart_entry import SmartEntryOutcomeAnalytics


def candles(count: int, *, start: int = 1_767_225_600_000, step: int = 900_000):
    return [
        Candle(
            open_time=start + index * step,
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=1,
            close_time=start + (index + 1) * step - 1,
        )
        for index in range(count)
    ]


def test_outcomes_only_publish_complete_horizons_without_lookahead():
    decision = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    outcomes = SmartEntryOutcomeAnalytics.evaluate(decision, candles(12))
    assert [item["horizon"] for item in outcomes] == [4, 12]
    assert all(item["candle_count"] == item["horizon"] for item in outcomes)
    assert all(item["coverage"] == 1 for item in outcomes)


def test_outcomes_are_deterministic_for_long_and_short():
    long_decision = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    short_decision = SmartEntryAnalytics.evaluate(
        result(action=SignalAction.SHORT, long_score=10, short_score=80, stop_loss=102), mode="DEMO"
    )
    first = SmartEntryOutcomeAnalytics.evaluate(long_decision, candles(24))
    assert first == SmartEntryOutcomeAnalytics.evaluate(long_decision, candles(24))
    assert first[-1]["return_fraction"] > 0
    assert SmartEntryOutcomeAnalytics.evaluate(short_decision, candles(4))[0]["return_fraction"] < 0


def test_outcomes_reject_gaps_and_forming_candles():
    decision = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    broken = candles(4)
    broken[2] = broken[2].model_copy(update={"open_time": broken[2].open_time + 1})
    import pytest

    with pytest.raises(ValueError, match="không liên tục"):
        SmartEntryOutcomeAnalytics.evaluate(decision, broken)


from app.services.smart_entry import SmartEntryPerformanceReport


def test_performance_report_is_descriptive_and_sample_guarded():
    decision = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    decision["outcomes"] = {
        str(row["horizon"]): row
        for row in SmartEntryOutcomeAnalytics.evaluate(decision, candles(24))
    }
    report = SmartEntryPerformanceReport.build([decision])
    assert report["sample_size"] == 3
    assert report["confidence_status"] == "ĐANG THU THẬP"
    assert report["overall"]["win_rate"] == 1
    assert report["dimensions"]["horizon"]["4"]["sample_size"] == 1
    assert "không tối ưu threshold" in report["note"]


def test_performance_report_handles_no_verified_outcomes():
    assert SmartEntryPerformanceReport.build([])["confidence_status"] == "CHƯA ĐỦ DỮ LIỆU"


async def test_outcome_collector_persists_available_horizons_and_reports_coverage():
    decision = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    storage = SimpleNamespace(
        pending_smart_entry_events=AsyncMock(side_effect=[[decision], []]),
        smart_entry_outcomes=AsyncMock(return_value=[]),
        save_smart_entry_outcome=AsyncMock(return_value=True),
        set_smart_entry_collection_state=AsyncMock(),
        smart_entry_collection_state=AsyncMock(return_value=None),
        log=AsyncMock(),
    )
    market_client = SimpleNamespace(closed_klines_range=AsyncMock(return_value=candles(12)))
    collector = SmartEntryOutcomeCollector(
        SimpleNamespace(storage=storage, market_client=market_client), interval_seconds=1
    )

    stats = await collector.run_once(now=datetime(2026, 1, 1, 3, tzinfo=UTC))

    assert stats == {
        "decisions_scanned": 1,
        "decisions_pending": 1,
        "decisions_complete": 0,
        "decisions_retrying": 0,
        "decisions_permanent_error": 0,
        "decisions_failed": 0,
        "outcomes_saved": 2,
    }
    assert storage.save_smart_entry_outcome.await_count == 2
    assert collector.snapshot()["last_error"] is None


async def test_outcome_collector_exposes_retryable_data_error():
    decision = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    storage = SimpleNamespace(
        pending_smart_entry_events=AsyncMock(side_effect=[[decision], []]),
        smart_entry_outcomes=AsyncMock(return_value=[]),
        save_smart_entry_outcome=AsyncMock(),
        set_smart_entry_collection_state=AsyncMock(),
        smart_entry_collection_state=AsyncMock(return_value=None),
        log=AsyncMock(),
    )
    market_client = SimpleNamespace(
        closed_klines_range=AsyncMock(side_effect=ValueError("gap in closed candles"))
    )
    collector = SmartEntryOutcomeCollector(
        SimpleNamespace(storage=storage, market_client=market_client)
    )

    stats = await collector.run_once(now=datetime(2026, 1, 2, tzinfo=UTC))

    assert stats["decisions_failed"] == 1
    assert collector.snapshot()["consecutive_failures"] == 1
    assert "gap in closed candles" in collector.snapshot()["last_error"]
    storage.log.assert_awaited_once()


async def test_outcome_collector_retries_with_backoff_then_marks_permanent_error():
    decision = SmartEntryAnalytics.evaluate(result(), mode="DEMO")
    storage = SimpleNamespace(
        pending_smart_entry_events=AsyncMock(side_effect=[[decision], []]),
        smart_entry_outcomes=AsyncMock(return_value=[]),
        save_smart_entry_outcome=AsyncMock(),
        set_smart_entry_collection_state=AsyncMock(),
        smart_entry_collection_state=AsyncMock(return_value={"attempts": 5}),
        log=AsyncMock(),
    )
    market_client = SimpleNamespace(
        closed_klines_range=AsyncMock(side_effect=ValueError("bad historical data"))
    )
    collector = SmartEntryOutcomeCollector(
        SimpleNamespace(storage=storage, market_client=market_client)
    )
    stats = await collector.run_once(now=datetime(2026, 1, 2, tzinfo=UTC))
    assert stats["decisions_permanent_error"] == 1
    assert storage.set_smart_entry_collection_state.await_args.kwargs["status"] == "PERMANENT_ERROR"
    assert storage.set_smart_entry_collection_state.await_args.kwargs["next_retry_at"] is None
