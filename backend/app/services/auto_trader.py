import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

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
from app.services.capital_risk import (
    CapitalRiskProfile,
    capital_risk_profile_for_mode,
)
from app.services.exchange import ExchangeCredentialsError, ExchangeError
from app.services.risk_engine import RiskEngine
from app.services.smart_entry import SmartEntryAnalytics


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
        self.data_quality_blocked = 0
        self.last_data_quality: dict[str, object] | None = None
        self.active_capital_profile: CapitalRiskProfile | None = None
        self._cycle_lock = asyncio.Lock()

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
            "data_quality_blocked": self.data_quality_blocked,
            "last_data_quality": self.last_data_quality,
            "capital_risk": self.active_capital_profile.snapshot()
            if self.active_capital_profile
            else None,
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
        """Chỉ cho phép một trading cycle chạy trong mỗi process."""
        if self._cycle_lock.locked():
            return await self._skip("BUSY", "Một vòng auto-trade khác đang chạy")
        async with self._cycle_lock:
            return await self._run_once_locked()

    async def _run_once_locked(self) -> dict[str, object]:
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
        profile = self._capital_profile(account_equity)
        self.active_capital_profile = profile
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
                profile = self._capital_profile(account_equity)
                self.active_capital_profile = profile
            except (ExchangeCredentialsError, ExchangeError) as exc:
                self.rejected += 1
                return await self._skip("BLOCKED", f"Exchange snapshot lỗi: {exc}")
            snapshot, orphan_symbols = await self._clean_exchange_orphans(adapter, snapshot)
            if orphan_symbols:
                return await self._skip(
                    "CLEANED_ORPHAN_ORDERS",
                    f"Đã hủy order mồ côi cho {', '.join(orphan_symbols)}; chờ chu kỳ sau mới xét lệnh mới",
                )
            unprotected_symbols = set(adapter.unprotected_bot_positions(snapshot))
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
                        unprotected_symbols = set(adapter.unprotected_bot_positions(snapshot))
                except Exception as exc:  # noqa: BLE001 - watchdog vẫn phải khóa an toàn
                    await self.state.storage.log(
                        "Phục hồi Stop Loss thất bại", {"error": str(exc)}, level="ERROR"
                    )
            if unprotected_symbols:
                try:
                    closed = await adapter.close_unprotected_bot_positions(
                        snapshot, set(unprotected_symbols)
                    )
                except Exception as exc:  # noqa: BLE001 - giữ watchdog ở trạng thái fail-closed
                    closed = []
                    await self.state.storage.log(
                        "Đóng vị thế thiếu Stop Loss thất bại",
                        {"error": str(exc), "symbols": unprotected_symbols},
                        level="CRITICAL",
                    )
                if closed:
                    await self.state.storage.log(
                        "Đã đóng vị thế bot không còn Stop Loss",
                        {"mode": self.state.trading_mode.value, "actions": closed},
                        level="CRITICAL",
                    )
                    snapshot = await adapter.snapshot()
                    unprotected_symbols = set(adapter.unprotected_bot_positions(snapshot))
                reason = f"SAFE_MODE: vị thế không có SL bảo vệ: {', '.join(sorted(unprotected_symbols))}"
                self.state.enter_safe_mode(reason)
                await self.state.storage.log(
                    "Auto-trader protection watchdog entered safe mode",
                    {"mode": self.state.trading_mode.value, "symbols": unprotected_symbols},
                    level="CRITICAL",
                )
                return await self._skip("BLOCKED", reason)

            self._mark_exchange_reconciled(adapter, snapshot)
            correlation_limits = await self._correlation_limits(snapshot)
            snapshot_audit = self.state.portfolio_risk.audit_snapshot(
                snapshot,
                max_open_risk_fraction=min(
                    self.state.bot_settings.max_total_open_risk,
                    profile.max_risk_per_trade * profile.max_open_positions,
                ),
                max_exposure_fraction=min(
                    self.state.bot_settings.max_portfolio_exposure,
                    profile.max_portfolio_exposure,
                ),
                max_symbol_exposure_fraction=self.state.bot_settings.max_symbol_exposure,
                max_directional_exposure_fraction=self.state.bot_settings.max_directional_exposure,
                max_symbol_open_risk_fraction=self.state.bot_settings.max_symbol_open_risk,
                **correlation_limits,
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
            if open_position_count >= profile.max_open_positions:
                return await self._skip(
                    "WAITING_POSITION",
                    f"Đã đủ {open_position_count}/{profile.max_open_positions} vị thế trên exchange",
                )
        elif self.state.execution.open_positions():
            active_symbols = {position.symbol for position in self.state.execution.open_positions()}
            if open_position_count >= profile.max_open_positions:
                return await self._skip("WAITING_POSITION", "Đã chạm số vị thế mô phỏng tối đa")

        if self.state.trading_mode == TradingMode.LIVE and not profile.live_allowed:
            return await self._skip("BLOCKED", profile.reason)
        effective_risk = self._effective_risk_engine(profile)
        if open_position_count >= profile.max_open_positions:
            return await self._skip(
                "WAITING_POSITION",
                f"Đã đủ {open_position_count}/{profile.max_open_positions} vị thế theo {profile.name}",
            )

        self.last_status = "SCANNING"
        results = await self.state.scanner.scan(
            limit=self.state.bot_settings.max_scan_symbols,
            timeframes=[Timeframe.M15, Timeframe.H1, Timeframe.H4],
        )
        for result in results:
            await self.state.storage.save_signal(result.model_dump(mode="json"))

        candidates = self._mtf_candidates(results)
        mtf_rejections = candidates[1]
        candidates = candidates[0]
        # Candidate telemetry only. Tasks are never awaited or read by the trading path.
        evaluator = getattr(self.state, "ai_shadow_evaluator", None)
        if evaluator is not None:
            for result in candidates:
                task = asyncio.create_task(evaluator.evaluate_and_log(result))
                task.add_done_callback(self._shadow_task_done)
        # Smart Entry is a write-behind audit trail. An analytics database issue
        # must never delay, reject, or submit an actual order. Its task has no
        # result consumed by the execution path below.
        for result in candidates:
            task = asyncio.create_task(self._record_smart_entry_evidence(result))
            task.add_done_callback(self._shadow_task_done)
        if not candidates:
            return await self._skip("NO_SIGNAL", "Scanner chưa có tín hiệu đủ điểm")

        rejection_reasons: dict[str, int] = dict(mtf_rejections)
        for result in candidates:
            if result.symbol in active_symbols:
                reason = "Symbol đang có vị thế hoặc lệnh mở"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                continue
            quality = result.data_quality
            self.last_data_quality = quality.model_dump(mode="json") if quality else None
            if quality is None or not quality.accepted:
                self.rejected += 1
                self.data_quality_blocked += 1
                details = ", ".join(quality.reasons) if quality else "thiếu bằng chứng chất lượng"
                reason = f"Data-quality gate chặn: {details}"
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                await self.state.storage.log(
                    "Auto-trader data-quality gate blocked candidate",
                    {
                        "symbol": result.symbol,
                        "timeframe": result.timeframe.value,
                        "assessment": quality.model_dump(mode="json") if quality else None,
                    },
                    level="WARNING",
                )
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
            selected_leverage = self._select_leverage(signal, result, profile=profile)
            selected_risk_fraction = self._risk_fraction_for_candidate(
                result, correlated_positions=correlated_positions, profile=profile
            )
            signal = signal.model_copy(
                update={
                    "leverage": selected_leverage,
                    "risk_fraction": selected_risk_fraction,
                }
            )

            decision = effective_risk.evaluate(
                signal,
                open_positions=open_position_count,
                daily_loss_fraction=self._daily_loss_fraction(),
                emergency_stop=self.state.emergency_stop,
                account_equity=account_equity,
                weekly_drawdown_fraction=self._weekly_drawdown_fraction(),
                portfolio_exposure_fraction=portfolio_exposure_fraction,
                correlated_positions=correlated_positions,
                loss_streak=self._loss_streak(result.symbol),
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
                    else self._simulation_margin_fraction()
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
                correlation_limits = await self._correlation_limits(
                    snapshot, candidate_symbol=plan.symbol
                )
                audit = self.state.portfolio_risk.evaluate_plan(
                    snapshot,
                    plan,
                    max_open_risk_fraction=min(
                        self.state.bot_settings.max_total_open_risk,
                        profile.max_risk_per_trade * profile.max_open_positions,
                    ),
                    max_exposure_fraction=min(
                        self.state.bot_settings.max_portfolio_exposure,
                        profile.max_portfolio_exposure,
                    ),
                    max_symbol_exposure_fraction=self.state.bot_settings.max_symbol_exposure,
                    max_directional_exposure_fraction=self.state.bot_settings.max_directional_exposure,
                    max_symbol_open_risk_fraction=self.state.bot_settings.max_symbol_open_risk,
                    **correlation_limits,
                )
                await self.state.storage.save_portfolio_risk_audit(audit.model_dump(mode="json"))
                enforcement_enabled = self.state.portfolio_risk_enforcement_enabled
                await self.state.storage.log(
                    "Portfolio risk pre-trade",
                    {
                        "symbol": plan.symbol,
                        "decision": audit.decision,
                        "reasons": audit.reasons,
                        "fingerprint": audit.fingerprint,
                        "enforcement_enabled": enforcement_enabled,
                    },
                    level="WARNING" if audit.decision == "WOULD_REJECT" else "INFO",
                )
                rejection = self._portfolio_risk_rejection(audit)
                if rejection:
                    self.rejected += 1
                    rejection_reasons[rejection] = rejection_reasons.get(rejection, 0) + 1
                    continue

            return await self._submit(plan, timeframe=result.timeframe.value)

        return await self._skip(
            "NO_ACCEPTED_SIGNAL",
            self._rejection_summary(rejection_reasons),
        )

    def _portfolio_risk_rejection(self, audit: Any) -> str | None:
        """Return a fail-closed reason only when enforcement is explicitly enabled."""
        if not self.state.portfolio_risk_enforcement_enabled:
            return None
        if audit.decision != "WOULD_ALLOW":
            return "; ".join(audit.reasons) or "Portfolio risk từ chối entry mới"
        return None

    async def _submit(self, plan: OrderPlan, *, timeframe: str) -> dict[str, object]:
        self.last_status = "SUBMITTING"
        self.last_symbol = plan.symbol
        if (
            self.state.bot_settings.universe_mode == "VALIDATION"
            and plan.symbol not in self.state.bot_settings.whitelist
        ) or plan.symbol in self.state.bot_settings.blacklist:
            self.rejected += 1
            return await self._skip(
                "SYMBOL_NOT_ALLOWED",
                f"{plan.symbol} không nằm trong universe được phép giao dịch",
            )
        if self.state.trading_mode in {TradingMode.DEMO, TradingMode.LIVE}:
            adapter = (
                self.state.live_exchange
                if self.state.trading_mode == TradingMode.LIVE
                else self.state.demo_exchange
            )
            try:
                # Refresh immediately before submit. This closes the stale-snapshot
                # window and fail-closes whenever any position already exists.
                latest_snapshot = await adapter.snapshot()
                if latest_snapshot.positions:
                    self.rejected += 1
                    return await self._skip(
                        "WAITING_POSITION",
                        "Chỉ cho phép tối đa 1 vị thế đang mở",
                    )
                result = await adapter.submit_order_plan(plan)
            except (ExchangeCredentialsError, ExchangeError) as exc:
                self.rejected += 1
                return await self._skip("ORDER_ERROR", f"{plan.symbol}: {exc}")
            await self._persist_exchange_result(plan, result)
            if result.accepted:
                await self._record_lifecycle_open(plan, result, timeframe=timeframe)
            if result.critical_alert:
                self.state.enter_safe_mode(result.critical_alert)
                await self.state.notifications.alert(
                    NotificationEvent.SAFE_MODE,
                    title="SAFE_MODE",
                    body=result.critical_alert,
                    data={
                        "mode": self.state.trading_mode.value,
                        "symbol": plan.symbol,
                        "client_order_id": result.client_order_id,
                    },
                )
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

        if self.state.execution.open_positions():
            self.rejected += 1
            return await self._skip(
                "WAITING_POSITION",
                "Chỉ cho phép tối đa 1 vị thế mô phỏng đang mở",
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
        await self.state.storage.log(
            "Auto-trader submitted simulated order", result, level="WARNING"
        )
        return self.snapshot()

    async def _correlation_limits(
        self, snapshot: Any, *, candidate_symbol: str | None = None
    ) -> dict[str, Any]:
        """Collect bounded closed-candle evidence for shadow audits only."""
        symbols = {item.symbol for item in snapshot.positions}
        if candidate_symbol:
            symbols.add(candidate_symbol)
        lookback = 60
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        closed_at = now_ms - (now_ms % 900_000)
        candles: dict[str, list[Any]] = {}
        for symbol in sorted(symbols):
            try:
                candles[symbol] = await self.state.market_client.closed_klines(
                    symbol, "15m", limit=lookback + 1, end_time=closed_at
                )
            except (ValueError, httpx.HTTPError):
                candles[symbol] = []
        return {
            "correlation_candles": candles,
            "correlation_lookback": lookback,
            "correlation_closed_at": closed_at,
        }

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

    async def _record_lifecycle_open(
        self,
        plan: OrderPlan,
        result: ExchangeExecutionResult,
        *,
        timeframe: str,
    ) -> None:
        raw_order = result.order.get("raw")
        raw_order = raw_order if isinstance(raw_order, dict) else {}
        exchange_time_ms = int(
            raw_order.get("updateTime")
            or raw_order.get("transactTime")
            or raw_order.get("time")
            or 0
        )
        event_at = (
            datetime.fromtimestamp(exchange_time_ms / 1000, UTC) if exchange_time_ms > 0 else None
        )
        entry_price = float(
            raw_order.get("avgPrice")
            or result.order.get("avg_price")
            or result.order.get("price")
            or 0
        )
        executed_quantity = float(
            result.order.get("executed_quantity") or raw_order.get("executedQty") or 0
        )
        initial_risk = abs(entry_price - plan.stop_loss) * executed_quantity
        evidence_verifiable = event_at is not None and entry_price > 0 and executed_quantity > 0
        await self.state.storage.save_lifecycle_analytics_event(
            {
                "event_key": f"{self.state.trading_mode.value}:{plan.client_order_id}:OPEN",
                "mode": self.state.trading_mode.value,
                "lifecycle_id": plan.client_order_id,
                "symbol": plan.symbol,
                "event_type": "OPEN",
                "event_at": event_at.isoformat() if event_at else datetime.now(UTC).isoformat(),
                "entry_timestamp_verifiable": event_at is not None,
                "side": plan.side.value,
                "entry_price": entry_price,
                "initial_quantity": executed_quantity or plan.quantity,
                "initial_stop_loss": plan.stop_loss,
                "initial_risk": initial_risk,
                "risk_verifiable": evidence_verifiable and initial_risk > 0,
                "timeframe": timeframe,
                "take_profits": plan.take_profits,
                "entry_order_id": result.order.get("order_id"),
                "entry_client_order_id": plan.client_order_id,
                "source": "ORDER_PLAN_ACCEPTED",
            }
        )

    async def _notify_position_open(self, plan: OrderPlan) -> None:
        notification = await self.state.notifications.alert(
            NotificationEvent.POSITION_OPEN,
            title="Mở vị thế",
            body=f"{plan.symbol} {plan.side.value}",
            data={
                "client_order_id": plan.client_order_id,
                "mode": self.state.trading_mode.value,
                "symbol": plan.symbol,
                "side": plan.side.value,
                "quantity": plan.quantity,
                "entry_price": plan.entry_price,
                "stop_loss": plan.stop_loss,
                "take_profits": plan.take_profits,
            },
        )
        await self.state.storage.log(
            "APNs-ready notification", notification.model_dump(mode="json"), level="INFO"
        )

    @staticmethod
    def _shadow_task_done(task: asyncio.Task[None]) -> None:
        # Consume failures so a provider outage cannot affect the auto-trader.
        if not task.cancelled():
            task.exception()

    async def _record_smart_entry_evidence(self, result: Any) -> None:
        """Best-effort, audit-only persistence kept outside the order path."""
        try:
            evidence = SmartEntryAnalytics.evaluate(result, mode=self.state.trading_mode.value)
            await self.state.storage.save_smart_entry_event(evidence)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - audit failure must be execution-neutral
            try:
                await self.state.storage.log(
                    "Smart Entry shadow evidence not saved",
                    {"error": str(exc), "shadow_only": True},
                    level="WARNING",
                )
            except Exception:  # noqa: BLE001 - logging is also non-critical here
                return

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
        return abs(realized) / self.state.bot_settings.simulation_initial_balance

    def _weekly_drawdown_fraction(self) -> float:
        performance = self.state.execution.performance()
        if self.state.bot_settings.simulation_initial_balance <= 0:
            return 0.0
        return performance.max_drawdown / self.state.bot_settings.simulation_initial_balance

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
        risk = (
            self.active_capital_profile.risk_per_trade
            if self.active_capital_profile
            else self.state.bot_settings.risk_per_trade
        )
        return open_position_count * risk

    def _simulation_margin_fraction(self) -> float:
        equity = max(self.state.execution.performance().equity, 1.0)
        margin = sum(
            (position.remaining_quantity * position.entry_price)
            / max(getattr(position, "leverage", None) or 1, 1)
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

    def _select_leverage(
        self, signal: Any, result: Any, *, profile: CapitalRiskProfile | None = None
    ) -> int:
        maximum = (
            profile.max_leverage if profile else min(int(self.state.bot_settings.max_leverage), 10)
        )
        atr_fraction = (result.indicators.atr / result.price) if result.indicators.atr else 0.02
        risk_reward = result.risk_reward or 0.0
        confidence = signal.confidence
        if confidence >= 0.85 and risk_reward >= 2.6 and atr_fraction <= 0.01:
            chosen = 10
        elif confidence >= 0.78 and risk_reward >= 2.2 and atr_fraction <= 0.015:
            chosen = 8
        else:
            chosen = 5
        return max(1, min(chosen, maximum))

    def _risk_fraction_for_candidate(
        self, result: Any, *, correlated_positions: int, profile: CapitalRiskProfile | None = None
    ) -> float:
        target = profile.risk_per_trade if profile else self.state.bot_settings.risk_per_trade
        maximum = (
            profile.max_risk_per_trade if profile else self.state.bot_settings.max_risk_per_trade
        )
        risk_fraction = min(target, maximum)
        if self.state.trading_mode == TradingMode.DEMO:
            risk_fraction = min(max(risk_fraction, 0.001), 0.0025)
        if max(result.long_score, result.short_score) < 85:
            risk_fraction = min(risk_fraction, 0.0025)
        if correlated_positions > 0:
            risk_fraction *= 0.5
        return max(0.001, risk_fraction)

    def _effective_risk_engine(self, profile: CapitalRiskProfile) -> RiskEngine:
        settings = self.state.bot_settings
        return RiskEngine(
            max_leverage=profile.max_leverage,
            risk_per_trade=profile.risk_per_trade,
            max_risk_per_trade=profile.max_risk_per_trade,
            max_total_open_risk=min(
                settings.max_total_open_risk,
                profile.max_risk_per_trade * profile.max_open_positions,
            ),
            max_margin_per_trade=profile.max_margin_per_trade,
            max_total_margin=profile.max_total_margin,
            max_daily_loss=profile.max_daily_loss,
            max_weekly_drawdown=profile.max_weekly_drawdown,
            max_open_positions=profile.max_open_positions,
            max_portfolio_exposure=min(
                settings.max_portfolio_exposure, profile.max_portfolio_exposure
            ),
            max_correlated_positions=settings.max_correlated_positions,
            max_loss_streak=settings.max_loss_streak,
            extreme_volatility_atr_fraction=settings.extreme_volatility_atr_fraction,
            stale_data_seconds=settings.stale_data_seconds,
            minimum_risk_reward=max(settings.minimum_risk_reward, 2.0),
            taker_fee_rate=settings.taker_fee_rate,
            slippage_bps=settings.slippage_bps,
        )

    def _capital_profile(self, account_equity: float) -> CapitalRiskProfile:
        return capital_risk_profile_for_mode(
            account_equity,
            mode=self.state.trading_mode.value,
            settings=self.state.bot_settings,
        )

    def _candidate_has_enough_confirmation(self, result: Any) -> tuple[bool, str]:
        score = max(result.long_score, result.short_score)
        reasons = set(result.reasons)
        if result.timeframe not in {Timeframe.M15, Timeframe.H1, Timeframe.H4}:
            return False, "Bỏ qua khung nhiễu 1m/5m"
        minimum_score = max(85, self.state.bot_settings.min_score_to_trade)
        high_risk_symbols = {
            symbol.strip().upper()
            for symbol in self.state.settings.scanner_high_risk_symbols.split(",")
            if symbol.strip()
        }
        if result.symbol.upper() in high_risk_symbols:
            minimum_score = max(minimum_score, self.state.settings.scanner_high_risk_min_score)
        if score < minimum_score:
            return False, f"Score dưới {minimum_score} sau reset"
        minimum_risk_reward = getattr(self.state.bot_settings, "minimum_risk_reward", 2.0)
        if (result.risk_reward or 0.0) < minimum_risk_reward:
            return False, f"RR dưới {minimum_risk_reward:.1f} sau phí/đệm"
        if result.regime in {MarketRegime.HIGH_VOL, MarketRegime.PANIC}:
            return False, "Tránh vùng biến động cao/panic"
        indicators = getattr(result, "indicators", None)
        atr = getattr(indicators, "atr", 0.0) or 0.0
        ema20 = getattr(indicators, "ema20", None)
        price = getattr(result, "price", None)
        if price is not None and ema20 and atr and abs(price - ema20) / atr > 2.0:
            return False, "Giá chạy quá xa EMA20 (>2 ATR)"
        if result.regime in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN}:
            return True, "Trend rõ"
        breakout = any(reason.startswith("Breakout") for reason in reasons)
        if breakout and "Volume tăng" in reasons and "ADX xác nhận trend" in reasons:
            return True, "Breakout có volume và ADX"
        return False, "Chưa đủ xác nhận trend/breakout"

    def _mtf_candidates(self, results: list[Any]) -> tuple[list[Any], dict[str, int]]:
        """Use 4h for regime, 1h for setup confirmation, and 15m only as entry trigger.

        This intentionally fails closed: a missing, neutral, or contradictory higher
        timeframe cannot be compensated for by a strong 15m score.
        """
        by_symbol_frame = {(item.symbol, item.timeframe): item for item in results}
        accepted: list[Any] = []
        rejected: dict[str, int] = {}
        for trigger in results:
            if trigger.timeframe != Timeframe.M15 or trigger.action == SignalAction.NO_TRADE:
                continue
            h1 = by_symbol_frame.get((trigger.symbol, Timeframe.H1))
            h4 = by_symbol_frame.get((trigger.symbol, Timeframe.H4))
            if h1 is None or h4 is None:
                reason = "Thiếu nến đóng xác nhận 1h/4h"
            elif h4.regime in {MarketRegime.HIGH_VOL, MarketRegime.PANIC}:
                reason = "4h volatility cao/panic"
            elif h4.regime not in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN}:
                reason = "4h không có xu hướng rõ"
            elif h1.regime in {MarketRegime.HIGH_VOL, MarketRegime.PANIC}:
                reason = "1h volatility cao/panic"
            elif h1.regime != h4.regime:
                reason = "1h không xác nhận xu hướng 4h"
            elif h1.action != trigger.action or trigger.action != self._regime_action(h4.regime):
                reason = "15m/1h/4h không cùng chiều"
            elif not self._is_h1_pullback_or_breakout(h1):
                reason = "1h chưa có vùng pullback/breakout hợp lệ"
            else:
                atr = trigger.indicators.atr or 0.0
                ema20 = trigger.indicators.ema20
                if ema20 and atr and abs(trigger.price - ema20) / atr > 2.0:
                    reason = "15m chạy quá xa EMA20 (>2 ATR)"
                elif atr / max(trigger.price, 1e-12) > (
                    self.state.bot_settings.extreme_volatility_atr_fraction
                ):
                    reason = "15m volatility vượt ngưỡng ATR"
                else:
                    accepted.append(trigger)
                    continue
            rejected[reason] = rejected.get(reason, 0) + 1
        return accepted, rejected

    @staticmethod
    def _regime_action(regime: MarketRegime) -> SignalAction:
        if regime == MarketRegime.TRENDING_UP:
            return SignalAction.LONG
        if regime == MarketRegime.TRENDING_DOWN:
            return SignalAction.SHORT
        return SignalAction.NO_TRADE

    @staticmethod
    def _is_h1_pullback_or_breakout(result: Any) -> bool:
        strategy = (getattr(result, "strategy", None) or "").lower()
        reasons = {reason.lower() for reason in getattr(result, "reasons", [])}
        pullback = "pullback" in strategy
        breakout = "breakout" in strategy or any("breakout" in reason for reason in reasons)
        return pullback or breakout

    @staticmethod
    def _rejection_summary(reasons: dict[str, int]) -> str:
        if not reasons:
            return "Có tín hiệu nhưng chưa có tín hiệu phù hợp để vào lệnh"
        ranked = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        details = "; ".join(f"{reason} ({count})" for reason, count in ranked[:3])
        return f"Có tín hiệu nhưng chưa đủ điều kiện: {details}"

    def _loss_streak(self, symbol: str | None = None) -> int:
        """Count losing lifecycles, scoped to the candidate symbol when supplied."""
        lifecycle_pnl: list[tuple[float, datetime]] = []
        lifecycle_key: tuple[object, ...] | None = None
        for trade in self.state.execution.trades:
            if symbol is not None and trade.symbol != symbol:
                continue
            key = (trade.symbol, trade.side, trade.created_at)
            if key != lifecycle_key:
                lifecycle_pnl.append((trade.net_pnl, trade.created_at))
                lifecycle_key = key
            else:
                pnl, created_at = lifecycle_pnl[-1]
                lifecycle_pnl[-1] = (pnl + trade.net_pnl, created_at)
        streak = 0
        latest_loss_at: datetime | None = None
        for net_pnl, created_at in reversed(lifecycle_pnl):
            if net_pnl >= 0:
                break
            latest_loss_at = latest_loss_at or created_at
            streak += 1
        settings = getattr(self.state, "bot_settings", None)
        if latest_loss_at is None or settings is None:
            return streak
        cooldown_seconds = settings.loss_streak_cooldown_minutes * 60
        if (datetime.now(UTC) - latest_loss_at).total_seconds() >= cooldown_seconds:
            return 0
        return min(streak, settings.max_loss_streak)
