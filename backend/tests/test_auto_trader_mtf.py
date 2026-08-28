from types import SimpleNamespace

import pytest

from app.domain.models import IndicatorSnapshot, MarketRegime, SignalAction, Timeframe, TradingMode
from app.services.auto_trader import AutoTrader


def result(
    timeframe: Timeframe,
    *,
    action: SignalAction = SignalAction.LONG,
    regime: MarketRegime = MarketRegime.TRENDING_UP,
    price: float = 100.0,
    ema20: float | None = 99.0,
    atr: float | None = 2.0,
    strategy: str | None = "Trend Pullback",
    reasons: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="BTCUSDT",
        timeframe=timeframe,
        action=action,
        regime=regime,
        price=price,
        indicators=IndicatorSnapshot(ema20=ema20, atr=atr),
        strategy=strategy,
        reasons=reasons or [],
    )


def trader() -> AutoTrader:
    return AutoTrader(
        SimpleNamespace(
            bot_settings=SimpleNamespace(extreme_volatility_atr_fraction=0.06),
        )
    )


def demo_trader() -> AutoTrader:
    return AutoTrader(
        SimpleNamespace(
            trading_mode=TradingMode.DEMO,
            settings=SimpleNamespace(
                demo_test_allow_high_vol_regime=True,
                demo_test_min_score=80,
                demo_test_min_risk_reward=1.8,
                demo_test_max_long_ema20_distance_atr=1.75,
            ),
            bot_settings=SimpleNamespace(extreme_volatility_atr_fraction=0.06),
        )
    )


def test_mtf_accepts_15m_only_after_1h_and_4h_same_direction():
    candidates, rejected = trader()._mtf_candidates(
        [result(Timeframe.M15), result(Timeframe.H1), result(Timeframe.H4)]
    )

    assert len(candidates) == 1
    assert rejected == {}


def test_mtf_rejects_4h_sideways_even_with_strong_15m_trigger():
    candidates, rejected = trader()._mtf_candidates(
        [
            result(Timeframe.M15),
            result(Timeframe.H1),
            result(Timeframe.H4, regime=MarketRegime.RANGING),
        ]
    )

    assert candidates == []
    assert rejected == {"4h không có xu hướng rõ": 1}


def test_mtf_rejects_conflicting_higher_timeframes():
    candidates, rejected = trader()._mtf_candidates(
        [
            result(Timeframe.M15),
            result(Timeframe.H1, action=SignalAction.SHORT, regime=MarketRegime.TRENDING_DOWN),
            result(Timeframe.H4),
        ]
    )

    assert candidates == []
    assert rejected == {"1h không xác nhận xu hướng 4h": 1}


def test_mtf_uses_4h_as_regime_not_as_independent_entry_signal():
    candidates, rejected = trader()._mtf_candidates(
        [
            result(Timeframe.M15),
            result(Timeframe.H1),
            result(Timeframe.H4, action=SignalAction.NO_TRADE),
        ]
    )

    assert len(candidates) == 1
    assert rejected == {}


def test_mtf_requires_1h_pullback_or_breakout_structure():
    candidates, rejected = trader()._mtf_candidates(
        [
            result(Timeframe.M15),
            result(Timeframe.H1, strategy=None),
            result(Timeframe.H4),
        ]
    )

    assert candidates == []
    assert rejected == {"1h chưa có vùng pullback/breakout hợp lệ": 1}


def test_mtf_rejects_4h_high_volatility_and_panic():
    for regime in (MarketRegime.HIGH_VOL, MarketRegime.PANIC):
        candidates, rejected = trader()._mtf_candidates(
            [result(Timeframe.M15), result(Timeframe.H1), result(Timeframe.H4, regime=regime)]
        )

        assert candidates == []
        assert rejected == {"4h volatility cao/panic": 1}


