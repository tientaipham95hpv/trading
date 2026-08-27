from app.domain.models import BotSettings
from app.services.capital_risk import (
    VND_PER_USDT,
    capital_risk_profile,
    capital_risk_profile_for_mode,
)


def test_below_one_million_blocks_live():
    profile = capital_risk_profile((1_000_000 / VND_PER_USDT) - 0.01)
    assert profile.observed_tier == "BELOW_1M_VND"
    assert profile.live_allowed is False
    assert profile.name == "LIVE_BLOCKED_BELOW_1M"


def test_one_to_five_million_uses_conservative_limits():
    profile = capital_risk_profile(4_000_000 / VND_PER_USDT)
    assert profile.live_allowed is True
    assert profile.risk_per_trade == 0.0025
    assert profile.max_risk_per_trade == 0.005
    assert profile.max_leverage == 3
    assert profile.max_open_positions == 1
    assert profile.max_margin_per_trade == 0.10
    assert profile.max_total_margin == 0.15
    assert profile.max_daily_loss == 0.02
    assert profile.max_weekly_drawdown == 0.05
    assert profile.risk_amount_vnd == 10_000


def test_five_to_twenty_million_uses_middle_live_tier():
    profile = capital_risk_profile(10_000_000 / VND_PER_USDT)
    assert profile.observed_tier == "5M_TO_20M_VND"
    assert profile.name == "LIVE_TIER_5M_TO_20M"
    assert profile.risk_per_trade == 0.0035
    assert profile.max_leverage == 5
    assert profile.max_open_positions == 1
    assert profile.max_portfolio_exposure == 0.50


def test_larger_capital_auto_raises_live_risk_below_demo_limits():
    profile = capital_risk_profile(25_000_000 / VND_PER_USDT)
    assert profile.observed_tier == "ABOVE_20M_VND"
    assert profile.name == "LIVE_TIER_ABOVE_20M"
    assert profile.risk_per_trade == 0.005
    assert profile.max_leverage == 7
    assert profile.max_open_positions == 1
    assert profile.max_portfolio_exposure == 0.75
    assert "thấp hơn DEMO" in profile.reason


def test_exact_tier_boundaries():
    one_million = capital_risk_profile(1_000_000 / VND_PER_USDT)
    five_million = capital_risk_profile(5_000_000 / VND_PER_USDT)
    twenty_million = capital_risk_profile(20_000_000 / VND_PER_USDT)
    assert one_million.observed_tier == "1M_TO_5M_VND"
    assert one_million.live_allowed is True
    assert five_million.observed_tier == "5M_TO_20M_VND"
    assert twenty_million.observed_tier == "ABOVE_20M_VND"


def test_non_positive_equity_is_normalized_and_live_blocked():
    for equity in (0, -10):
        profile = capital_risk_profile(equity)
        assert profile.equity_usdt == 0
        assert profile.risk_amount_usdt == 0
        assert profile.live_allowed is False


def test_demo_profile_allows_three_positions_with_portfolio_limits():
    settings = BotSettings(
        max_leverage=10,
        max_total_open_risk=0.05,
        max_margin_per_trade=0.15,
        max_total_margin=0.50,
        max_portfolio_exposure=1.00,
        max_open_positions=3,
    )

    profile = capital_risk_profile_for_mode(
        25_000_000 / VND_PER_USDT,
        mode="DEMO",
        settings=settings,
    )

    assert profile.name == "DEMO_SETTINGS"
    assert profile.max_leverage == 10
    assert profile.max_open_positions == 3
    assert profile.max_total_margin == 0.50
    assert profile.max_portfolio_exposure == 1.00


def test_live_profile_hard_caps_positions_at_one():
    settings = BotSettings(max_leverage=10, max_open_positions=3)

    profile = capital_risk_profile_for_mode(
        25_000_000 / VND_PER_USDT,
        mode="LIVE",
        settings=settings,
    )

    assert profile.name == "LIVE_TIER_ABOVE_20M"
    assert profile.max_open_positions == 1
    assert profile.max_leverage == 7


def test_validation_universe_requires_a_nonempty_usdt_whitelist():
    try:
        BotSettings(whitelist=[])
    except ValueError as exc:
        assert "Whitelist không được để trống" in str(exc)
    else:
        raise AssertionError("Không được cho phép scanner universe rỗng")

    settings = BotSettings(whitelist=["btcusdt"], blacklist=[])
    assert settings.whitelist == ["BTCUSDT"]
