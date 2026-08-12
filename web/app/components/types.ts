export type WsState = "LIVE" | "STALE" | "OFFLINE";

export type TradingMode = "DEMO" | "LIVE";

export type StatusPayload = {
  mode: TradingMode | "PAPER";
  live_enabled: boolean;
  bot_state: "STOPPED" | "RUNNING" | "PAUSED" | "SAFE_MODE";
  emergency_stop: boolean;
  safe_mode: boolean;
  safe_mode_reason: string | null;
  exchange: ExchangeSnapshot;
  risk: {
    max_leverage: number;
    risk_per_trade: number;
    max_risk_per_trade: number;
    max_daily_loss: number;
    max_weekly_drawdown: number;
    max_open_positions: number;
    max_portfolio_exposure: number;
    max_correlated_positions: number;
    max_loss_streak: number;
    minimum_risk_reward: number;
  };
  live_readiness: {
    live_enabled: boolean;
    all_tests_pass: boolean;
    demo_stable: boolean;
    sl_protection_pass: boolean;
    reconnect_pass: boolean;
    reconciliation_pass: boolean;
    duplicate_order_tests_pass: boolean;
    allowed: boolean;
    blockers: string[];
  };
  auto_trader?: {
    running: boolean;
    interval_seconds: number;
    last_run_at: string | null;
    last_action_at: string | null;
    last_status: string;
    last_reason: string;
    last_symbol: string | null;
    cycles: number;
    submitted: number;
    rejected: number;
  };
};

export type ExchangeSnapshot = {
  mode: TradingMode | "PAPER";
  connection: "DISCONNECTED" | "CONNECTED" | "STALE" | "SAFE_MODE";
  safe_mode: boolean;
  safe_mode_reason: string | null;
  balance: {
    asset: string;
    balance: number;
    available: number;
    margin_balance: number;
    unrealized_pnl: number;
  };
  orders: Array<{
    symbol: string;
    order_id: number | string;
    client_order_id: string;
    side: string;
    order_type: string;
    status: string;
    price: number;
    quantity: number;
    executed_quantity: number;
    reduce_only: boolean;
    stop_price: number | null;
  }>;
  positions: Array<{
    symbol: string;
    side: string;
    quantity: number;
    entry_price: number;
    mark_price: number;
    unrealized_pnl: number;
    liquidation_price: number | null;
    leverage: number | null;
    margin_type: string | null;
  }>;
  last_reconciled_at: string | null;
  last_user_stream_at: string | null;
};

export type Candle = {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  close_time: number;
  quote_volume: number;
};

export type Market = {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  status: string;
  quote_volume: number;
  price_change_percent: number;
  funding_rate: number;
  bid_price: number;
  ask_price: number;
  last_price: number;
  spread_bps: number;
  listing_age_days: number | null;
};

export type ScannerResult = {
  symbol: string;
  timeframe: string;
  regime: string;
  long_score: number;
  short_score: number;
  action: "LONG" | "SHORT" | "NO_TRADE";
  strategy: string | null;
  price: number;
  price_change_percent: number;
  quote_volume: number;
  funding_rate: number;
  stop_loss: number | null;
  take_profits: number[];
  risk_reward: number | null;
  indicators: {
    atr: number | null;
    rsi: number | null;
    adx: number | null;
    ema20: number | null;
    ema50: number | null;
    ema200: number | null;
    macd_histogram: number | null;
    vwap: number | null;
  };
  reasons: string[];
  scanned_at: string;
};

export type Position = {
  id: string;
  symbol: string;
  side: "LONG" | "SHORT";
  status: "OPEN" | "CLOSED";
  quantity: number;
  remaining_quantity: number;
  entry_price: number;
  mark_price?: number;
  stop_loss: number;
  take_profits: number[];
  realized_pnl: number;
  unrealized_pnl?: number;
  fees_paid: number;
  funding_paid: number;
  break_even_active: boolean;
  trailing_stop_active: boolean;
  liquidation_price?: number | null;
  leverage?: number | null;
  margin_type?: string | null;
};

export type Trade = {
  id: string;
  symbol: string;
  side: "LONG" | "SHORT";
  entry_price: number;
  exit_price: number;
  quantity: number;
  gross_pnl: number;
  fee: number;
  slippage: number;
  funding: number;
  net_pnl: number;
  reason: string;
  created_at: string;
};

export type Performance = {
  balance: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  fees_paid: number;
  funding_paid: number;
  win_rate: number;
  total_trades: number;
  open_positions: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe: number;
  sortino: number;
  expectancy: number;
};

export type BotSettings = {
  whitelist: string[];
  blacklist: string[];
  min_quote_volume: number;
  max_spread_bps: number;
  min_listing_age_days: number;
  scan_timeframes: string[];
  min_score_to_trade: number;
  paper_initial_balance: number;
  taker_fee_rate: number;
  maker_fee_rate: number;
  slippage_bps: number;
  funding_rate_per_8h: number;
  max_leverage: number;
  risk_per_trade: number;
  max_risk_per_trade: number;
  max_daily_loss: number;
  max_weekly_drawdown: number;
  max_open_positions: number;
  max_portfolio_exposure: number;
  max_correlated_positions: number;
  max_loss_streak: number;
  loss_streak_cooldown_minutes: number;
  extreme_volatility_atr_fraction: number;
  stale_data_seconds: number;
  minimum_risk_reward: number;
};

export type LogItem = {
  level: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};
