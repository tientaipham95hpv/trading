from datetime import UTC, datetime

from app.domain.models import (
    EmergencyStopState,
    GuardSnapshot,
    MarketRegime,
    RiskDecision,
    Side,
    StrategySignal,
)


class RiskEngine:
    def __init__(
        self,
        *,
        max_leverage: int = 5,
        risk_per_trade: float = 0.005,
        max_risk_per_trade: float = 0.01,
        max_daily_loss: float = 0.04,
        max_weekly_drawdown: float = 0.08,
        max_open_positions: int = 4,
        max_portfolio_exposure: float = 1.0,
        max_correlated_positions: int = 2,
        max_loss_streak: int = 3,
        extreme_volatility_atr_fraction: float = 0.06,
        stale_data_seconds: int = 180,
        minimum_risk_reward: float = 1.8,
    ) -> None:
        self.max_leverage = max_leverage
        self.risk_per_trade = risk_per_trade
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_weekly_drawdown = max_weekly_drawdown
        self.max_open_positions = max_open_positions
        self.max_portfolio_exposure = max_portfolio_exposure
        self.max_correlated_positions = max_correlated_positions
        self.max_loss_streak = max_loss_streak
        self.extreme_volatility_atr_fraction = extreme_volatility_atr_fraction
        self.stale_data_seconds = stale_data_seconds
        self.minimum_risk_reward = minimum_risk_reward

    def evaluate(
        self,
        signal: StrategySignal,
        *,
        open_positions: int,
        daily_loss_fraction: float,
        emergency_stop: EmergencyStopState,
        account_equity: float = 10_000.0,
        weekly_drawdown_fraction: float = 0.0,
        portfolio_exposure_fraction: float = 0.0,
        correlated_positions: int = 0,
        loss_streak: int = 0,
        market_regime: MarketRegime | None = None,
        atr_fraction: float | None = None,
        data_age_seconds: float = 0.0,
        safe_mode: bool = False,
    ) -> RiskDecision:
        guard = self.guard_snapshot(
            daily_loss_fraction=daily_loss_fraction,
            weekly_drawdown_fraction=weekly_drawdown_fraction,
            portfolio_exposure_fraction=portfolio_exposure_fraction,
            correlated_positions=correlated_positions,
            loss_streak=loss_streak,
            market_regime=market_regime,
            atr_fraction=atr_fraction,
            data_age_seconds=data_age_seconds,
            safe_mode=safe_mode,
        )
        if guard.reasons:
            return RiskDecision(accepted=False, reason=guard.reasons[0], guard=guard)
        if emergency_stop.active:
            return RiskDecision(accepted=False, reason="Dừng khẩn cấp đang bật", guard=guard)
        if signal.stop_loss <= 0:
            return RiskDecision(accepted=False, reason="Bắt buộc có stop loss", guard=guard)
        if signal.leverage > self.max_leverage:
            return RiskDecision(accepted=False, reason="Đòn bẩy vượt giới hạn tối đa", guard=guard)
        if signal.risk_fraction > self.max_risk_per_trade:
            return RiskDecision(accepted=False, reason="Rủi ro mỗi lệnh vượt mức 1%", guard=guard)
        if signal.risk_fraction > self.risk_per_trade:
            return RiskDecision(accepted=False, reason="Rủi ro mỗi lệnh vượt mặc định 0.5%", guard=guard)
        if open_positions >= self.max_open_positions:
            return RiskDecision(accepted=False, reason="Đã chạm số vị thế mở tối đa", guard=guard)
        if signal.metadata.get("sizing") in {"martingale", "unlimited_dca"}:
            return RiskDecision(accepted=False, reason="Không cho phép martingale hoặc DCA không giới hạn", guard=guard)
        if signal.side == Side.LONG and signal.stop_loss >= signal.entry_price:
            return RiskDecision(accepted=False, reason="Stop loss LONG phải thấp hơn giá vào lệnh", guard=guard)
        if signal.side == Side.SHORT and signal.stop_loss <= signal.entry_price:
            return RiskDecision(accepted=False, reason="Stop loss SHORT phải cao hơn giá vào lệnh", guard=guard)

        target = signal.take_profit or (signal.take_profits[-1] if signal.take_profits else None)
        if target is None:
            return RiskDecision(accepted=False, reason="Bắt buộc có TP để tính RR", guard=guard)
        reward = abs(target - signal.entry_price)
        risk_per_unit = abs(signal.entry_price - signal.stop_loss)
        if risk_per_unit <= 0:
            return RiskDecision(accepted=False, reason="Khoảng SL không hợp lệ", guard=guard)
        risk_reward = reward / risk_per_unit
        if risk_reward < self.minimum_risk_reward:
            return RiskDecision(accepted=False, reason="RR nhỏ hơn 1.8", guard=guard)

        risk_amount = account_equity * signal.risk_fraction
        quantity = risk_amount / risk_per_unit
        notional = quantity * signal.entry_price
        margin_required = notional / signal.leverage
        return RiskDecision(
            accepted=True,
            signal=signal,
            quantity=quantity,
            notional=notional,
            margin_required=margin_required,
            risk_amount=risk_amount,
            risk_reward=risk_reward,
            guard=guard,
        )

    def guard_snapshot(
        self,
        *,
        daily_loss_fraction: float,
        weekly_drawdown_fraction: float,
        portfolio_exposure_fraction: float,
        correlated_positions: int,
        loss_streak: int,
        market_regime: MarketRegime | None,
        atr_fraction: float | None,
        data_age_seconds: float,
        safe_mode: bool,
    ) -> GuardSnapshot:
        reasons: list[str] = []
        daily_breaker = daily_loss_fraction >= self.max_daily_loss
        weekly_breaker = weekly_drawdown_fraction >= self.max_weekly_drawdown
        exposure_breaker = portfolio_exposure_fraction >= self.max_portfolio_exposure
        correlation_risk = correlated_positions >= self.max_correlated_positions
        loss_cooldown = loss_streak >= self.max_loss_streak
        extreme_volatility = (
            market_regime in {MarketRegime.HIGH_VOL, MarketRegime.PANIC}
            or (atr_fraction is not None and atr_fraction >= self.extreme_volatility_atr_fraction)
        )
        stale_data = data_age_seconds > self.stale_data_seconds
        if safe_mode:
            reasons.append("SAFE_MODE đang bật")
        if daily_breaker:
            reasons.append("Đã chạm daily circuit breaker 4%")
        if weekly_breaker:
            reasons.append("Đã chạm weekly DD 8%")
        if exposure_breaker:
            reasons.append("Portfolio exposure vượt giới hạn")
        if correlation_risk:
            reasons.append("Correlation risk vượt giới hạn")
        if loss_cooldown:
            reasons.append("Loss streak cooldown đang bật")
        if extreme_volatility:
            reasons.append("Extreme volatility guard đang bật")
        if stale_data:
            reasons.append("Stale data guard đang bật")
        return GuardSnapshot(
            portfolio_exposure=portfolio_exposure_fraction,
            correlation_risk=correlation_risk,
            daily_circuit_breaker=daily_breaker,
            weekly_drawdown=weekly_drawdown_fraction,
            loss_streak=loss_streak,
            loss_streak_cooldown=loss_cooldown,
            extreme_volatility=extreme_volatility,
            stale_data=stale_data,
            reasons=reasons,
        )


def seconds_since(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, (datetime.now(UTC) - value).total_seconds())
