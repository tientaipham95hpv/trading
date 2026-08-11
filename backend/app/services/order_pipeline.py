from app.domain.models import OrderPlan, RiskDecision


class PositionSizer:
    def apply(self, decision: RiskDecision) -> float:
        if decision.quantity is None or decision.quantity <= 0:
            raise ValueError("PositionSizer không có quantity hợp lệ")
        return decision.quantity


class OrderValidator:
    def validate(self, plan: OrderPlan) -> None:
        if not plan.client_order_id:
            raise ValueError("Bắt buộc có client_order_id để chống duplicate")
        if plan.stop_loss <= 0:
            raise ValueError("Bắt buộc có stop loss")
        if plan.quantity <= 0:
            raise ValueError("Quantity không hợp lệ")
        if plan.entry_price <= 0:
            raise ValueError("Entry price không hợp lệ")
        if plan.leverage <= 0:
            raise ValueError("Leverage không hợp lệ")
        if not plan.take_profits:
            raise ValueError("Bắt buộc có TP")
