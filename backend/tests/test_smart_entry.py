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
