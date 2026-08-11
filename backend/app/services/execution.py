from datetime import UTC, datetime
from statistics import mean, pstdev
from uuid import uuid4

from app.domain.models import (
    BotSettings,
    OrderPlan,
    OrderStatus,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PerformanceSnapshot,
    PositionStatus,
    Side,
    TradeRecord,
)


class DuplicateOrderError(Exception):
    pass


class ExecutionService:
    def __init__(self, settings: BotSettings | None = None) -> None:
        self.settings = settings or BotSettings()
        self.balance = self.settings.paper_initial_balance
        self._submitted_client_ids: set[str] = set()
        self.orders: list[PaperOrder] = []
        self.fills: list[PaperFill] = []
        self.positions: list[PaperPosition] = []
        self.trades: list[TradeRecord] = []

    async def submit_order_plan(self, plan: OrderPlan) -> dict[str, object]:
        if plan.client_order_id in self._submitted_client_ids:
            raise DuplicateOrderError(plan.client_order_id)
        self._submitted_client_ids.add(plan.client_order_id)

        fill_price, slippage = self._apply_slippage(plan.entry_price, plan.side, entry=True)
        fee = fill_price * plan.quantity * self.settings.taker_fee_rate
        order = PaperOrder(
            id=str(uuid4()),
            client_order_id=plan.client_order_id,
            symbol=plan.symbol,
            side=plan.side,
            order_type=plan.order_type,
            status=OrderStatus.FILLED,
            quantity=plan.quantity,
            filled_quantity=plan.quantity,
            price=plan.entry_price,
            stop_loss=plan.stop_loss,
            take_profits=plan.take_profits,
        )
        fill = PaperFill(
            id=str(uuid4()),
            order_id=order.id,
            symbol=plan.symbol,
            side=plan.side,
            quantity=plan.quantity,
            price=fill_price,
            fee=fee,
            slippage=slippage,
            reason="ENTRY",
        )
        position = PaperPosition(
            id=str(uuid4()),
            symbol=plan.symbol,
            side=plan.side,
            quantity=plan.quantity,
            remaining_quantity=plan.quantity,
            entry_price=fill_price,
            stop_loss=plan.stop_loss,
            take_profits=plan.take_profits,
            fees_paid=fee,
        )
        self.balance -= fee
        self.orders.append(order)
        self.fills.append(fill)
        self.positions.append(position)
        return {
            "accepted": True,
            "client_order_id": plan.client_order_id,
            "status": "PAPER_FILLED",
            "order": order.model_dump(mode="json"),
            "position": position.model_dump(mode="json"),
        }

    def update_market_price(self, symbol: str, price: float) -> list[TradeRecord]:
        closed: list[TradeRecord] = []
        for position in list(self.open_positions(symbol)):
            self._apply_funding(position)
            if self._stop_hit(position, price):
                closed.append(self._close_position(position, price, "SL"))
                continue
            for take_profit in position.take_profits:
                if take_profit in position.filled_take_profits:
                    continue
                if self._target_hit(position, price, take_profit):
                    closed.append(self._partial_take_profit(position, take_profit))
                    if len(position.filled_take_profits) == 1:
                        position.break_even_active = True
                        position.stop_loss = position.entry_price
                    if len(position.filled_take_profits) >= 2:
                        position.trailing_stop_active = True
                        position.trailing_stop_distance = abs(take_profit - position.entry_price) * 0.35
            if position.trailing_stop_active and position.trailing_stop_distance:
                self._move_trailing_stop(position, price)
        return closed

    def open_positions(self, symbol: str | None = None) -> list[PaperPosition]:
        return [
            position
            for position in self.positions
            if position.status == PositionStatus.OPEN and (symbol is None or position.symbol == symbol)
        ]

    def cancel_open_orders(self) -> list[PaperOrder]:
        self.orders = [
            order.model_copy(update={"status": OrderStatus.CANCELED})
            if order.status in {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED}
            else order
            for order in self.orders
        ]
        return self.orders

    def close_all_positions(self) -> list[TradeRecord]:
        closed: list[TradeRecord] = []
        for position in list(self.open_positions()):
            closed.append(self._close_position(position, position.entry_price, "CLOSE_ALL"))
        return closed

    def performance(self, marks: dict[str, float] | None = None) -> PerformanceSnapshot:
        marks = marks or {}
        unrealized = 0.0
        for position in self.open_positions():
            mark = marks.get(position.symbol, position.entry_price)
            unrealized += self._gross_pnl(position.side, position.entry_price, mark, position.remaining_quantity)
        total_trades = len(self.trades)
        wins = sum(1 for trade in self.trades if trade.net_pnl > 0)
        gross_profit = sum(trade.net_pnl for trade in self.trades if trade.net_pnl > 0)
        gross_loss = abs(sum(trade.net_pnl for trade in self.trades if trade.net_pnl <= 0))
        realized = sum(trade.net_pnl for trade in self.trades)
        fees = sum(fill.fee for fill in self.fills)
        funding = sum(position.funding_paid for position in self.positions)
        returns = [trade.net_pnl for trade in self.trades]
        avg_return = mean(returns) if returns else 0.0
        volatility = pstdev(returns) if len(returns) > 1 else 0.0
        downside = [value for value in returns if value < 0]
        downside_vol = pstdev(downside) if len(downside) > 1 else 0.0
        equity = self.settings.paper_initial_balance
        peak = equity
        max_drawdown = 0.0
        for trade in self.trades:
            equity += trade.net_pnl
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        return PerformanceSnapshot(
            balance=self.balance,
            equity=self.balance + unrealized,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            fees_paid=fees,
            funding_paid=funding,
            win_rate=(wins / total_trades) if total_trades else 0.0,
            total_trades=total_trades,
            open_positions=len(self.open_positions()),
            profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
            max_drawdown=max_drawdown,
            sharpe=(avg_return / volatility) if volatility > 0 else 0.0,
            sortino=(avg_return / downside_vol) if downside_vol > 0 else 0.0,
            expectancy=avg_return,
        )

    def _partial_take_profit(self, position: PaperPosition, price: float) -> TradeRecord:
        fraction = 0.4 if not position.filled_take_profits else 0.3
        quantity = min(position.remaining_quantity, position.quantity * fraction)
        position.filled_take_profits.append(price)
        return self._close_quantity(position, price, quantity, "TP")

    def _close_position(self, position: PaperPosition, price: float, reason: str) -> TradeRecord:
        return self._close_quantity(position, price, position.remaining_quantity, reason)

    def _close_quantity(
        self, position: PaperPosition, price: float, quantity: float, reason: str
    ) -> TradeRecord:
        fill_price, slippage = self._apply_slippage(price, position.side, entry=False)
        gross = self._gross_pnl(position.side, position.entry_price, fill_price, quantity)
        fee = fill_price * quantity * self.settings.taker_fee_rate
        net = gross - fee
        trade = TradeRecord(
            id=str(uuid4()),
            symbol=position.symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=fill_price,
            quantity=quantity,
            gross_pnl=gross,
            fee=fee,
            slippage=slippage,
            funding=position.funding_paid,
            net_pnl=net,
            reason=reason,
        )
        fill = PaperFill(
            id=str(uuid4()),
            order_id=position.id,
            symbol=position.symbol,
            side=position.side,
            quantity=quantity,
            price=fill_price,
            fee=fee,
            slippage=slippage,
            reason=reason,
        )
        position.remaining_quantity = max(0.0, position.remaining_quantity - quantity)
        position.realized_pnl += net
        position.fees_paid += fee
        if position.remaining_quantity <= 1e-12:
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.now(UTC)
        self.balance += net
        self.trades.append(trade)
        self.fills.append(fill)
        return trade

    def _apply_slippage(self, price: float, side: Side, *, entry: bool) -> tuple[float, float]:
        adjustment = price * self.settings.slippage_bps / 10_000
        worse_for_long = side == Side.LONG and entry or side == Side.SHORT and not entry
        fill_price = price + adjustment if worse_for_long else price - adjustment
        return fill_price, abs(fill_price - price)

    def _apply_funding(self, position: PaperPosition) -> None:
        notional = position.remaining_quantity * position.entry_price
        funding = notional * self.settings.funding_rate_per_8h / (8 * 60)
        position.funding_paid += funding
        self.balance -= funding

    @staticmethod
    def _gross_pnl(side: Side, entry: float, exit_price: float, quantity: float) -> float:
        if side == Side.LONG:
            return (exit_price - entry) * quantity
        return (entry - exit_price) * quantity

    @staticmethod
    def _stop_hit(position: PaperPosition, price: float) -> bool:
        if position.side == Side.LONG:
            return price <= position.stop_loss
        return price >= position.stop_loss

    @staticmethod
    def _target_hit(position: PaperPosition, price: float, target: float) -> bool:
        if position.side == Side.LONG:
            return price >= target
        return price <= target

    @staticmethod
    def _move_trailing_stop(position: PaperPosition, price: float) -> None:
        distance = position.trailing_stop_distance or 0
        if position.side == Side.LONG:
            position.stop_loss = max(position.stop_loss, price - distance)
        else:
            position.stop_loss = min(position.stop_loss, price + distance)
