from app.domain.models import EmergencyStopState, RiskDecision, Side, StrategySignal


class RiskEngine:
    def __init__(
        self,
        *,
        max_leverage: int = 5,
        risk_per_trade: float = 0.005,
        max_risk_per_trade: float = 0.01,
        max_daily_loss: float = 0.04,
        max_open_positions: int = 4,
        minimum_risk_reward: float = 1.8,
    ) -> None:
        self.max_leverage = max_leverage
        self.risk_per_trade = risk_per_trade
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_open_positions = max_open_positions
        self.minimum_risk_reward = minimum_risk_reward

    def evaluate(
        self,
        signal: StrategySignal,
        *,
        open_positions: int,
        daily_loss_fraction: float,
        emergency_stop: EmergencyStopState,
        account_equity: float = 10_000.0,
    ) -> RiskDecision:
        if emergency_stop.active:
            return RiskDecision(accepted=False, reason="Dừng khẩn cấp đang bật")
        if signal.stop_loss <= 0:
            return RiskDecision(accepted=False, reason="Bắt buộc có stop loss")
        if signal.leverage > self.max_leverage:
            return RiskDecision(accepted=False, reason="Đòn bẩy vượt giới hạn tối đa")
        if signal.risk_fraction > self.max_risk_per_trade:
            return RiskDecision(accepted=False, reason="Rủi ro mỗi lệnh vượt mức 1%")
        if signal.risk_fraction > self.risk_per_trade:
            return RiskDecision(accepted=False, reason="Rủi ro mỗi lệnh vượt mặc định 0.5%")
        if daily_loss_fraction >= self.max_daily_loss:
            return RiskDecision(accepted=False, reason="Đã chạm mức lỗ tối đa trong ngày")
        if open_positions >= self.max_open_positions:
            return RiskDecision(accepted=False, reason="Đã chạm số vị thế mở tối đa")
        if signal.metadata.get("sizing") == "martingale":
            return RiskDecision(accepted=False, reason="Không cho phép martingale")
        if signal.side == Side.LONG and signal.stop_loss >= signal.entry_price:
            return RiskDecision(accepted=False, reason="Stop loss LONG phải thấp hơn giá vào lệnh")
        if signal.side == Side.SHORT and signal.stop_loss <= signal.entry_price:
            return RiskDecision(accepted=False, reason="Stop loss SHORT phải cao hơn giá vào lệnh")

        target = signal.take_profit or (signal.take_profits[-1] if signal.take_profits else None)
        if target is None:
            return RiskDecision(accepted=False, reason="Bắt buộc có TP để tính RR")
        reward = abs(target - signal.entry_price)
        risk_per_unit = abs(signal.entry_price - signal.stop_loss)
        if risk_per_unit <= 0:
            return RiskDecision(accepted=False, reason="Khoảng SL không hợp lệ")
        risk_reward = reward / risk_per_unit
        if risk_reward < self.minimum_risk_reward:
            return RiskDecision(accepted=False, reason="RR nhỏ hơn 1.8")

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
        )