def test_demo_profile_allows_high_vol_4h_when_1h_and_15m_confirm_direction():
    candidates, rejected = demo_trader()._mtf_candidates(
        [
            result(Timeframe.M15),
            result(Timeframe.H1),
            result(Timeframe.H4, regime=MarketRegime.HIGH_VOL),
        ]
    )

    assert len(candidates) == 1
    assert rejected == {}


def test_demo_profile_still_rejects_panic_4h():
    candidates, rejected = demo_trader()._mtf_candidates(
        [
            result(Timeframe.M15),
            result(Timeframe.H1),
            result(Timeframe.H4, regime=MarketRegime.PANIC),
        ]
    )

    assert candidates == []
    assert rejected == {"4h volatility cao/panic": 1}


def test_demo_rejects_overextended_long_on_15m_or_1h():
    for frame in (Timeframe.M15, Timeframe.H1):
        items = [result(Timeframe.M15), result(Timeframe.H1), result(Timeframe.H4)]
        target = next(item for item in items if item.timeframe == frame)
        target.price = 103.6
        target.indicators = IndicatorSnapshot(ema20=100.0, atr=2.0)

        candidates, rejected = demo_trader()._mtf_candidates(items)

        assert candidates == []
        assert rejected == {"DEMO bỏ LONG đuổi giá: cách EMA20 quá 1.75 ATR": 1}


def test_demo_anti_chase_gate_does_not_change_short_entries():
    items = [
        result(Timeframe.M15, action=SignalAction.SHORT, regime=MarketRegime.TRENDING_DOWN),
        result(Timeframe.H1, action=SignalAction.SHORT, regime=MarketRegime.TRENDING_DOWN),
        result(Timeframe.H4, action=SignalAction.SHORT, regime=MarketRegime.TRENDING_DOWN),
    ]
    items[0].price = 96.0
    items[0].indicators = IndicatorSnapshot(ema20=100.0, atr=2.0)

    candidates, rejected = demo_trader()._mtf_candidates(items)

    assert len(candidates) == 1
    assert rejected == {}


@pytest.mark.parametrize(
    ("symbol", "distance_15m", "distance_1h", "accepted"),
    [
        ("OGNUSDT", 1.01, 1.81, False),
        ("TSTUSDT", 1.40, 1.66, True),
        ("QUSDT", 1.59, 1.32, True),
        ("HYPEUSDT", 1.59, 1.52, True),
        ("JUPUSDT", 2.43, 2.04, False),
        ("WLDUSDT", 1.85, 1.70, False),
        ("AIOUSDT", 1.86, 1.95, False),
    ],
)
def test_demo_anti_chase_replays_latest_closed_cohort(
    symbol: str, distance_15m: float, distance_1h: float, accepted: bool
):
    items = [result(Timeframe.M15), result(Timeframe.H1), result(Timeframe.H4)]
    for item in items:
        item.symbol = symbol
    items[0].price = 100 + distance_15m * 2
    items[0].indicators = IndicatorSnapshot(ema20=100, atr=2)
    items[1].price = 100 + distance_1h * 2
    items[1].indicators = IndicatorSnapshot(ema20=100, atr=2)

    candidates, _ = demo_trader()._mtf_candidates(items)

    assert bool(candidates) is accepted


def test_mtf_rejects_trigger_when_it_is_too_far_from_ema_or_too_volatile():
    candidates, rejected = trader()._mtf_candidates(
        [
            result(Timeframe.M15, price=106.0, ema20=100.0, atr=2.0),
            result(Timeframe.H1),
            result(Timeframe.H4),
        ]
    )
    assert candidates == []
    assert rejected == {"15m chạy quá xa EMA20 (>2 ATR)": 1}

    candidates, rejected = trader()._mtf_candidates(
        [
            result(Timeframe.M15, price=100.0, ema20=99.0, atr=7.0),
            result(Timeframe.H1),
            result(Timeframe.H4),
        ]
    )
    assert candidates == []
    assert rejected == {"15m volatility vượt ngưỡng ATR": 1}
