import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import Settings
from app.domain.models import BotSettings, BotState, EmergencyStopState, TradingMode
from app.services.ai_shadow import AIShadowEvaluator
from app.services.analytics_history import AnalyticsHistoryCache
from app.services.auto_trader import AutoTrader
from app.services.backtest import BacktestService
from app.services.binance_client import BinanceMarketDataClient
from app.services.capital_risk import capital_risk_profile_for_mode
from app.services.equity import EquityTracker
from app.services.exchange import BinanceFuturesAdapter
from app.services.execution import ExecutionService
from app.services.monitoring import MonitoringService
from app.services.notifications import NotificationService
from app.services.order_pipeline import OrderValidator, PositionSizer
from app.services.portfolio_risk import PortfolioRiskEngine
from app.services.reconciliation import ExchangeReconciliationService
from app.services.risk_engine import RiskEngine
from app.services.scanner import FuturesScanner
from app.services.smart_entry import SmartEntryOutcomeCollector
from app.services.stability import DemoStabilityService
from app.services.storage import Storage
from app.services.telegram_alerts import TelegramAlertService
from app.services.user_stream import UserStreamWatchdog


def bot_settings_from_env(settings: Settings) -> BotSettings:
    return BotSettings(
        min_quote_volume=settings.scanner_min_quote_volume,
        max_spread_bps=settings.scanner_max_spread_bps,
        min_listing_age_days=settings.scanner_min_listing_age_days,
        min_score_to_trade=settings.scanner_min_score_to_trade,
        taker_fee_rate=settings.taker_fee_rate,
        maker_fee_rate=settings.maker_fee_rate,
        slippage_bps=settings.slippage_bps,
        funding_rate_per_8h=settings.funding_rate_per_8h,
        max_leverage=settings.max_leverage,
        # DEMO validation is deliberately capped even when stale env/runtime
        # values are more permissive.
        risk_per_trade=min(max(settings.risk_per_trade, 0.001), 0.0025),
        max_risk_per_trade=min(max(settings.max_risk_per_trade, 0.001), 0.0025),
        max_total_open_risk=min(settings.max_total_open_risk, 0.0025),
        max_margin_per_trade=settings.max_margin_per_trade,
        max_total_margin=settings.max_total_margin,
        max_daily_loss=settings.max_daily_loss,
        max_weekly_drawdown=settings.max_weekly_drawdown,
        max_open_positions=settings.max_open_positions,
        max_portfolio_exposure=settings.max_portfolio_exposure,
        max_symbol_exposure=settings.max_symbol_exposure,
        max_directional_exposure=settings.max_directional_exposure,
        max_symbol_open_risk=settings.max_symbol_open_risk,
        max_correlated_positions=settings.max_correlated_positions,
        max_loss_streak=settings.max_loss_streak,
        loss_streak_cooldown_minutes=settings.loss_streak_cooldown_minutes,
        extreme_volatility_atr_fraction=settings.extreme_volatility_atr_fraction,
        stale_data_seconds=settings.stale_data_seconds,
        minimum_risk_reward=settings.minimum_risk_reward,
    )


