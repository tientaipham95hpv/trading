export type WsState = "LIVE" | "STALE" | "OFFLINE";

export type StatusPayload = {
  mode: "PAPER" | "DEMO" | "LIVE";
  live_enabled: boolean;
  bot_state: "STOPPED" | "RUNNING" | "PAUSED";
  emergency_stop: boolean;
  risk: {
    max_leverage: number;
    risk_per_trade: number;
    max_risk_per_trade: number;
    max_daily_loss: number;
    max_open_positions: number;
    minimum_risk_reward: number;
  };
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
  stop_loss: number;
  take_profits: number[];
  realized_pnl: number;
  fees_paid: number;
  funding_paid: number;
  break_even_active: boolean;
  trailing_stop_active: boolean;
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
};

export type LogItem = {
  level: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};
