from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    app_env: str = "local"
    trading_mode: str = "DEMO"
    live_trading_enabled: bool = False
    binance_base_url: str = "https://fapi.binance.com"
    binance_demo_base_url: str = "https://demo-fapi.binance.com"
    binance_demo_stream_url: str = "wss://demo-fstream.binance.com"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_demo_api_key: str = ""
    binance_demo_api_secret: str = ""
    database_url: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"
    redis_url: str = "redis://localhost:6379/0"
    max_leverage: int = Field(default=5, ge=1, le=125)
    risk_per_trade: float = Field(default=0.005, gt=0, le=0.05)
    max_risk_per_trade: float = Field(default=0.01, gt=0, le=0.05)
    max_daily_loss: float = Field(default=0.04, gt=0, le=0.25)
    max_weekly_drawdown: float = Field(default=0.08, gt=0, le=0.5)
    max_open_positions: int = Field(default=4, ge=1, le=50)
    max_portfolio_exposure: float = Field(default=1.0, gt=0, le=3)
    max_correlated_positions: int = Field(default=2, ge=1, le=10)
    max_loss_streak: int = Field(default=3, ge=1, le=20)
    loss_streak_cooldown_minutes: int = Field(default=60, ge=1, le=1440)
    extreme_volatility_atr_fraction: float = Field(default=0.06, gt=0, le=1)
    stale_data_seconds: int = Field(default=180, ge=10, le=3600)
    minimum_risk_reward: float = Field(default=1.8, ge=1)
    default_margin_type: str = "ISOLATED"
    ai_evaluator_enabled: bool = False
    live_preflight_all_tests_pass: bool = False
    live_preflight_demo_stable: bool = False
    live_preflight_sl_protection_pass: bool = False
    live_preflight_reconnect_pass: bool = False
    live_preflight_reconciliation_pass: bool = False
    live_preflight_duplicate_order_tests_pass: bool = False
    scanner_min_quote_volume: float = 50_000_000
    scanner_max_spread_bps: float = 8.0
    scanner_min_listing_age_days: int = 30
    scanner_min_score_to_trade: int = 70
    paper_initial_balance: float = 10_000.0
    taker_fee_rate: float = 0.0005
    maker_fee_rate: float = 0.0002
    slippage_bps: float = 2.0
    funding_rate_per_8h: float = 0.0001
    runtime_config_path: str = "runtime-config.json"
