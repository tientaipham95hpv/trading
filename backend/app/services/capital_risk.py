from dataclasses import asdict, dataclass, replace
from typing import Any

# Operational planning rate, intentionally fixed so risk does not change with FX noise.
VND_PER_USDT = 26_000.0
MIN_LIVE_CAPITAL_VND = 1_000_000.0


@dataclass(frozen=True)
class CapitalRiskProfile:
    name: str
    observed_tier: str
    equity_usdt: float
    equity_vnd: float
    risk_per_trade: float
    max_risk_per_trade: float
    max_leverage: int
    max_open_positions: int
    max_margin_per_trade: float
    max_total_margin: float
    max_daily_loss: float
    max_weekly_drawdown: float
    max_portfolio_exposure: float
    live_allowed: bool
    reason: str

    @property
    def risk_amount_usdt(self) -> float:
        return self.equity_usdt * self.risk_per_trade

    @property
    def risk_amount_vnd(self) -> float:
        return self.equity_vnd * self.risk_per_trade

    def snapshot(self) -> dict[str, object]:
        result = asdict(self)
        result.update(
            {
                "mode": self.name,
                "vnd_per_usdt": VND_PER_USDT,
                "risk_amount_usdt": self.risk_amount_usdt,
                "risk_amount_vnd": self.risk_amount_vnd,
            }
        )
        return result


def capital_risk_profile(equity_usdt: float) -> CapitalRiskProfile:
    equity_usdt = max(float(equity_usdt), 0.0)
    equity_vnd = equity_usdt * VND_PER_USDT
    if equity_vnd < 1_000_000:
        observed = "BELOW_1M_VND"
    elif equity_vnd < 5_000_000:
        observed = "1M_TO_5M_VND"
    elif equity_vnd < 20_000_000:
        observed = "5M_TO_20M_VND"
    else:
        observed = "ABOVE_20M_VND"

    live_allowed = equity_vnd >= MIN_LIVE_CAPITAL_VND
    reason = "Vốn Futures dưới 1.000.000 VND quy đổi; chặn lệnh LIVE"
    name = "LIVE_BLOCKED_BELOW_1M"
    risk_per_trade = 0.0025
    max_risk_per_trade = 0.005
    max_leverage = 3
    max_open_positions = 1
    max_margin_per_trade = 0.10
    max_total_margin = 0.15
    max_daily_loss = 0.02
    max_weekly_drawdown = 0.05
    max_portfolio_exposure = 0.30

    if live_allowed and observed == "1M_TO_5M_VND":
        name = "LIVE_TIER_1M_TO_5M"
        reason = "LIVE tự chỉnh theo vốn 1–5 triệu VND: ưu tiên bảo toàn vốn."
    elif observed == "5M_TO_20M_VND":
        name = "LIVE_TIER_5M_TO_20M"
        risk_per_trade = 0.0035
        max_risk_per_trade = 0.006
        max_leverage = 5
        max_open_positions = 2
        max_margin_per_trade = 0.12
        max_total_margin = 0.25
        max_daily_loss = 0.03
        max_weekly_drawdown = 0.06
        max_portfolio_exposure = 0.50
        reason = "LIVE tự chỉnh theo vốn 5–20 triệu VND: tăng room vừa phải."
    elif observed == "ABOVE_20M_VND":
        name = "LIVE_TIER_ABOVE_20M"
        risk_per_trade = 0.005
        max_risk_per_trade = 0.0075
        max_leverage = 7
        max_open_positions = 3
        max_margin_per_trade = 0.15
        max_total_margin = 0.35
        max_daily_loss = 0.04
        max_weekly_drawdown = 0.08
        max_portfolio_exposure = 0.75
        reason = "LIVE tự chỉnh theo vốn trên 20 triệu VND: linh hoạt hơn nhưng vẫn thấp hơn DEMO."

    return CapitalRiskProfile(
        name=name,
        observed_tier=observed,
        equity_usdt=equity_usdt,
        equity_vnd=equity_vnd,
        risk_per_trade=risk_per_trade,
        max_risk_per_trade=max_risk_per_trade,
        max_leverage=max_leverage,
        max_open_positions=max_open_positions,
        max_margin_per_trade=max_margin_per_trade,
        max_total_margin=max_total_margin,
        max_daily_loss=max_daily_loss,
        max_weekly_drawdown=max_weekly_drawdown,
        max_portfolio_exposure=max_portfolio_exposure,
        live_allowed=live_allowed,
        reason=reason,
    )


def capital_risk_profile_for_mode(
    equity_usdt: float, *, mode: str, settings: Any
) -> CapitalRiskProfile:
    profile = capital_risk_profile(equity_usdt)
    if mode != "DEMO":
        return profile

    return replace(
        profile,
        name="DEMO_SETTINGS",
        risk_per_trade=settings.risk_per_trade,
        max_risk_per_trade=settings.max_risk_per_trade,
        max_leverage=min(int(settings.max_leverage), 10),
        max_open_positions=settings.max_open_positions,
        max_margin_per_trade=settings.max_margin_per_trade,
        max_total_margin=settings.max_total_margin,
        max_daily_loss=settings.max_daily_loss,
        max_weekly_drawdown=settings.max_weekly_drawdown,
        max_portfolio_exposure=settings.max_portfolio_exposure,
        reason="DEMO dùng giới hạn từ BotSettings; profile vốn chỉ dùng để quan sát.",
    )
