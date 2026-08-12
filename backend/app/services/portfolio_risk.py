from datetime import UTC, datetime

from app.domain.models import ExchangeSnapshot, PortfolioRiskPosition, PortfolioRiskSnapshot


class PortfolioRiskEngine:
    """Deterministic, read-only portfolio risk accounting for Phase 7 shadow mode."""

    def snapshot(
        self,
        exchange: ExchangeSnapshot,
        *,
        max_open_risk_fraction: float,
        max_exposure_fraction: float,
    ) -> PortfolioRiskSnapshot:
        equity = max(exchange.balance.margin_balance or exchange.balance.balance, 0.0)
        lifecycles = {item.symbol: item for item in exchange.lifecycles}
        items: list[PortfolioRiskPosition] = []
        reasons: list[str] = []
        long_notional = short_notional = open_risk = 0.0
        for position in exchange.positions:
            price = position.mark_price or position.entry_price
            notional = abs(position.quantity) * price
            side = position.side.upper()
            long_notional += notional if side == "LONG" else 0.0
            short_notional += notional if side == "SHORT" else 0.0
            stop = lifecycles.get(position.symbol).active_stop if position.symbol in lifecycles else None
            if stop is None:
                matching = [
                    order.stop_price
                    for order in exchange.orders
                    if order.symbol == position.symbol
                    and order.status == "NEW"
                    and "STOP" in order.order_type
                    and "TAKE_PROFIT" not in order.order_type
                    and order.stop_price
                ]
                stop = matching[0] if len(matching) == 1 else None
            protected = stop is not None and (
                (side == "LONG" and stop < position.entry_price)
                or (side == "SHORT" and stop > position.entry_price)
            )
            risk_amount = abs(position.entry_price - stop) * abs(position.quantity) if protected and stop else None
            if risk_amount is None:
                reasons.append(f"{position.symbol} chưa có Stop Loss hợp lệ để tính open risk")
            else:
                open_risk += risk_amount
            items.append(PortfolioRiskPosition(symbol=position.symbol, side=side, quantity=abs(position.quantity), entry_price=position.entry_price, mark_price=price, stop_loss=stop, notional=notional, open_risk=risk_amount, protected=protected))
        gross = long_notional + short_notional
        limit = equity * max_open_risk_fraction
        exposure_limit = equity * max_exposure_fraction
        if equity <= 0:
            reasons.append("Không có equity hợp lệ để tính ngân sách danh mục")
        if open_risk > limit:
            reasons.append("Tổng open risk vượt ngân sách")
        if gross > exposure_limit:
            reasons.append("Gross exposure vượt giới hạn")
        return PortfolioRiskSnapshot(
            generated_at=datetime.now(UTC), equity=equity, long_notional=long_notional,
            short_notional=short_notional, gross_exposure=gross,
            net_exposure=long_notional-short_notional,
            gross_exposure_fraction=gross/equity if equity else 0.0,
            net_exposure_fraction=(long_notional-short_notional)/equity if equity else 0.0,
            open_risk=open_risk, open_risk_fraction=open_risk/equity if equity else 0.0,
            open_risk_limit=limit, open_risk_remaining=max(0.0, limit-open_risk),
            exposure_limit=exposure_limit, positions=items, reasons=reasons,
            would_reject_new_entries=bool(reasons),
        )
