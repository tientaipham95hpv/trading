from types import SimpleNamespace

from app.domain.models import IndicatorSnapshot, MarketRegime, SignalAction, Timeframe
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
