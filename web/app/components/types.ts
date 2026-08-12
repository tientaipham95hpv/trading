export type WsState = "LIVE" | "STALE" | "OFFLINE";

export type StabilityCheck = {
  passed: boolean;
  value: number | string | boolean | null;
  requirement: string;
  detail: string;
};
export type StabilityIncident = {
  id: number;
  key: string;
  severity: "WARNING" | "CRITICAL";
  status: "OPEN" | "RESOLVED";
  message: string;
  payload: Record<string, unknown> | null;
  opened_at: string;
  resolved_at: string | null;
  last_seen_at: string;
};
export type DemoStability = {
  generated_at: string;
  mode: "DEMO";
  sample_started_at: string | null;
  score: number;
  verdict: "READY" | "COLLECTING_DATA" | "NOT_READY";
  checks: Record<string, StabilityCheck>;
  blockers: string[];
  metrics: Record<string, number | string | boolean | null>;
  incidents: StabilityIncident[];
  history: Array<Omit<DemoStability, "incidents" | "history">>;
};

export type TradingMode = "DEMO" | "LIVE";
export type PortfolioRisk = {
  generated_at: string;
  mode: "SHADOW";
  enforcement_enabled: false;
  equity: number;
  long_notional: number;
  short_notional: number;
  gross_exposure: number;
  net_exposure: number;
  gross_exposure_fraction: number;
  net_exposure_fraction: number;
  open_risk: number;
  open_risk_fraction: number;
  open_risk_limit: number;
  open_risk_remaining: number;
  exposure_limit: number;
  would_reject_new_entries: boolean;
  reasons: string[];
  positions: Array<{ symbol: string; side: string; quantity: number; entry_price: number; mark_price: number; stop_loss: number | null; notional: number; open_risk: number | null; protected: boolean }>;
};
export type RiskPayload = { limits: StatusPayload["risk"]; portfolio: PortfolioRisk };


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
    max_total_open_risk: number;
    max_margin_per_trade: number;
    max_total_margin: number;
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
  performance_reset_at?: string | null;
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
  lifecycles?: Array<{
    symbol: string;
    group_id: string;
    state:
      "OPENING" | "PROTECTED" | "TP1_HIT" | "TP2_HIT" | "CLOSING" | "CLOSED";
    side: string | null;
    entry_price: number;
    current_quantity: number;
    initial_quantity: number;
    remaining_take_profits: number;
    active_stop: number | null;
    last_event_at: string | null;
    updated_at: string;
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
  initial_capital: number;
  net_pnl: number;
  equity_pnl: number;
  return_percent: number;
  equity_return_percent: number;
  realized_pnl: number;
  unrealized_pnl: number;
  fees_paid: number;
  funding_paid: number;
  win_rate: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  open_positions: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe: number;
  sortino: number;
  expectancy: number;
};

export type BacktestConfig = {
  name: string;
  min_score: number;
  risk_fraction: number;
  stop_atr_multiplier: number;
  take_profit_r_multiples: number[];
  take_profit_fractions: number[];
};
export type BacktestMetrics = {
  pnl: number;
  profit_factor: number;
  drawdown: number;
  sharpe: number;
  sortino: number;
  expectancy: number;
  winrate: number;
  trades: number;
  fees: number;
  slippage: number;
  funding: number;
  walk_forward_windows: number;
  out_of_sample_trades: number;
  no_lookahead_bias: boolean;
};
export type BacktestStrategyReport = {
  config: BacktestConfig;
  config_fingerprint: string;
  metrics: BacktestMetrics;
  average_r: number;
  max_drawdown_percent: number;
  segments: Array<{ name: string; metrics: BacktestMetrics; average_r: number; max_drawdown_percent: number }>;
};
export type BacktestReport = {
  id: string;
  symbol: string;
  interval: string;
  candle_count: number;
  dataset_start: number;
  dataset_end: number;
  dataset_fingerprint: string;
  execution_policy: string;
  baseline: BacktestStrategyReport;
  candidate: BacktestStrategyReport | null;
  candidate_applied: false;
};

export type BacktestOptimizerCandidate = {
  rank: number;
  score: number;
  eligible: boolean;
  rejection_reasons: string[];
  profitable_walk_forward_ratio: number;
  report: BacktestStrategyReport;
};
export type BacktestOptimizerReport = {
  id: string;
  symbol: string;
  interval: string;
  dataset_fingerprint: string;
  evaluated_candidates: number;
  eligible_candidates: number;
  minimum_oos_trades: number;
  selection_policy: string;
  candidates: BacktestOptimizerCandidate[];
  candidate_applied: false;
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
  max_total_open_risk: number;
  max_margin_per_trade: number;
  max_total_margin: number;
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
