import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.domain.models import (
    BotState,
    ExchangeExecutionResult,
    NotificationEvent,
    OrderPlan,
    SignalAction,
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
        await self.state.storage.log("Auto-trader worker started", {"interval_seconds": self.interval_seconds})
        while self.running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - background worker must not die on one cycle
                self.last_status = "ERROR"
                self.last_reason = str(exc)
                await self.state.storage.log("Auto-trader cycle error", {"error": str(exc)}, level="ERROR")
            await asyncio.sleep(self.interval_seconds)

    async def run_once(self) -> dict[str, object]:
        self.cycles += 1
        self.last_run_at = datetime.now(UTC)

        if self.state.bot_state != BotState.RUNNING:
            return await self._skip("IDLE", f"Bot state {self.state.bot_state.value}, không auto-trade")
        if self.state.emergency_stop.active:
            return await self._skip("BLOCKED", "Emergency Stop đang bật")
        if self.state.safe_mode:
            return await self._skip("BLOCKED", self.state.safe_mode_reason or "SAFE_MODE đang bật")
        if self.state.trading_mode == TradingMode.LIVE and not self._live_allowed():
            return await self._skip("BLOCKED", "LIVE chưa pass readiness")

        snapshot = None
        account_equity = self.state.execution.performance().equity
        if self.state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            adapter = self.state.live_exchange if self.state.trading_mode == TradingMode.LIVE else self.state.demo_exchange
            try:
                snapshot = await adapter.snapshot()
                account_equity = max(snapshot.balance.available, 1.0)
            except (ExchangeCredentialsError, ExchangeError) as exc:
                self.rejected += 1
                return await self._skip("BLOCKED", f"Exchange snapshot lỗi: {exc}")
            if snapshot.orders or snapshot.positions:
                return await self._skip(
                    "WAITING_POSITION",
                    f"Đang có {len(snapshot.orders)} order và {len(snapshot.positions)} vị thế trên exchange",
                )
        elif self.state.execution.open_positions():
            return await self._skip("WAITING_POSITION", "PAPER đang có vị thế mở")

        self.last_status = "SCANNING"
        results = await self.state.scanner.scan(limit=40)
        for result in results:
            await self.state.storage.save_signal(result.model_dump(mode="json"))

        candidates = [item for item in results if item.action != SignalAction.NO_TRADE]
        if not candidates:
            return await self._skip("NO_SIGNAL", "Scanner chưa có tín hiệu đủ điểm")

        for result in candidates:
            signal = self.state.scanner.signal_from_result(result)
            if signal is None:
                continue
            signal = await self.state.ai.score(signal)
            if signal.metadata.get("ai_action") == "NO_TRADE":
                self.rejected += 1
                await self.state.storage.log("Auto-trader AI skip", {"symbol": result.symbol}, level="INFO")
                continue

            decision = self.state.risk.evaluate(
                signal,
                open_positions=len(self.state.execution.open_positions()),
                daily_loss_fraction=self._daily_loss_fraction(),
                emergency_stop=self.state.emergency_stop,
                account_equity=account_equity,
                weekly_drawdown_fraction=self._weekly_drawdown_fraction(),
                portfolio_exposure_fraction=self._portfolio_exposure_fraction(),
                correlated_positions=self._correlated_positions(signal.symbol),
                loss_streak=self._loss_streak(),
                market_regime=result.regime,
                atr_fraction=(result.indicators.atr / result.price) if result.indicators.atr else None,
                data_age_seconds=max(0.0, (datetime.now(UTC) - result.scanned_at).total_seconds()),
                safe_mode=self.state.safe_mode,
            )
            if not decision.accepted or decision.quantity is None:
                self.rejected += 1
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
                leverage=signal.leverage,
                order_type=signal.order_type,
                take_profits=signal.take_profits,
                risk_fraction=signal.risk_fraction,
            )
            try:
                self.state.order_validator.validate(plan)
            except ValueError as exc:
                self.rejected += 1
                await self.state.storage.log("Auto-trader invalid plan", {"symbol": result.symbol, "error": str(exc)}, level="WARNING")
                continue

            return await self._submit(plan)

        return await self._skip("NO_ACCEPTED_SIGNAL", "Có tín hiệu nhưng đều bị AI/risk guard chặn")

    async def _submit(self, plan: OrderPlan) -> dict[str, object]:
        self.last_status = "SUBMITTING"
        self.last_symbol = plan.symbol
        if self.state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            adapter = self.state.live_exchange if self.state.trading_mode == TradingMode.LIVE else self.state.demo_exchange
            try:
                result = await adapter.submit_order_plan(plan)
            except (ExchangeCredentialsError, ExchangeError) as exc:
                self.rejected += 1
                return await self._skip("ORDER_ERROR", f"{plan.symbol}: {exc}")
            await self._persist_exchange_result(plan, result)
            if result.critical_alert:
                self.state.enter_safe_mode(result.critical_alert)
                await self.state.storage.log(result.critical_alert, result.model_dump(mode="json"), level="CRITICAL")
            if result.accepted:
                self.submitted += 1
                self.last_action_at = datetime.now(UTC)
                self.last_status = "ORDER_SUBMITTED"
                self.last_reason = f"Đã vào {plan.symbol} {plan.side.value} trên {self.state.trading_mode.value}"
                await self._notify_position_open(plan)
                await self.state.storage.log("Auto-trader submitted order", result.model_dump(mode="json"), level="WARNING")
                return self.snapshot()
            self.rejected += 1
            return await self._skip(result.status, result.critical_alert or "Exchange không accept order")

        before_fills = len(self.state.execution.fills)
        before_trades = len(self.state.execution.trades)
        result = await self.state.execution.submit_order_plan(plan)
        await self.state.storage.save_order_bundle(
            order=result["order"],  # type: ignore[arg-type]
            fills=[item.model_dump(mode="json") for item in self.state.execution.fills[before_fills:]],
            positions=[item.model_dump(mode="json") for item in self.state.execution.positions],
            trades=[item.model_dump(mode="json") for item in self.state.execution.trades[before_trades:]],
            performance=self.state.execution.performance().model_dump(mode="json"),
        )
        self.submitted += 1
        self.last_action_at = datetime.now(UTC)
        self.last_status = "ORDER_SUBMITTED"
        self.last_reason = f"Đã vào {plan.symbol} {plan.side.value} trên PAPER"
        await self._notify_position_open(plan)
        await self.state.storage.log("Auto-trader submitted paper order", result, level="WARNING")
        return self.snapshot()

    async def _persist_exchange_result(self, plan: OrderPlan, result: ExchangeExecutionResult) -> None:
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
        await self.state.storage.log("APNs-ready notification", notification.model_dump(mode="json"), level="INFO")

    async def _skip(self, status: str, reason: str) -> dict[str, object]:
        self.last_status = status
        self.last_reason = reason
        await self.state.storage.log("Auto-trader skip", {"status": status, "reason": reason}, level="INFO")
        return self.snapshot()

    def _live_allowed(self) -> bool:
        return self.state.live_trading_enabled and all(self.state.live_preflight.values())

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

    def _correlated_positions(self, symbol: str) -> int:
        base = symbol.replace("USDT", "")
        bucket = "BTC_ETH" if base in {"BTC", "ETH"} else base[:3]
        return sum(
            1
            for position in self.state.execution.open_positions()
            if position.symbol.replace("USDT", "")[:3] == bucket[:3]
        )

    def _loss_streak(self) -> int:
        streak = 0
        for trade in reversed(self.state.execution.trades):
            if trade.net_pnl < 0:
                streak += 1
            else:
                break
        return streak
