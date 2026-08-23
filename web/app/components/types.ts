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
  max_symbol_exposure_fraction: number;
  max_directional_exposure_fraction: number;
  max_symbol_open_risk_fraction: number;
  would_reject_new_entries: boolean;
  reasons: string[];
  correlation: {
    status: "NOT_REQUESTED" | "COMPLETE" | "INCOMPLETE";
    interval: string;
    lookback: number;
    threshold: number;
    covered_symbols: string[];
    missing_symbols: string[];
    pairs: Array<{ symbol_a: string; symbol_b: string; correlation: number; observations: number; same_direction: boolean }>;
    clusters: Array<{ symbols: string[]; notional: number; notional_fraction: number }>;
    adjusted_exposure: number;
    adjusted_exposure_fraction: number;
    reasons: string[];
  };
  positions: Array<{ symbol: string; side: string; quantity: number; entry_price: number; mark_price: number; stop_loss: number | null; notional: number; open_risk: number | null; protected: boolean; notional_fraction: number; risk_fraction: number | null }>;
};
export type PortfolioRiskAudit = { audit_id: string; created_at: string; event: "SNAPSHOT" | "PRE_TRADE"; symbol: string | null; side: string | null; decision: "OBSERVED" | "WOULD_ALLOW" | "WOULD_REJECT"; reasons: string[]; before: PortfolioRisk; after: PortfolioRisk | null; candidate: Record<string, string | number> | null; fingerprint: string };
export type RiskPayload = { limits: StatusPayload["risk"]; portfolio: PortfolioRisk; audits: PortfolioRiskAudit[]; audit_summary: { total: number; snapshots: number; by_decision: Record<string, number> } };

export type GatewayStatus = {
  base_url: string;
  circuit_breaker: {
    state: "open" | "closed";
    consecutive_failures: number;
    remaining_cooldown_seconds: number;
  };
  cache: { hits: number; misses: number };
  usage: {
    market_weight_last_minute: number;
    private_weight_last_minute: number;
    order_requests_last_10s: number;
  };
};

export type OperationsStatus = {
  mode: TradingMode;
  gateway: {
    demo: GatewayStatus;
    live: GatewayStatus;
    market: GatewayStatus;
  };
  notifications: {
    configured: boolean;
    commands_enabled: boolean;
    queued: number;
    sent: number;
    dropped: number;
    commands: number;
    command_replies: number;
    unauthorized: number;
    last_command: string | null;
    last_command_at: string | null;
  };
  equity: {
    mode: string;
    samples: number;
    equity: number;
    peak_equity: number;
    current_drawdown_percent: number;
    max_drawdown_percent: number;
    return_percent: number;
    first_at: string | null;
    last_at: string | null;
  };
  ai_analytics: {
    shadow_only: true;
    read_only: true;
    collector: SmartEntryPayload["collector"];
    training: {
      mode: string;
      shadow_only: true;
      execution_enabled: false;
      model_family: string;
      sample_size: number;
      minimum_sample_for_training: number;
      minimum_sample_for_execution: number;
      ready_for_training: boolean;
      ready_for_execution: boolean;
      edge_detected: boolean;
      next_step: string;
      guardrails: string[];
      performance: SmartEntryPayload["performance"];
      collector: SmartEntryPayload["collector"];
    };
  };
  reconciliation: {
    last_reconciled_at: string | null;
    safe_mode: boolean;
    safe_mode_reason: string | null;
  };
};


