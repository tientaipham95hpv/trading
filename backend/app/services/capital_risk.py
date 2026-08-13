from dataclasses import asdict, dataclass

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
                "mode": "AUTO_CONSERVATIVE",
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
    if not live_allowed:
        reason = "Vốn Futures dưới 1.000.000 VND quy đổi; chặn lệnh LIVE"
    elif observed == "1M_TO_5M_VND":
        reason = "Profile vốn 1–5 triệu VND"
    else:
        reason = (
            f"Vốn thuộc bậc {observed}, nhưng AUTO_CONSERVATIVE giữ trần rủi ro "
            "bậc 1–5 triệu cho tới khi có gate hiệu suất được phê duyệt"
        )

    # AUTO_CONSERVATIVE deliberately caps risk-taking parameters at the first live tier.
    # Equity still scales every order's monetary risk and position quantity.
    return CapitalRiskProfile(
        name="AUTO_CONSERVATIVE_1M_TO_5M",
        observed_tier=observed,
        equity_usdt=equity_usdt,
        equity_vnd=equity_vnd,
        risk_per_trade=0.0025,
        max_risk_per_trade=0.005,
        max_leverage=3,
        max_open_positions=1,
        max_margin_per_trade=0.10,
        max_total_margin=0.15,
        max_daily_loss=0.02,
        max_weekly_drawdown=0.05,
        max_portfolio_exposure=0.30,
        live_allowed=live_allowed,
        reason=reason,
    )
