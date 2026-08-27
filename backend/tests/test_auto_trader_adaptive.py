from types import SimpleNamespace

import pytest

from app.domain.models import MarketRegime, TradingMode
from app.services.auto_trader import AutoTrader


def make_result(*, symbol: str, score: int, confidence: float = 0.8, rr: float = 2.0):
    return SimpleNamespace(
        symbol=symbol,
        long_score=score,
        short_score=0,
        confidence=confidence,
        risk_reward=rr,
        price=100.0,
        regime=MarketRegime.TRENDING_UP,
        indicators=SimpleNamespace(atr=1.0),
    )


def make_trader() -> AutoTrader:
    settings = SimpleNamespace(
        risk_per_trade=0.001,
        max_risk_per_trade=0.0025,
        max_leverage=10,
        max_open_positions=3,
        max_margin_per_trade=0.10,
        max_total_margin=0.25,
        max_daily_loss=0.04,
        max_weekly_drawdown=0.08,
        max_portfolio_exposure=0.50,
    )
    return AutoTrader(
        SimpleNamespace(
            trading_mode=TradingMode.DEMO,
            bot_settings=settings,
        )
    )


def test_candidate_ranking_prefers_quality_over_scanner_order():
    low = make_result(symbol="LOWUSDT", score=82, confidence=0.75, rr=1.9)
    high = make_result(symbol="HIGHUSDT", score=92, confidence=0.90, rr=2.8)

    ranked = make_trader()._rank_candidates([low, high])

    assert [item.symbol for item in ranked] == ["HIGHUSDT", "LOWUSDT"]


def test_demo_risk_budget_scales_with_score_and_correlation():
    trader = make_trader()
    profile = trader._capital_profile(5_000)
    low = make_result(symbol="LOWUSDT", score=82)
    high = make_result(symbol="HIGHUSDT", score=92)

    low_risk = trader._risk_fraction_for_candidate(
        low, correlated_positions=0, profile=profile
    )
    high_risk = trader._risk_fraction_for_candidate(
        high, correlated_positions=0, profile=profile
    )
    correlated_risk = trader._risk_fraction_for_candidate(
        high, correlated_positions=1, profile=profile
    )

    assert low_risk == pytest.approx(0.0005)
    assert high_risk == pytest.approx(0.001)
    assert correlated_risk == pytest.approx(0.0005)


def test_correlation_buckets_group_major_beta_and_separate_sectors():
    trader = make_trader()

    assert trader._correlation_bucket("BTCUSDT") == "BTC_BETA"
    assert trader._correlation_bucket("ETHUSDT") == "BTC_BETA"
    assert trader._correlation_bucket("DOGEUSDT") == "MEME"
    assert trader._correlation_bucket("AAVEUSDT") == "DEFI"