export type StatusPayload = {
  mode: TradingMode;
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
  mode: TradingMode;
  connection: "DISCONNECTED" | "CONNECTED" | "STALE" | "SAFE_MODE";
  freshness: "LIVE" | "STALE" | "OFFLINE";
  snapshot_age_seconds?: number | null;
  reconciliation_age_seconds?: number | null;
  user_stream_connected?: boolean;
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
  data_quality: {
    accepted: boolean;
    status: "PASS" | "BLOCKED";
    confidence: number;
    minimum_confidence: number;
    sample_size: number;
    minimum_candles: number;
    latest_closed_at: string | null;
    age_seconds: number | null;
    complete: boolean;
    continuous: boolean;
    valid: boolean;
    fresh: boolean;
    reasons: string[];
    checked_at: string;
  } | null;
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

export type ExitAnalyticsBreakdown = {
  key: string;
  closes: number;
  realized_pnl: number;
  commission: number;
  funding: number;
  net_realized_pnl: number;
};

export type ExitAnalyticsAvailability = {
  available: boolean;
  coverage: number;
  reason: string | null;
};

export type ExitAnalytics = {
  read_only: boolean;
  generated_at: string;
  source: string;
  summary: {
    close_fills: number;
    realized_pnl: number;
    commission: number;
    funding: number;
    net_realized_pnl: number;
  };
  by_close_reason: ExitAnalyticsBreakdown[];
  by_side: ExitAnalyticsBreakdown[];
  by_symbol: ExitAnalyticsBreakdown[];
  realized_r: number | null;
  excursion: {
    lifecycles: number;
    mae_r: number | null;
    mfe_r: number | null;
    missed_r: number | null;
  };
  realized_r_availability: ExitAnalyticsAvailability;
  mae_availability: ExitAnalyticsAvailability;
  mfe_availability: ExitAnalyticsAvailability;
  missed_r_availability: ExitAnalyticsAvailability;
  notes: string[];
};

export type Performance = {
  balance: number;
  equity: number;
  initial_capital: number;
  net_pnl: number;
  non_trading_balance_change: number;
  equity_pnl: number;
  return_percent: number;
  equity_return_percent: number;
  realized_pnl: number;
  unrealized_pnl: number;
  fees_paid: number;
  funding_paid: number;
  win_rate: number;
  /** Binance REALIZED_PNL close events; not guaranteed to be complete trades. */
  realized_pnl_events: number;
  winning_realized_pnl_events: number;
  losing_realized_pnl_events: number;
  breakeven_realized_pnl_events: number;
  /** Deprecated compatibility aliases; prefer explicit realized-PnL event fields. */
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
  universe_mode: "VALIDATION" | "ALL_MARKET";
  whitelist: string[];
  blacklist: string[];
  min_quote_volume: number;
  max_spread_bps: number;
  min_listing_age_days: number;
  max_scan_symbols: number;
  scan_timeframes: string[];
  min_score_to_trade: number;
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

export type AIShadowConfig = {
  enabled: boolean;
  model: string;
  outcome_horizon: number;
  minimum_training_samples: number;
  mode: string;
  shadow_only: true;
  read_only: true;
  execution_enabled: false;
};

export type LogItem = {
  level: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type SmartEntryDecision = "WOULD_ENTER" | "WOULD_SKIP";
export type SmartEntryItem = { event_key: string; symbol: string; timeframe: string; side: string; decision: SmartEntryDecision; decision_label: string; decision_description: string; available: boolean; quality_score: number; reasons: string[]; decision_at: string; entry_price: number; stop_loss: number | null; risk_reward: number | null; outcomes: Record<string, null | { return_fraction: number; mfe_fraction: number; mae_fraction: number; horizon: number; last_close_time: number }>; outcome_note: string; shadow_only: true };
export type SmartEntryMetric = { sample_size: number; confidence_status: string; win_rate: number | null; average_return: number | null; median_return: number | null; average_mfe: number | null; average_mae: number | null };
export type SmartEntryPayload = { mode: string; shadow_only: true; read_only: true; decision_legend: Record<SmartEntryDecision, { label: string; description: string }>; items: SmartEntryItem[]; summary: { total: number; WOULD_ENTER: number; WOULD_SKIP: number; outcomes_available: number }; performance: { sample_size: number; confidence_status: string; minimum_sample: number; overall: SmartEntryMetric; dimensions: Record<string, Record<string, SmartEntryMetric>>; note: string }; collector: { running: boolean; interval_seconds: number; batch_size: number; cycles: number; last_run_at: string | null; last_success_at: string | null; last_error: string | null; consecutive_failures: number; last_cycle: { decisions_scanned: number; decisions_pending: number; decisions_complete: number; decisions_retrying: number; decisions_permanent_error: number; decisions_failed: number; outcomes_saved: number }; coverage: { total_decisions: number; complete_decisions: number; pending_decisions: number; retrying_decisions: number; permanent_errors: number; completion_ratio: number; oldest_pending_at: string | null; outcomes_by_horizon: Record<string, number> } }; note: string };
