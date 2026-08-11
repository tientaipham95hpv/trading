from app.core.settings import Settings
from app.domain.models import BotSettings, BotState, EmergencyStopState, TradingMode
from app.services.binance_client import BinanceMarketDataClient
from app.services.exchange import BinanceFuturesAdapter
from app.services.execution import ExecutionService
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
    )


class AppState:
    def __init__(self, settings: Settings) -> None:
        bot_settings = bot_settings_from_env(settings)
        self.settings = settings
        self.bot_settings = bot_settings
        self.trading_mode = TradingMode(settings.trading_mode)
        self.bot_state = BotState.STOPPED
        self.emergency_stop = EmergencyStopState(active=False, reason=None)
        self.market_client = BinanceMarketDataClient(settings.binance_base_url)
        self.scanner = FuturesScanner(self.market_client, bot_settings)
        self.execution = ExecutionService(bot_settings)
        self.position_sizer = PositionSizer()
        self.order_validator = OrderValidator()
        self.demo_exchange = BinanceFuturesAdapter(
            api_key=settings.binance_demo_api_key or settings.binance_api_key,
            api_secret=settings.binance_demo_api_secret or settings.binance_api_secret,
            base_url=settings.binance_demo_base_url,
            stream_url=settings.binance_demo_stream_url,
        )
        self.risk = RiskEngine(
            max_leverage=settings.max_leverage,
            risk_per_trade=settings.risk_per_trade,
            max_risk_per_trade=settings.max_risk_per_trade,
            max_daily_loss=settings.max_daily_loss,
            max_open_positions=settings.max_open_positions,
            minimum_risk_reward=settings.minimum_risk_reward,
        )
        self.storage = Storage(settings.database_url)

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


state = AppState(Settings())
