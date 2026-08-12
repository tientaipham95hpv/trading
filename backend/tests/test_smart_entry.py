from datetime import UTC, datetime

from app.domain.models import (
    IndicatorSnapshot,
    MarketRegime,
    ScannerResult,
    SignalAction,
    Timeframe,
)
from app.services.smart_entry import SmartEntryAnalytics


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
