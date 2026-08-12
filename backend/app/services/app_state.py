import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import Settings
from app.domain.models import BotSettings, BotState, EmergencyStopState, TradingMode
from app.services.ai_evaluator import AiEvaluator
from app.services.auto_trader import AutoTrader
from app.services.backtest import BacktestService
from app.services.binance_client import BinanceMarketDataClient
from app.services.exchange import BinanceFuturesAdapter
from app.services.execution import ExecutionService
from app.services.notifications import NotificationService
from app.services.order_pipeline import OrderValidator, PositionSizer
from app.services.risk_engine import RiskEngine
from app.services.scanner import FuturesScanner
from app.services.storage import Storage


def bot_settings_from_env(settings: Settings) -> BotSettings:
    return BotSettings(
        min_quote_volume=settings.scanner_min_quote_volume,
        max_spread_bps=settings.scanner_max_spread_bps,
        min_listing_age_days=settings.scanner_min_listing_age_days,
        min_score_to_trade=settings.scanner_min_score_to_trade,
        paper_initial_balance=settings.paper_initial_balance,
        taker_fee_rate=settings.taker_fee_rate,
        maker_fee_rate=settings.maker_fee_rate,
        slippage_bps=settings.slippage_bps,
        funding_rate_per_8h=settings.funding_rate_per_8h,
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
        self.live_preflight = {
            "all_tests_pass": settings.live_preflight_all_tests_pass,
            "demo_stable": settings.live_preflight_demo_stable,
            "sl_protection_pass": settings.live_preflight_sl_protection_pass,
            "reconnect_pass": settings.live_preflight_reconnect_pass,
            "reconciliation_pass": settings.live_preflight_reconciliation_pass,
            "duplicate_order_tests_pass": settings.live_preflight_duplicate_order_tests_pass,
        }
        self.performance_reset_at: datetime | None = None
        self.runtime_config_path = (Path(__file__).resolve().parents[3] / settings.runtime_config_path).resolve()
        self._load_runtime_config()
        self.bot_state = BotState.STOPPED
        self.emergency_stop = EmergencyStopState(active=False, reason=None)
        self.market_client = BinanceMarketDataClient(settings.binance_base_url)
        self.scanner = FuturesScanner(self.market_client, bot_settings)
        self.execution = ExecutionService(bot_settings)
        self.ai = AiEvaluator(enabled=settings.ai_evaluator_enabled)
        self.backtest = BacktestService()
        self.notifications = NotificationService()
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
            minimum_risk_reward=settings.minimum_risk_reward,
        )
        self.storage = Storage(settings.database_url)
        self.auto_trader = AutoTrader(self)

    @property
    def safe_mode(self) -> bool:
        return self.demo_exchange.snapshot_cache.safe_mode

    @property
    def safe_mode_reason(self) -> str | None:
        return self.demo_exchange.snapshot_cache.safe_mode_reason

    def enter_safe_mode(self, reason: str) -> None:
        self.bot_state = BotState.SAFE_MODE
        self.demo_exchange.snapshot_cache.safe_mode = True
        self.demo_exchange.snapshot_cache.safe_mode_reason = reason

    def save_runtime_config(self) -> None:
        payload = {
            "trading_mode": self.trading_mode.value,
            "live_trading_enabled": self.live_trading_enabled,
            "live_preflight": self.live_preflight,
            "performance_reset_at": self.performance_reset_at.isoformat() if self.performance_reset_at else None,
        }
        self.runtime_config_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

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
        reset_at = payload.get("performance_reset_at")
        if isinstance(reset_at, str):
            try:
                self.performance_reset_at = datetime.fromisoformat(reset_at)
                if self.performance_reset_at.tzinfo is None:
                    self.performance_reset_at = self.performance_reset_at.replace(tzinfo=UTC)
            except ValueError:
                self.performance_reset_at = None


state = AppState(Settings())
