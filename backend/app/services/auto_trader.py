import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.domain.models import (
    BotState,
    ExchangeExecutionResult,
    MarketRegime,
    NotificationEvent,
    OrderPlan,
    SignalAction,
    Timeframe,
    TradingMode,
)
from app.services.exchange import ExchangeCredentialsError, ExchangeError


class AutoTrader:
    def __init__(self, app_state: Any, *, interval_seconds: int = 45) -> None:
        self.state = app_state
        self.interval_seconds = interval_seconds
        self.task: asyncio.Task[None] | None = None
        self.running = False
        self.last_run_at: datetime | None = None
        self.last_action_at: datetime | None = None
        self.last_status = "IDLE"
        self.last_reason = "Chưa chạy vòng auto-trade"
        self.last_symbol: str | None = None
        self.cycles = 0
        self.submitted = 0
        self.rejected = 0

    def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def snapshot(self) -> dict[str, object]:
        return {
            "running": self.running and self.task is not None and not self.task.done(),
            "interval_seconds": self.interval_seconds,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_action_at": self.last_action_at.isoformat() if self.last_action_at else None,
            "last_status": self.last_status,
            "last_reason": self.last_reason,
            "last_symbol": self.last_symbol,
            "cycles": self.cycles,
            "submitted": self.submitted,
            "rejected": self.rejected,
        }

    async def _run(self) -> None:
        await self.state.storage.log(
            "Auto-trader worker started", {"interval_seconds": self.interval_seconds}
        )
        while self.running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - background worker must not die on one cycle
                self.last_status = "ERROR"
                self.last_reason = str(exc)
                await self.state.storage.log(
                    "Auto-trader cycle error", {"error": str(exc)}, level="ERROR"
                )
            await asyncio.sleep(self.interval_seconds)

    async def run_once(self) -> dict[str, object]:
        self.cycles += 1
        self.last_run_at = datetime.now(UTC)

        if self.state.bot_state != BotState.RUNNING:
            return await self._skip(
                "IDLE", f"Bot state {self.state.bot_state.value}, không auto-trade"
            )
        if self.state.emergency_stop.active:
            return await self._skip("BLOCKED", "Emergency Stop đang bật")
        if self.state.safe_mode:
            return await self._skip("BLOCKED", self.state.safe_mode_reason or "SAFE_MODE đang bật")
        if self.state.trading_mode == TradingMode.LIVE and not self._live_allowed():
            return await self._skip("BLOCKED", "LIVE chưa pass readiness")

        snapshot = None
        account_equity = self.state.execution.performance().equity
        active_symbols: set[str] = set()
        open_position_count = len(self.state.execution.open_positions())
        portfolio_exposure_fraction = self._portfolio_exposure_fraction()
        if self.state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            adapter = (
                self.state.live_exchange
                if self.state.trading_mode == TradingMode.LIVE
                else self.state.demo_exchange
            )
            try:
                snapshot = await adapter.snapshot()
                account_equity = max(
                    snapshot.balance.margin_balance or snapshot.balance.available, 1.0
                )
            except (ExchangeCredentialsError, ExchangeError) as exc:
                self.rejected += 1
                return await self._skip("BLOCKED", f"Exchange snapshot lỗi: {exc}")
            snapshot, orphan_symbols = await self._clean_exchange_orphans(adapter, snapshot)
            if orphan_symbols:
                return await self._skip(
                    "CLEANED_ORPHAN_ORDERS",
                    f"Đã hủy order mồ côi cho {', '.join(orphan_symbols)}; chờ chu kỳ sau mới xét lệnh mới",
                )
            unprotected_symbols = self._unprotected_exchange_positions(snapshot)
            if unprotected_symbols:
                try:
                    repairs = await adapter.repair_missing_stop_losses(snapshot)
                    if repairs:
                        await self.state.storage.log(
                            "Đã tự động phục hồi Stop Loss",
                            {"mode": self.state.trading_mode.value, "actions": repairs},
                            level="WARNING",
                        )
                        snapshot = await adapter.snapshot()
                        unprotected_symbols = self._unprotected_exchange_positions(snapshot)
                except Exception as exc:  # noqa: BLE001 - watchdog vẫn phải khóa an toàn
                    await self.state.storage.log(
                        "Phục hồi Stop Loss thất bại", {"error": str(exc)}, level="ERROR"
                    )
            if unprotected_symbols:
                reason = f"SAFE_MODE: vị thế không có SL bảo vệ: {', '.join(unprotected_symbols)}"
                self.state.enter_safe_mode(reason)
                await self.state.storage.log(
                    "Auto-trader protection watchdog entered safe mode",
                    {"mode": self.state.trading_mode.value, "symbols": unprotected_symbols},
                    level="CRITICAL",
                )
                return await self._skip("BLOCKED", reason)

            self._mark_exchange_reconciled(adapter, snapshot)
            snapshot_audit = self.state.portfolio_risk.audit_snapshot(
                snapshot,
                max_open_risk_fraction=self.state.bot_settings.max_total_open_risk,
                max_exposure_fraction=self.state.bot_settings.max_portfolio_exposure,
                max_symbol_exposure_fraction=self.state.bot_settings.max_symbol_exposure,
                max_directional_exposure_fraction=self.state.bot_settings.max_directional_exposure,
                max_symbol_open_risk_fraction=self.state.bot_settings.max_symbol_open_risk,
            )
            await self.state.storage.save_portfolio_risk_audit(
                snapshot_audit.model_dump(mode="json")
            )
            open_position_count = len(snapshot.positions)
            active_symbols = self._busy_exchange_symbols(snapshot)
            portfolio_exposure_fraction = self._exchange_portfolio_exposure_fraction(snapshot)
            stop_actions = await adapter.manage_open_position_stops()
            if stop_actions:
                await self.state.storage.log(
                    "Auto-trader managed protective stops",
                    {"mode": self.state.trading_mode.value, "actions": stop_actions},
                    level="WARNING",
                )
            if open_position_count >= self.state.bot_settings.max_open_positions:
                return await self._skip(
                    "WAITING_POSITION",
                    f"Đã đủ {open_position_count}/{self.state.bot_settings.max_open_positions} vị thế trên exchange",
                )
        elif self.state.execution.open_positions():
            active_symbols = {position.symbol for position in self.state.execution.open_positions()}
            if open_position_count >= self.state.bot_settings.max_open_positions:
                return await self._skip("WAITING_POSITION", "Đã chạm số vị thế mô phỏng tối đa")

        self.last_status = "SCANNING"
        results = await self.state.scanner.scan(limit=40)
        for result in results:
            await self.state.storage.save_signal(result.model_dump(mode="json"))

        candidates = [item for item in results if item.action != SignalAction.NO_TRADE]
        if not candidates:
            return await self._skip("NO_SIGNAL", "Scanner chưa có tín hiệu đủ điểm")

        rejection_reasons: dict[str, int] = {}
        for result in candidates:
            if result.symbol in active_symbols:
                reason = "Symbol đang có vị thế hoặc lệnh mở"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                continue
            accepted, reason = self._candidate_has_enough_confirmation(result)
            if not accepted:
                self.rejected += 1
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                await self.state.storage.log(
                    "Auto-trader weak signal skip",
                    {
                        "symbol": result.symbol,
                        "reason": reason,
                        "timeframe": result.timeframe.value,
                    },
                    level="INFO",
                )
                continue
            if snapshot is not None and not await adapter.is_symbol_tradable(result.symbol):
                reason = "Symbol không thể giao dịch trên exchange"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                await self.state.storage.log(
                    "Auto-trader skip non-tradable symbol",
                    {"symbol": result.symbol, "mode": self.state.trading_mode.value},
                    level="INFO",
                )
                continue
            signal = self.state.scanner.signal_from_result(result)
            if signal is None:
                reason = "Không tạo được kế hoạch từ tín hiệu"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                continue
            correlated_positions = self._correlated_positions(signal.symbol, snapshot=snapshot)
            selected_leverage = self._select_leverage(signal, result)
            selected_risk_fraction = self._risk_fraction_for_candidate(
                result, correlated_positions=correlated_positions
            )
            signal = signal.model_copy(
                update={
                    "leverage": selected_leverage,
                    "risk_fraction": selected_risk_fraction,
                }
            )

            decision = self.state.risk.evaluate(
                signal,
                open_positions=open_position_count,
                daily_loss_fraction=self._daily_loss_fraction(),
                emergency_stop=self.state.emergency_stop,
                account_equity=account_equity,
                weekly_drawdown_fraction=self._weekly_drawdown_fraction(),
                portfolio_exposure_fraction=portfolio_exposure_fraction,
                correlated_positions=correlated_positions,
                loss_streak=self._loss_streak(),
                market_regime=result.regime,
                atr_fraction=(result.indicators.atr / result.price)
                if result.indicators.atr
                else None,
                data_age_seconds=max(0.0, (datetime.now(UTC) - result.scanned_at).total_seconds()),
                safe_mode=self.state.safe_mode,
                current_open_risk_fraction=self._current_open_risk_fraction(open_position_count),
                current_margin_fraction=(
                    self._exchange_margin_fraction(snapshot)
                    if snapshot is not None
                    else self._paper_margin_fraction()
                ),
            )
            if not decision.accepted or decision.quantity is None:
                self.rejected += 1
                reason = decision.reason or "Risk engine không chấp nhận"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                await self.state.storage.log(
                    "Auto-trader risk skip",
                    {"symbol": result.symbol, "reason": decision.reason},
                    level="INFO",
                )
                continue

            plan = OrderPlan(
                client_order_id=f"a-{self.state.trading_mode.value.lower()}-{signal.symbol}-{uuid4().hex[:8]}",
                symbol=signal.symbol,
                side=signal.side,
                quantity=self.state.position_sizer.apply(decision),
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                leverage=selected_leverage,
                order_type=signal.order_type,
                take_profits=signal.take_profits,
                risk_fraction=signal.risk_fraction,
            )
            try:
                self.state.order_validator.validate(plan)
            except ValueError as exc:
                self.rejected += 1
                reason = str(exc)
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                await self.state.storage.log(
                    "Auto-trader invalid plan",
                    {"symbol": result.symbol, "error": str(exc)},
                    level="WARNING",
                )
                continue

            if snapshot is not None:
                audit = self.state.portfolio_risk.evaluate_plan(
                    snapshot,
                    plan,
                    max_open_risk_fraction=self.state.bot_settings.max_total_open_risk,
                    max_exposure_fraction=self.state.bot_settings.max_portfolio_exposure,
                    max_symbol_exposure_fraction=self.state.bot_settings.max_symbol_exposure,
                    max_directional_exposure_fraction=self.state.bot_settings.max_directional_exposure,
                    max_symbol_open_risk_fraction=self.state.bot_settings.max_symbol_open_risk,
                )
                await self.state.storage.save_portfolio_risk_audit(audit.model_dump(mode="json"))
                await self.state.storage.log(
                    "Portfolio risk shadow pre-trade",
                    {
                        "symbol": plan.symbol,
                        "decision": audit.decision,
                        "reasons": audit.reasons,
                        "fingerprint": audit.fingerprint,
                        "enforcement_enabled": False,
                    },
                    level="WARNING" if audit.decision == "WOULD_REJECT" else "INFO",
                )

            return await self._submit(plan)

        return await self._skip(
            "NO_ACCEPTED_SIGNAL",
            self._rejection_summary(rejection_reasons),
        )

    async def _submit(self, plan: OrderPlan) -> dict[str, object]:
        self.last_status = "SUBMITTING"
        self.last_symbol = plan.symbol
        if self.state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            adapter = (
                self.state.live_exchange
                if self.state.trading_mode == TradingMode.LIVE
                else self.state.demo_exchange
            )
            try:
                result = await adapter.submit_order_plan(plan)
            except (ExchangeCredentialsError, ExchangeError) as exc:
                self.rejected += 1
                return await self._skip("ORDER_ERROR", f"{plan.symbol}: {exc}")
            await self._persist_exchange_result(plan, result)
            if result.critical_alert:
                self.state.enter_safe_mode(result.critical_alert)
                await self.state.storage.log(
                    result.critical_alert, result.model_dump(mode="json"), level="CRITICAL"
                )
            if result.accepted:
                self.submitted += 1
                self.last_action_at = datetime.now(UTC)
                self.last_status = "ORDER_SUBMITTED"
                self.last_reason = (
                    f"Đã vào {plan.symbol} {plan.side.value} trên {self.state.trading_mode.value}"
                )
                await self._notify_position_open(plan)
                await self.state.storage.log(
                    "Auto-trader submitted order", result.model_dump(mode="json"), level="WARNING"
                )
                return self.snapshot()
            self.rejected += 1
            return await self._skip(
                result.status, result.critical_alert or "Exchange không accept order"
            )

        before_fills = len(self.state.execution.fills)
        before_trades = len(self.state.execution.trades)
        result = await self.state.execution.submit_order_plan(plan)
        await self.state.storage.save_order_bundle(
            order=result["order"],  # type: ignore[arg-type]
            fills=[
                item.model_dump(mode="json") for item in self.state.execution.fills[before_fills:]
            ],
            positions=[item.model_dump(mode="json") for item in self.state.execution.positions],
            trades=[
                item.model_dump(mode="json") for item in self.state.execution.trades[before_trades:]
            ],
            performance=self.state.execution.performance().model_dump(mode="json"),
        )
        self.submitted += 1
        self.last_action_at = datetime.now(UTC)
        self.last_status = "ORDER_SUBMITTED"
        self.last_reason = f"Đã vào {plan.symbol} {plan.side.value} trên mô phỏng"
        await self._notify_position_open(plan)
        await self.state.storage.log("Auto-trader submitted paper order", result, level="WARNING")
        return self.snapshot()

    async def _persist_exchange_result(
        self, plan: OrderPlan, result: ExchangeExecutionResult
    ) -> None:
        if "DUPLICATE_ACK" in result.status:
            return
        await self.state.storage.save_order_bundle(
            order=result.order,
            fills=result.fills,
            positions=result.positions,
            trades=result.trades,
            performance=self.state.execution.performance().model_dump(mode="json"),
        )

    async def _notify_position_open(self, plan: OrderPlan) -> None:
        notification = self.state.notifications.build(
            NotificationEvent.POSITION_OPEN,
            title="Position open",
            body=f"{plan.symbol} {plan.side.value}",
            data={"client_order_id": plan.client_order_id, "mode": self.state.trading_mode.value},
        )
        await self.state.storage.log(
            "APNs-ready notification", notification.model_dump(mode="json"), level="INFO"
        )

    async def _skip(self, status: str, reason: str) -> dict[str, object]:
        self.last_status = status
        self.last_reason = reason
        await self.state.storage.log(
            "Auto-trader skip", {"status": status, "reason": reason}, level="INFO"
        )
        return self.snapshot()

    async def _clean_exchange_orphans(self, adapter: Any, snapshot: Any) -> tuple[Any, list[str]]:
        position_symbols = {position.symbol for position in snapshot.positions}
        order_symbols = {order.symbol for order in snapshot.orders}
        orphan_symbols = sorted(order_symbols - position_symbols)
        if not orphan_symbols:
            return snapshot, []

        canceled = 0
        for symbol in orphan_symbols:
            canceled += len(await adapter.cancel_all_orders(symbol))
        await self.state.storage.log(
            "Auto-trader cleaned orphan exchange orders",
            {
                "mode": self.state.trading_mode.value,
                "symbols": orphan_symbols,
                "canceled_symbols": canceled,
            },
            level="WARNING",
        )
        return await adapter.snapshot(), orphan_symbols

    @staticmethod
    def _busy_exchange_symbols(snapshot: Any) -> set[str]:
        return {position.symbol for position in snapshot.positions} | {
            order.symbol for order in snapshot.orders
        }

    @staticmethod
    def _unprotected_exchange_positions(snapshot: Any) -> list[str]:
        stop_orders_by_symbol: dict[str, list[Any]] = {}
        for order in snapshot.orders:
            if (
                not order.stop_price
                or "STOP" not in order.order_type
                or "TAKE_PROFIT" in order.order_type
            ):
                continue
            stop_orders_by_symbol.setdefault(order.symbol, []).append(order)

        unprotected: list[str] = []
        for position in snapshot.positions:
            stops = stop_orders_by_symbol.get(position.symbol, [])
            if not stops:
                unprotected.append(position.symbol)
                continue
            mark = position.mark_price or position.entry_price
            if position.side == "LONG":
                protects = any(
                    order.side == "SELL" and (order.stop_price or 0) < mark for order in stops
                )
            else:
                protects = any(
                    order.side == "BUY" and (order.stop_price or 0) > mark for order in stops
                )
            if not protects:
                unprotected.append(position.symbol)
        return sorted(set(unprotected))

    @staticmethod
    def _mark_exchange_reconciled(adapter: Any, snapshot: Any) -> None:
        snapshot.last_reconciled_at = datetime.now(UTC)
        adapter.snapshot_cache = snapshot

    def _live_allowed(self) -> bool:
        report = self.state.stability.last_report
        return (
            self.state.live_trading_enabled
            and all(self.state.live_preflight.values())
            and report is not None
            and report.verdict == "READY"
        )

    def _daily_loss_fraction(self) -> float:
        realized = self.state.execution.performance().realized_pnl
        if realized >= 0:
            return 0.0
        return abs(realized) / self.state.bot_settings.paper_initial_balance

    def _weekly_drawdown_fraction(self) -> float:
        performance = self.state.execution.performance()
        if self.state.bot_settings.paper_initial_balance <= 0:
            return 0.0
        return performance.max_drawdown / self.state.bot_settings.paper_initial_balance

    def _portfolio_exposure_fraction(self) -> float:
        equity = max(self.state.execution.performance().equity, 1.0)
        exposure = sum(
            position.remaining_quantity * position.entry_price
            for position in self.state.execution.open_positions()
        )
        return exposure / equity

    def _exchange_portfolio_exposure_fraction(self, snapshot: Any) -> float:
        equity = max(snapshot.balance.margin_balance or snapshot.balance.available, 1.0)
        exposure = sum(
            position.quantity * (position.mark_price or position.entry_price)
            for position in snapshot.positions
        )
        return exposure / equity

    def _current_open_risk_fraction(self, open_position_count: int) -> float:
        return open_position_count * self.state.bot_settings.risk_per_trade

    def _paper_margin_fraction(self) -> float:
        equity = max(self.state.execution.performance().equity, 1.0)
        leverage = max(self.state.bot_settings.max_leverage, 1)
        margin = sum(
            (position.remaining_quantity * position.entry_price) / leverage
            for position in self.state.execution.open_positions()
        )
        return margin / equity

    def _exchange_margin_fraction(self, snapshot: Any) -> float:
        equity = max(snapshot.balance.margin_balance or snapshot.balance.available, 1.0)
        margin = sum(
            (position.quantity * (position.mark_price or position.entry_price))
            / max(position.leverage or 1, 1)
            for position in snapshot.positions
        )
        return margin / equity

    def _correlated_positions(self, symbol: str, *, snapshot: Any | None = None) -> int:
        base = symbol.replace("USDT", "")
        bucket = "BTC_ETH" if base in {"BTC", "ETH"} else base[:3]
        if snapshot is not None:
            return sum(
                1
                for position in snapshot.positions
                if position.symbol.replace("USDT", "")[:3] == bucket[:3]
            )
        return sum(
            1
            for position in self.state.execution.open_positions()
            if position.symbol.replace("USDT", "")[:3] == bucket[:3]
        )

    def _select_leverage(self, signal: Any, result: Any) -> int:
        maximum = max(5, min(int(self.state.bot_settings.max_leverage), 10))
        atr_fraction = (result.indicators.atr / result.price) if result.indicators.atr else 0.02
        risk_reward = result.risk_reward or 0.0
        confidence = signal.confidence
        if confidence >= 0.85 and risk_reward >= 2.6 and atr_fraction <= 0.01:
            chosen = 10
        elif confidence >= 0.78 and risk_reward >= 2.2 and atr_fraction <= 0.015:
            chosen = 8
        else:
            chosen = 5
        return max(5, min(chosen, maximum))

    def _risk_fraction_for_candidate(self, result: Any, *, correlated_positions: int) -> float:
        score = max(result.long_score, result.short_score)
        if score >= 90 and (result.risk_reward or 0.0) >= 2.6:
            risk_fraction = min(0.0075, self.state.bot_settings.max_risk_per_trade)
        elif score >= 85:
            risk_fraction = min(0.005, self.state.bot_settings.risk_per_trade)
        else:
            risk_fraction = min(0.0035, self.state.bot_settings.risk_per_trade)
        if correlated_positions > 0:
            risk_fraction *= 0.5
        return max(0.001, risk_fraction)

    def _candidate_has_enough_confirmation(self, result: Any) -> tuple[bool, str]:
        score = max(result.long_score, result.short_score)
        reasons = set(result.reasons)
        if result.timeframe not in {Timeframe.M15, Timeframe.H1, Timeframe.H4}:
            return False, "Bỏ qua khung nhiễu 1m/5m"
        if score < 80:
            return False, "Score dưới 80 sau reset"
        if (result.risk_reward or 0.0) < 2.0:
            return False, "RR dưới 2.0 sau reset"
        if result.regime in {MarketRegime.HIGH_VOL, MarketRegime.PANIC}:
            return False, "Tránh vùng biến động cao/panic"
        if result.regime in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN}:
            return True, "Trend rõ"
        breakout = any(reason.startswith("Breakout") for reason in reasons)
        if breakout and "Volume tăng" in reasons and "ADX xác nhận trend" in reasons:
            return True, "Breakout có volume và ADX"
        return False, "Chưa đủ xác nhận trend/breakout"

    @staticmethod
    def _rejection_summary(reasons: dict[str, int]) -> str:
        if not reasons:
            return "Có tín hiệu nhưng chưa có tín hiệu phù hợp để vào lệnh"
        ranked = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        details = "; ".join(f"{reason} ({count})" for reason, count in ranked[:3])
        return f"Có tín hiệu nhưng chưa đủ điều kiện: {details}"

    def _loss_streak(self) -> int:
        streak = 0
        for trade in reversed(self.state.execution.trades):
            if trade.net_pnl < 0:
                streak += 1
            else:
                break
        return streak
