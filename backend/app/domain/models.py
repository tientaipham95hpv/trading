from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TradingMode(StrEnum):
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"


class BotState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


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


class RiskDecision(BaseModel):
    accepted: bool
    reason: str | None = None
    signal: StrategySignal | None = None
    quantity: float | None = None
    notional: float | None = None
    margin_required: float | None = None
    risk_amount: float | None = None
    risk_reward: float | None = None


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
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    funding_paid: float
    win_rate: float
    total_trades: int
    open_positions: int


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