class AppState:
    def __init__(self, settings: Settings) -> None:
        bot_settings = bot_settings_from_env(settings)
        self.settings = settings
        self.bot_settings = bot_settings
        self.trading_mode = TradingMode(settings.trading_mode)
        self.live_trading_enabled = settings.live_trading_enabled
        self.portfolio_risk_enforcement_enabled = settings.portfolio_risk_enforcement_enabled
        self.live_preflight = {
            "all_tests_pass": settings.live_preflight_all_tests_pass,
            "demo_stable": settings.live_preflight_demo_stable,
            "sl_protection_pass": settings.live_preflight_sl_protection_pass,
            "reconnect_pass": settings.live_preflight_reconnect_pass,
            "reconciliation_pass": settings.live_preflight_reconciliation_pass,
            "duplicate_order_tests_pass": settings.live_preflight_duplicate_order_tests_pass,
        }
        self.performance_reset_at_by_mode: dict[TradingMode, datetime | None] = {
            TradingMode.DEMO: None,
            TradingMode.LIVE: None,
        }
        self.performance_initial_capital_by_mode: dict[TradingMode, float | None] = {
            TradingMode.DEMO: None,
            TradingMode.LIVE: None,
        }
        self.ai_shadow_config = {
            "enabled": settings.ai_evaluator_enabled,
            "model": settings.ai_model,
            "outcome_horizon": settings.ai_outcome_horizon,
            "minimum_training_samples": settings.ai_minimum_training_samples,
        }
        self.runtime_config_path = (
            Path(__file__).resolve().parents[3] / settings.runtime_config_path
        ).resolve()
        self._load_runtime_config()
        self.bot_state = BotState.STOPPED
        self.emergency_stop = EmergencyStopState(active=False, reason=None)
        self.market_client = BinanceMarketDataClient(settings.binance_base_url)
        self.scanner = FuturesScanner(self.market_client, bot_settings)
        self.telegram_alerts = TelegramAlertService(
            settings.telegram_bot_token,
            settings.telegram_alert_chat_id,
            context_provider=self._telegram_context,
        )
        self.notifications = NotificationService(telegram=self.telegram_alerts)
        self.monitoring = MonitoringService()
        self.execution = ExecutionService(bot_settings, notifications=self.notifications)
        self.backtest = BacktestService()
        self.position_sizer = PositionSizer()
        self.order_validator = OrderValidator()
        self.demo_exchange = BinanceFuturesAdapter(
            api_key=settings.binance_demo_api_key or settings.binance_api_key,
            api_secret=settings.binance_demo_api_secret or settings.binance_api_secret,
            base_url=settings.binance_demo_base_url,
            stream_url=settings.binance_demo_stream_url,
            mode=TradingMode.DEMO,
        )
        self.live_exchange = BinanceFuturesAdapter(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            base_url=settings.binance_base_url,
            stream_url="wss://fstream.binance.com",
            mode=TradingMode.LIVE,
        )
        self.portfolio_risk = PortfolioRiskEngine()
        self.risk = RiskEngine(
            max_leverage=settings.max_leverage,
            risk_per_trade=settings.risk_per_trade,
            max_risk_per_trade=settings.max_risk_per_trade,
            max_total_open_risk=settings.max_total_open_risk,
            max_margin_per_trade=settings.max_margin_per_trade,
            max_total_margin=settings.max_total_margin,
            max_daily_loss=settings.max_daily_loss,
            max_weekly_drawdown=settings.max_weekly_drawdown,
            max_open_positions=settings.max_open_positions,
            max_portfolio_exposure=settings.max_portfolio_exposure,
            max_correlated_positions=settings.max_correlated_positions,
            max_loss_streak=settings.max_loss_streak,
            extreme_volatility_atr_fraction=settings.extreme_volatility_atr_fraction,
            stale_data_seconds=settings.stale_data_seconds,
            minimum_risk_reward=max(settings.minimum_risk_reward, 2.0),
            taker_fee_rate=settings.taker_fee_rate,
            slippage_bps=settings.slippage_bps,
        )
        self.storage = Storage(settings.database_url)
        self.reconciliation = ExchangeReconciliationService(self.storage, self.execution)
        self.auto_trader = AutoTrader(self)
        self.user_stream = UserStreamWatchdog(self)
        self.stability = DemoStabilityService(self)
        self.smart_entry_collector = SmartEntryOutcomeCollector(self)
        self.ai_shadow_evaluator = AIShadowEvaluator(self)
        self.equity_tracker = EquityTracker(self)
        self.analytics_history = AnalyticsHistoryCache()

    @property
    def safe_mode(self) -> bool:
        return self._active_exchange().snapshot_cache.safe_mode

    @property
    def safe_mode_reason(self) -> str | None:
        return self._active_exchange().snapshot_cache.safe_mode_reason

    def enter_safe_mode(self, reason: str) -> None:
        self.bot_state = BotState.SAFE_MODE
        adapter = self._active_exchange()
        adapter.snapshot_cache.safe_mode = True
        adapter.snapshot_cache.safe_mode_reason = reason

    def clear_safe_mode_after_verified_reconciliation(self) -> None:
        """Unlock the safety latch only after an authoritative reconciliation.

        Recovery intentionally lands in PAUSED rather than RUNNING: an operator
        must explicitly start the bot again after a safety incident.
        """
        adapter = self._active_exchange()
        adapter.snapshot_cache.safe_mode = False
        adapter.snapshot_cache.safe_mode_reason = None
        if self.bot_state == BotState.SAFE_MODE:
            self.bot_state = BotState.PAUSED

    def _active_exchange(self) -> BinanceFuturesAdapter:
        return self.live_exchange if self.trading_mode == TradingMode.LIVE else self.demo_exchange

    def _telegram_context(self) -> dict[str, object]:
        """Capture one consistent operator-safety snapshot when an alert is queued."""
        snapshot = self._active_exchange().snapshot_cache
        return {
            "mode": self.trading_mode.value,
            "exchange": snapshot.connection.value,
            "bot_state": self.bot_state.value,
            "live_enabled": self.live_trading_enabled,
            "safe_mode": snapshot.safe_mode,
            "emergency_stop": self.emergency_stop.active,
        }

    async def handle_telegram_command(self, command: str, args: str = "") -> str:
        """Restricted operator commands for the allowlisted Telegram chat only."""
        adapter = self._active_exchange()
        snapshot = adapter.snapshot_cache
        if command in {"/help", "/start"}:
            return (
                "🤖 LỆNH AN TOÀN (chỉ đọc/khóa entry)\n"
                "/status — trạng thái DEMO/sàn/bot\n"
                "/positions — vị thế đang mở từ cache\n"
                "/risk — giới hạn risk hiện hành\n"
                "/pause — khóa entry mới\n"
                "/resume — chạy lại DEMO nếu an toàn\n"
                "/safe — trạng thái SAFE_MODE\n"
                "/report — tóm tắt hiệu suất\n"
                "\nKhông có từ Telegram: bật LIVE, reset SAFE_MODE, AI execution."
            )
        if command == "/status":
            mode = self.trading_mode.value
            mode_hint = {
                "DEMO": "không dùng vốn thật",
                "PAPER": "mô phỏng nội bộ",
                "LIVE": "vốn thật",
            }.get(mode, "cần kiểm tra")
            live_label = (
                "BẬT · có thể gửi lệnh" if self.live_trading_enabled else "TẮT · không gửi lệnh"
            )
            bot = self.bot_state.value
            bot_hint = {
                "STOPPED": "không phát lệnh",
                "RUNNING": "đang chạy",
                "PAUSED": "tạm dừng entry",
                "SAFE_MODE": "khóa entry",
            }.get(bot, "cần kiểm tra")
            exchange = snapshot.connection.value
            exchange_hint = {
                "CONNECTED": "đã kết nối",
                "DISCONNECTED": "chưa kết nối",
                "STALE": "dữ liệu cũ",
                "SAFE_MODE": "đang khóa",
            }.get(exchange, "cần kiểm tra")
            safe_mode = "BẬT" if snapshot.safe_mode else "TẮT"
            emergency_stop = "BẬT" if self.emergency_stop.active else "TẮT"
            return (
                "📊 TRẠNG THÁI\n"
                f"🔒 Phạm vi: {mode} · {mode_hint} · LIVE {live_label}\n"
                f"• Bot: {bot} · {bot_hint}\n"
                f"• Sàn: {exchange} · {exchange_hint}\n"
                f"• SAFE_MODE: {safe_mode}"
                + (f" — {snapshot.safe_mode_reason}" if snapshot.safe_mode_reason else "")
                + f"\n• Dừng khẩn cấp: {emergency_stop}"
                + (f" — {self.emergency_stop.reason}" if self.emergency_stop.reason else "")
                + f"\n• Vị thế: {len(snapshot.positions)} | Lệnh mở: {len(snapshot.orders)}"
                + "\n➡️ Telegram không bật LIVE / không điều khiển AI."
            )
        if command == "/positions":
            if not snapshot.positions:
                return "📌 VỊ THẾ\nKhông có vị thế mở trong exchange cache."
            return "📌 VỊ THẾ\n" + "\n".join(
                f"• {item.symbol} | Hướng: {item.side} | SL/TP: kiểm tra dashboard\n"
                f"  Khối lượng: {item.quantity:g} | Giá vào: {item.entry_price:g} | "
                f"Giá hiện tại: {(item.mark_price or item.entry_price):g} | "
                f"uPnL: {item.unrealized_pnl:g}"
                for item in snapshot.positions[:20]
            )
        if command == "/risk":
            equity = snapshot.balance.margin_balance or snapshot.balance.available or 0.0
            profile = capital_risk_profile_for_mode(
                equity, mode=self.trading_mode.value, settings=self.bot_settings
            )
            return (
                "🛡 GIỚI HẠN RỦI RO\n"
                f"• Profile: {profile.name}\n"
                f"• Equity: {equity:.2f} USDT\n"
                f"• Risk/lệnh: {profile.risk_per_trade * 100:.2f}%\n"
                f"• Số vị thế tối đa: {profile.max_open_positions}\n"
                f"• Đòn bẩy tối đa: {profile.max_leverage}x\n"
                f"• Exposure tối đa: {profile.max_portfolio_exposure * 100:.0f}%\n"
                f"• Ghi chú: {profile.reason}"
            )
        if command == "/pause":
            self.bot_state = BotState.PAUSED
            await self.storage.log(
                "Telegram command pause", {"args": args, "mode": self.trading_mode.value}
            )
            return "⏸ Đã khóa entry mới. Vị thế đang mở không bị đóng."
        if command == "/resume":
            if self.trading_mode == TradingMode.LIVE:
                return "Không resume LIVE qua Telegram. Dùng web/app có xác thực để bật LIVE."
            if self.safe_mode:
                return f"Không resume vì SAFE_MODE: {self.safe_mode_reason or 'unknown'}"
            if self.emergency_stop.active:
                return f"Không resume vì Emergency Stop: {self.emergency_stop.reason or 'active'}"
            self.bot_state = BotState.RUNNING
            await self.storage.log("Telegram command resume", {"mode": self.trading_mode.value})
            return "▶️ Đã resume DEMO bot. LIVE vẫn tắt."
        if command == "/safe":
            return (
                "🚨 SAFE_MODE đang BẬT: " + (self.safe_mode_reason or "không rõ lý do")
                if self.safe_mode
                else "✅ SAFE_MODE đang TẮT."
            )
        if command == "/report":
            report = await self.equity_tracker.analytics(self.trading_mode.value)
            return (
                f"📈 BÁO CÁO {self.trading_mode.value}\n"
                f"• Equity: {float(report.get('equity') or 0):.2f} USDT\n"
                f"• Return: {float(report.get('return_percent') or 0):.2f}%\n"
                f"• Max DD: {float(report.get('max_drawdown_percent') or 0):.2f}%\n"
                f"• Mẫu: {int(report.get('samples') or 0)}"
            )
        if command == "/reset_safe_mode":
            return "Reset SAFE_MODE phải làm trên web/app có kiểm tra vị thế và Face ID."
        return "Command chưa hỗ trợ. Gõ /help để xem danh sách lệnh an toàn."

    def performance_reset_at_for(self, mode: TradingMode | None = None) -> datetime | None:
        return self.performance_reset_at_by_mode.get(mode or self.trading_mode)

    def performance_initial_capital_for(self, mode: TradingMode | None = None) -> float | None:
        return self.performance_initial_capital_by_mode.get(mode or self.trading_mode)

    def set_performance_baseline(
        self, mode: TradingMode, reset_at: datetime, initial_capital: float
    ) -> None:
        self.performance_reset_at_by_mode[mode] = reset_at
        self.performance_initial_capital_by_mode[mode] = initial_capital

    def save_runtime_config(self) -> None:
        payload = {
            "trading_mode": self.trading_mode.value,
            "live_trading_enabled": self.live_trading_enabled,
            "live_preflight": self.live_preflight,
            "ai_shadow": {
                key: self.ai_shadow_config[key]
                for key in (
                    "enabled",
                    "model",
                    "outcome_horizon",
                    "minimum_training_samples",
                )
            },
            "performance": {
                mode.value: {
                    "reset_at": self.performance_reset_at_for(mode).isoformat()
                    if self.performance_reset_at_for(mode)
                    else None,
                    "initial_capital": self.performance_initial_capital_for(mode),
                }
                for mode in (TradingMode.DEMO, TradingMode.LIVE)
            },
        }
        self.runtime_config_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _load_runtime_config(self) -> None:
        if not self.runtime_config_path.exists():
            return
        try:
            payload = json.loads(self.runtime_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        mode = payload.get("trading_mode")
        if mode in {item.value for item in TradingMode}:
            self.trading_mode = TradingMode(mode)
        if isinstance(payload.get("live_trading_enabled"), bool):
            self.live_trading_enabled = payload["live_trading_enabled"]
        preflight = payload.get("live_preflight")
        if isinstance(preflight, dict):
            for key in self.live_preflight:
                if isinstance(preflight.get(key), bool):
                    self.live_preflight[key] = preflight[key]
        ai_shadow = payload.get("ai_shadow")
        if isinstance(ai_shadow, dict):
            if isinstance(ai_shadow.get("enabled"), bool):
                self.ai_shadow_config["enabled"] = ai_shadow["enabled"]
            if isinstance(ai_shadow.get("model"), str) and ai_shadow["model"].strip():
                self.ai_shadow_config["model"] = ai_shadow["model"].strip()[:120]
            horizon = ai_shadow.get("outcome_horizon")
            if isinstance(horizon, int) and not isinstance(horizon, bool) and 4 <= horizon <= 96:
                self.ai_shadow_config["outcome_horizon"] = horizon
            samples = ai_shadow.get("minimum_training_samples")
            if (
                isinstance(samples, int)
                and not isinstance(samples, bool)
                and 50 <= samples <= 10000
            ):
                self.ai_shadow_config["minimum_training_samples"] = samples
        performance = payload.get("performance")
        if isinstance(performance, dict):
            for performance_mode in (TradingMode.DEMO, TradingMode.LIVE):
                item = performance.get(performance_mode.value)
                if not isinstance(item, dict):
                    continue
                reset_at = item.get("reset_at")
                if isinstance(reset_at, str):
                    try:
                        parsed = datetime.fromisoformat(reset_at)
                        self.performance_reset_at_by_mode[performance_mode] = (
                            parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                        )
                    except ValueError:
                        pass
                initial_capital = item.get("initial_capital")
                if isinstance(initial_capital, (int, float)):
                    self.performance_initial_capital_by_mode[performance_mode] = float(
                        initial_capital
                    )
        else:
            # Legacy timestamp belonged to the active environment only.
            reset_at = payload.get("performance_reset_at")
            if isinstance(reset_at, str):
                try:
                    parsed = datetime.fromisoformat(reset_at)
                    self.performance_reset_at_by_mode[self.trading_mode] = (
                        parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                    )
                except ValueError:
                    pass


state = AppState(Settings())
