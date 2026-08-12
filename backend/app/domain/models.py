from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class TradingMode(StrEnum):
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"


class BotState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SAFE_MODE = "SAFE_MODE"


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MarginType(StrEnum):
    ISOLATED = "ISOLATED"
    CROSSED = "CROSSED"


class MarketRegime(StrEnum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOL = "HIGH_VOL"
    LOW_VOL = "LOW_VOL"
    PANIC = "PANIC"


class SignalAction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class NotificationEvent(StrEnum):
    POSITION_OPEN = "POSITION_OPEN"
    POSITION_CLOSE = "POSITION_CLOSE"
    TP = "TP"
    SL = "SL"
    RISK_LIMIT = "RISK_LIMIT"
    API_DISCONNECT = "API_DISCONNECT"
    SAFE_MODE = "SAFE_MODE"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"


class SymbolCandidate(BaseModel):
    symbol: str
    base_asset: str
    quote_asset: str
    contract_type: str
    status: str
    onboard_date: int | None = None
    quote_volume: float = 0.0
    price_change_percent: float = 0.0
    funding_rate: float = 0.0
    bid_price: float = 0.0
    ask_price: float = 0.0
    last_price: float = 0.0
    spread_bps: float = 0.0
    listing_age_days: float | None = None


class Candle(BaseModel):
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float = 0.0


class IndicatorSnapshot(BaseModel):
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    atr: float | None = None
    bollinger_mid: float | None = None
    bollinger_upper: float | None = None
    bollinger_lower: float | None = None
    vwap: float | None = None
    adx: float | None = None
    volume_sma20: float | None = None


class ScannerResult(BaseModel):
    symbol: str
    timeframe: Timeframe
    regime: MarketRegime
    long_score: int = Field(ge=0, le=100)
    short_score: int = Field(ge=0, le=100)
    action: SignalAction
    strategy: str | None = None
    price: float = Field(gt=0)
    price_change_percent: float = 0.0
    quote_volume: float = 0.0
    funding_rate: float = 0.0
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: list[float] = Field(default_factory=list)
    risk_reward: float | None = None
    indicators: IndicatorSnapshot
    reasons: list[str] = Field(default_factory=list)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StrategySignal(BaseModel):
    symbol: str
    side: Side
    confidence: float = Field(ge=0, le=1)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    take_profits: list[float] = Field(default_factory=list)
    leverage: int = Field(default=1, ge=1)
    risk_fraction: float = Field(default=0.005, gt=0)
    order_type: OrderType = OrderType.MARKET
    strategy: str = "scanner"
    timeframe: Timeframe = Timeframe.M15
    metadata: dict[str, str] = Field(default_factory=dict)


class AiDecision(BaseModel):
    action: SignalAction
    confidence: float = Field(ge=0, le=1)
    strategy: str
    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class GuardSnapshot(BaseModel):
    portfolio_exposure: float = 0.0
    correlation_risk: bool = False
    daily_circuit_breaker: bool = False
    weekly_drawdown: float = 0.0
    loss_streak: int = 0
    loss_streak_cooldown: bool = False
    extreme_volatility: bool = False
    stale_data: bool = False
    reasons: list[str] = Field(default_factory=list)


class RiskDecision(BaseModel):
    accepted: bool
    reason: str | None = None
    signal: StrategySignal | None = None
    quantity: float | None = None
    notional: float | None = None
    margin_required: float | None = None
    risk_amount: float | None = None
    risk_reward: float | None = None
    guard: GuardSnapshot = Field(default_factory=GuardSnapshot)


class PortfolioRiskPosition(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_price: float
    mark_price: float
    stop_loss: float | None = None
    notional: float
    open_risk: float | None = None
    protected: bool = False
    notional_fraction: float = 0.0
    risk_fraction: float | None = None


class PortfolioRiskSnapshot(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: str = "SHADOW"
    enforcement_enabled: bool = False
    equity: float = 0.0
    long_notional: float = 0.0
    short_notional: float = 0.0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    gross_exposure_fraction: float = 0.0
    net_exposure_fraction: float = 0.0
    open_risk: float = 0.0
    open_risk_fraction: float = 0.0
    open_risk_limit: float = 0.0
    open_risk_remaining: float = 0.0
    exposure_limit: float = 0.0
    max_symbol_exposure_fraction: float = 0.20
    max_directional_exposure_fraction: float = 0.30
    max_symbol_open_risk_fraction: float = 0.015
    would_reject_new_entries: bool = False
    reasons: list[str] = Field(default_factory=list)
    positions: list[PortfolioRiskPosition] = Field(default_factory=list)


class PortfolioRiskAudit(BaseModel):
    audit_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event: str
    symbol: str | None = None
    side: str | None = None
    decision: str
    reasons: list[str] = Field(default_factory=list)
    before: PortfolioRiskSnapshot
    after: PortfolioRiskSnapshot | None = None
    candidate: dict[str, object] | None = None
    fingerprint: str


class EmergencyStopState(BaseModel):
    active: bool
    reason: str | None = None


class OrderPlan(BaseModel):
    client_order_id: str
    symbol: str
    side: Side
    quantity: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    leverage: int = Field(ge=1)
    margin_type: MarginType = MarginType.ISOLATED
    order_type: OrderType = OrderType.MARKET
    take_profits: list[float] = Field(default_factory=list)
    risk_fraction: float = Field(default=0.005, gt=0)


class PaperOrder(BaseModel):
    id: str
    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    status: OrderStatus
    quantity: float
    filled_quantity: float = 0.0
    price: float
    stop_loss: float
    take_profits: list[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PaperFill(BaseModel):
    id: str
    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float
    slippage: float
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PaperPosition(BaseModel):
    id: str
    symbol: str
    side: Side
    status: PositionStatus = PositionStatus.OPEN
    quantity: float
    remaining_quantity: float
    entry_price: float
    stop_loss: float
    take_profits: list[float] = Field(default_factory=list)
    filled_take_profits: list[float] = Field(default_factory=list)
    break_even_active: bool = False
    trailing_stop_active: bool = False
    trailing_stop_distance: float | None = None
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    funding_paid: float = 0.0
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    closed_at: datetime | None = None


class TradeRecord(BaseModel):
    id: str
    symbol: str
    side: Side
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    fee: float
    slippage: float
    funding: float = 0.0
    net_pnl: float
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PerformanceSnapshot(BaseModel):
    balance: float
    equity: float
    initial_capital: float = 0.0
    net_pnl: float = 0.0
    equity_pnl: float = 0.0
    return_percent: float = 0.0
    equity_return_percent: float = 0.0
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    funding_paid: float
    win_rate: float
    total_trades: int
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    open_positions: int
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    expectancy: float = 0.0


class BotSettings(BaseModel):
    whitelist: list[str] = Field(default_factory=list)
    blacklist: list[str] = Field(default_factory=list)
    min_quote_volume: float = 50_000_000
    max_spread_bps: float = 8.0
    min_listing_age_days: int = 30
    scan_timeframes: list[Timeframe] = Field(
        default_factory=lambda: [
            Timeframe.M1,
            Timeframe.M5,
            Timeframe.M15,
            Timeframe.H1,
            Timeframe.H4,
        ]
    )
    min_score_to_trade: int = 70
    paper_initial_balance: float = 10_000.0
    taker_fee_rate: float = 0.0005
    maker_fee_rate: float = 0.0002
    slippage_bps: float = 2.0
    funding_rate_per_8h: float = 0.0001
    max_leverage: int = Field(default=5, ge=1, le=10)
    risk_per_trade: float = Field(default=0.005, gt=0, le=0.005)
    max_risk_per_trade: float = Field(default=0.0075, gt=0, le=0.01)
    max_total_open_risk: float = Field(default=0.03, gt=0, le=0.10)
    max_margin_per_trade: float = Field(default=0.10, gt=0, le=1.0)
    max_total_margin: float = Field(default=0.30, gt=0, le=1.0)
    max_daily_loss: float = Field(default=0.04, gt=0, le=0.04)
    max_weekly_drawdown: float = Field(default=0.08, gt=0, le=0.08)
    max_open_positions: int = Field(default=3, ge=1, le=4)
    max_portfolio_exposure: float = Field(default=0.30, gt=0, le=1.0)
    max_symbol_exposure: float = Field(default=0.20, gt=0, le=1.0)
    max_directional_exposure: float = Field(default=0.30, gt=0, le=1.0)
    max_symbol_open_risk: float = Field(default=0.015, gt=0, le=0.10)
    max_correlated_positions: int = Field(default=2, ge=1, le=2)
    max_loss_streak: int = Field(default=3, ge=1, le=3)
    loss_streak_cooldown_minutes: int = Field(default=60, ge=1, le=1440)
    extreme_volatility_atr_fraction: float = Field(default=0.06, gt=0, le=0.06)
    stale_data_seconds: int = Field(default=180, ge=10, le=180)
    minimum_risk_reward: float = Field(default=1.8, ge=1.8)


class ExchangeConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    STALE = "STALE"
    SAFE_MODE = "SAFE_MODE"


class ExchangePositionLifecycleState(StrEnum):
    OPENING = "OPENING"
    PROTECTED = "PROTECTED"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ExchangeBalance(BaseModel):
    asset: str = "USDT"
    balance: float = 0.0
    available: float = 0.0
    margin_balance: float = 0.0
    unrealized_pnl: float = 0.0


class ExchangeOrder(BaseModel):
    symbol: str
    order_id: int | str
    client_order_id: str
    side: str
    order_type: str
    status: str
    price: float = 0.0
    quantity: float = 0.0
    executed_quantity: float = 0.0
    reduce_only: bool = False
    stop_price: float | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class ExchangePosition(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_price: float
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    liquidation_price: float | None = None
    leverage: int | None = None
    margin_type: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)


class ExchangePositionLifecycle(BaseModel):
    symbol: str
    group_id: str
    state: ExchangePositionLifecycleState = ExchangePositionLifecycleState.OPENING
    side: str | None = None
    entry_price: float = 0.0
    current_quantity: float = 0.0
    initial_quantity: float = 0.0
    remaining_take_profits: int = 0
    active_stop: float | None = None
    last_event_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExchangeSnapshot(BaseModel):
    mode: TradingMode = TradingMode.PAPER
    connection: ExchangeConnectionState = ExchangeConnectionState.DISCONNECTED
    safe_mode: bool = False
    safe_mode_reason: str | None = None
    balance: ExchangeBalance = Field(default_factory=ExchangeBalance)
    orders: list[ExchangeOrder] = Field(default_factory=list)
    positions: list[ExchangePosition] = Field(default_factory=list)
    lifecycles: list[ExchangePositionLifecycle] = Field(default_factory=list)
    last_reconciled_at: datetime | None = None
    last_user_stream_at: datetime | None = None


class ExchangeExecutionResult(BaseModel):
    accepted: bool
    status: str
    client_order_id: str
    order: dict[str, object]
    fills: list[dict[str, object]] = Field(default_factory=list)
    positions: list[dict[str, object]] = Field(default_factory=list)
    trades: list[dict[str, object]] = Field(default_factory=list)
    critical_alert: str | None = None


class LiveReadiness(BaseModel):
    live_enabled: bool = False
    all_tests_pass: bool = False
    demo_stable: bool = False
    sl_protection_pass: bool = False
    reconnect_pass: bool = False
    reconciliation_pass: bool = False
    duplicate_order_tests_pass: bool = False
    allowed: bool = False
    blockers: list[str] = Field(default_factory=list)


class StabilityCheck(BaseModel):
    passed: bool = False
    value: float | int | str | bool | None = None
    requirement: str
    detail: str


class DemoStabilityReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: TradingMode = TradingMode.DEMO
    sample_started_at: datetime | None = None
    score: int = 0
    verdict: str = "NOT_READY"
    checks: dict[str, StabilityCheck] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class LiveConfigUpdate(BaseModel):
    live_enabled: bool | None = None
    all_tests_pass: bool | None = None
    demo_stable: bool | None = None
    sl_protection_pass: bool | None = None
    reconnect_pass: bool | None = None
    reconciliation_pass: bool | None = None
    duplicate_order_tests_pass: bool | None = None


class BacktestMetrics(BaseModel):
    pnl: float = 0.0
    profit_factor: float = 0.0
    drawdown: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    expectancy: float = 0.0
    winrate: float = 0.0
    trades: int = 0
    fees: float = 0.0
    slippage: float = 0.0
    funding: float = 0.0
    walk_forward_windows: int = 0
    out_of_sample_trades: int = 0
    no_lookahead_bias: bool = True


class BacktestStrategyConfig(BaseModel):
    """Versioned experiment settings; never written to runtime settings."""

    name: str = "Baseline"
    min_score: int = Field(default=70, ge=0, le=100)
    risk_fraction: float = Field(default=0.005, gt=0, le=0.01)
    stop_atr_multiplier: float = Field(default=1.2, gt=0, le=10)
    take_profit_r_multiples: list[float] = Field(default_factory=lambda: [1.0, 1.8, 2.6])
    take_profit_fractions: list[float] = Field(default_factory=lambda: [0.4, 0.3, 0.3])


class BacktestRunRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", min_length=3, max_length=30)
    interval: Timeframe = Timeframe.M15
    limit: int = Field(default=1000, ge=250, le=5000)
    initial_capital: float = Field(default=10_000, gt=0)
    taker_fee_rate: float = Field(default=0.0005, ge=0, le=0.01)
    slippage_bps: float = Field(default=2.0, ge=0, le=100)
    funding_rate_per_8h: float = Field(default=0.0001, ge=-0.01, le=0.01)
    train_fraction: float = Field(default=0.6, gt=0, lt=1)
    validation_fraction: float = Field(default=0.2, gt=0, lt=1)
    walk_forward_windows: int = Field(default=3, ge=1, le=20)
    baseline: BacktestStrategyConfig = Field(default_factory=BacktestStrategyConfig)
    candidate: BacktestStrategyConfig | None = None

    @model_validator(mode="after")
    def validate_splits(self) -> "BacktestRunRequest":
        if self.train_fraction + self.validation_fraction >= 1:
            raise ValueError("Train + Validation phải nhỏ hơn 1")
        return self


class BacktestPoint(BaseModel):
    time: int
    equity: float


class BacktestTrade(BaseModel):
    side: Side
    signal_time: int
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    fees: float
    funding: float
    slippage: float
    net_pnl: float
    r_multiple: float
    reason: str


class BacktestSegment(BaseModel):
    name: str
    start_time: int | None = None
    end_time: int | None = None
    metrics: BacktestMetrics
    average_r: float = 0.0
    max_drawdown_percent: float = 0.0


class BacktestStrategyReport(BaseModel):
    config: BacktestStrategyConfig
    config_fingerprint: str
    metrics: BacktestMetrics
    average_r: float = 0.0
    max_drawdown_percent: float = 0.0
    segments: list[BacktestSegment] = Field(default_factory=list)
    walk_forward: list[BacktestSegment] = Field(default_factory=list)
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[BacktestPoint] = Field(default_factory=list)


class BacktestRunReport(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    symbol: str
    interval: Timeframe
    candle_count: int
    dataset_start: int
    dataset_end: int
    dataset_fingerprint: str
    execution_policy: str = "NEXT_OPEN_CONSERVATIVE"
    baseline: BacktestStrategyReport
    candidate: BacktestStrategyReport | None = None
    candidate_applied: bool = False


class BacktestOptimizerRequest(BaseModel):
    """Bounded experiment grid; results are advisory and never mutate runtime settings."""

    run: BacktestRunRequest = Field(default_factory=BacktestRunRequest)
    min_scores: list[int] = Field(default_factory=lambda: [65, 70, 75])
    stop_atr_multipliers: list[float] = Field(default_factory=lambda: [1.0, 1.2, 1.5])
    risk_fractions: list[float] = Field(default_factory=lambda: [0.003, 0.005])
    minimum_oos_trades: int = Field(default=3, ge=1, le=100)
    max_candidates: int = Field(default=12, ge=1, le=24)

    @model_validator(mode="after")
    def validate_grid(self) -> "BacktestOptimizerRequest":
        if not self.min_scores or not self.stop_atr_multipliers or not self.risk_fractions:
            raise ValueError("Lưới optimizer không được để trống")
        if any(score < 0 or score > 100 for score in self.min_scores):
            raise ValueError("Signal Score phải nằm trong khoảng 0-100")
        if any(value <= 0 or value > 10 for value in self.stop_atr_multipliers):
            raise ValueError("ATR Stop phải nằm trong khoảng (0, 10]")
        if any(value <= 0 or value > 0.01 for value in self.risk_fractions):
            raise ValueError("Risk fraction phải nằm trong khoảng (0, 0.01]")
        combinations = (
            len(set(self.min_scores))
            * len(set(self.stop_atr_multipliers))
            * len(set(self.risk_fractions))
        )
        if combinations > self.max_candidates:
            raise ValueError(
                f"Lưới có {combinations} Candidate, vượt giới hạn {self.max_candidates}"
            )
        return self


class BacktestOptimizerCandidate(BaseModel):
    rank: int
    score: float
    eligible: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    profitable_walk_forward_ratio: float = 0.0
    report: BacktestStrategyReport


class BacktestOptimizerReport(BaseModel):
    id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    symbol: str
    interval: Timeframe
    dataset_fingerprint: str
    evaluated_candidates: int
    eligible_candidates: int
    minimum_oos_trades: int
    selection_policy: str = "VALIDATION_OOS_STABILITY_V1"
    candidates: list[BacktestOptimizerCandidate] = Field(default_factory=list)
    candidate_applied: bool = False


class NotificationPayload(BaseModel):
    event: NotificationEvent
    title: str
    body: str
    data: dict[str, str] = Field(default_factory=dict)
    apns_ready: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PushDeviceRegistration(BaseModel):
    platform: str = "ios"
    token: str = Field(min_length=16)
