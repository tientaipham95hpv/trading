from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    app_env: str = "local"
    api_auth_token: str = ""
    operator_password: str = ""
    auth_session_ttl_seconds: int = Field(default=43_200, ge=900, le=604_800)
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
    risk_per_trade: float = Field(default=0.001, gt=0, le=0.05)
    max_risk_per_trade: float = Field(default=0.0025, gt=0, le=0.05)
    max_total_open_risk: float = Field(default=0.0025, gt=0, le=0.25)
    max_margin_per_trade: float = Field(default=0.10, gt=0, le=1)
    max_total_margin: float = Field(default=0.25, gt=0, le=1)
    max_daily_loss: float = Field(default=0.04, gt=0, le=0.25)
    max_weekly_drawdown: float = Field(default=0.08, gt=0, le=0.5)
    max_open_positions: int = Field(default=1, ge=1, le=50)
    max_portfolio_exposure: float = Field(default=0.50, gt=0, le=3)
    max_symbol_exposure: float = Field(default=0.15, gt=0, le=1)
    max_directional_exposure: float = Field(default=0.30, gt=0, le=1)
    max_symbol_open_risk: float = Field(default=0.015, gt=0, le=0.10)
    portfolio_risk_enforcement_enabled: bool = True
    max_correlated_positions: int = Field(default=2, ge=1, le=10)
    max_loss_streak: int = Field(default=2, ge=1, le=20)
    loss_streak_cooldown_minutes: int = Field(default=60, ge=1, le=1440)
    extreme_volatility_atr_fraction: float = Field(default=0.06, gt=0, le=1)
    stale_data_seconds: int = Field(default=180, ge=10, le=3600)
    minimum_risk_reward: float = Field(default=2.5, ge=1)
    default_margin_type: str = "ISOLATED"
    live_preflight_all_tests_pass: bool = False
    live_preflight_demo_stable: bool = False
    live_preflight_sl_protection_pass: bool = False
    live_preflight_reconnect_pass: bool = False
    live_preflight_reconciliation_pass: bool = False
    live_preflight_duplicate_order_tests_pass: bool = False
    scanner_universe_mode: str = "VALIDATION"
    # Comma-separated overrides keep the runtime universe durable across restarts.
    scanner_whitelist: str = "BTCUSDT,ETHUSDT,SOLUSDT"
    scanner_blacklist: str = "PROMUSDT,ZECUSDT,XMRUSDT,SUIUSDT,UNIUSDT,KAITOUSDT"
    scanner_max_symbols: int = Field(default=40, ge=1, le=100)
    scanner_min_quote_volume: float = 50_000_000
    scanner_max_spread_bps: float = 8.0
    scanner_min_listing_age_days: int = 30
    scanner_min_score_to_trade: int = 85
    scanner_high_risk_symbols: str = "AVAXUSDT,APRUSDT,ADAUSDT,BNBUSDT,WLDUSDT,XRPUSDT"
    scanner_high_risk_min_score: int = Field(default=90, ge=85, le=100)
    # Forward-test profile. These relaxations are consulted only while the
    # runtime is in DEMO; LIVE continues to use the production gates below.
    demo_test_min_score: int = Field(default=80, ge=70, le=84)
    demo_test_min_risk_reward: float = Field(default=1.8, ge=1.5, le=2.0)
    demo_test_allow_high_vol_regime: bool = True
    taker_fee_rate: float = 0.0005
    maker_fee_rate: float = 0.0002
    slippage_bps: float = 2.0
    funding_rate_per_8h: float = 0.0001
    runtime_config_path: str = "runtime-config.json"
    telegram_bot_token: str = ""
    telegram_alert_chat_id: str = ""
    ai_evaluator_enabled: bool = False
    ai_model: str = "claude-haiku-4-5"
    ai_outcome_horizon: int = Field(default=24, ge=4, le=96)
    ai_minimum_training_samples: int = Field(default=300, ge=50, le=10000)
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    ai_evaluator_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
