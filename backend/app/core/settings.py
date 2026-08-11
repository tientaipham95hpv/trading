from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    app_env: str = "local"
    trading_mode: str = "PAPER"
    live_trading_enabled: bool = False
    binance_base_url: str = "https://fapi.binance.com"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    database_url: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"
    redis_url: str = "redis://localhost:6379/0"
    max_leverage: int = Field(default=5, ge=1, le=125)
    risk_per_trade: float = Field(default=0.005, gt=0, le=0.05)
    max_risk_per_trade: float = Field(default=0.01, gt=0, le=0.05)
    max_daily_loss: float = Field(default=0.04, gt=0, le=0.25)
    max_open_positions: int = Field(default=4, ge=1, le=50)
    minimum_risk_reward: float = Field(default=1.8, ge=1)
    default_margin_type: str = "ISOLATED"
    ai_evaluator_enabled: bool = False
    scanner_min_quote_volume: float = 50_000_000
    scanner_max_spread_bps: float = 8.0
    scanner_min_listing_age_days: int = 30
    scanner_min_score_to_trade: int = 70
    paper_initial_balance: float = 10_000.0
    taker_fee_rate: float = 0.0005
    maker_fee_rate: float = 0.0002
    slippage_bps: float = 2.0
    funding_rate_per_8h: float = 0.0001
