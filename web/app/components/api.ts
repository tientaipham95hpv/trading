import type {
  BacktestOptimizerReport,
  BacktestReport,
  BotSettings,
  DemoStability,
  Candle,
  Market,
  LogItem,
  Performance,
  Position,
  RiskPayload,
  ScannerResult,
  StatusPayload,
  Trade,
  ExchangeSnapshot,
  ExitAnalytics,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export const api = {
  status: () => request<StatusPayload>("/api/status"),
  risk: () => request<RiskPayload>("/api/risk"),
  stability: () => request<DemoStability>("/api/demo/stability"),
  markets: () => request<{ items: Market[] }>("/api/markets"),
  scanner: (limit = 40, timeframes = "15m") =>
    request<{ items: ScannerResult[] }>(
      `/api/scanner?limit=${limit}&timeframes=${timeframes}`,
    ),
  signals: () => request<{ items: ScannerResult[] }>("/api/signals"),
  positions: () => request<{ items: Position[] }>("/api/positions"),
  trades: () => request<{ items: Trade[] }>("/api/trades"),
  logs: () => request<{ items: LogItem[] }>("/api/logs"),
  performance: () => request<Performance>("/api/performance"),
  exitAnalytics: () => request<ExitAnalytics>("/api/exit-analytics"),
  exchange: () => request<ExchangeSnapshot>("/api/exchange"),
  settings: () => request<BotSettings>("/api/settings"),
  runBacktest: (payload: object) =>
    request<BacktestReport>("/api/backtests/run", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  latestBacktest: () => request<BacktestReport>("/api/backtests/latest"),
  optimizeBacktest: (payload: object) =>
    request<BacktestOptimizerReport>("/api/backtests/optimize", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  latestBacktestOptimizer: () =>
    request<BacktestOptimizerReport>("/api/backtests/optimizer/latest"),
  klines: (symbol: string, interval = "15m", limit = 180) =>
    request<{ symbol: string; interval: string; items: Candle[] }>(
      `/api/klines/${symbol}?interval=${interval}&limit=${limit}`,
    ),
  updateSettings: (settings: BotSettings) =>
    request<BotSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  bot: (action: "start" | "pause" | "stop") =>
    request<{ bot_state: StatusPayload["bot_state"] }>(`/api/bot/${action}`, {
      method: "POST",
    }),
  mode: (mode: "DEMO" | "LIVE") =>
    request<{ accepted: boolean; mode?: string; reason?: string }>(
      `/api/mode/${mode}`,
      { method: "POST" },
    ),
  control: (action: "pause-new-trades" | "cancel-orders" | "close-all") =>
    request<{ accepted: boolean; reason?: string }>(`/api/controls/${action}`, {
      method: "POST",
    }),
  emergencyStop: () =>
    request<{ active: boolean; reason: string | null }>("/api/emergency-stop", {
      method: "POST",
    }),
  liveConfig: (update: Partial<StatusPayload["live_readiness"]>) =>
    request<StatusPayload["live_readiness"]>("/api/live/config", {
      method: "PUT",
      body: JSON.stringify(update),
    }),
  prepareLive: () =>
    request<{
      accepted: boolean;
      reason?: string;
      readiness?: StatusPayload["live_readiness"];
    }>("/api/live/prepare", { method: "POST" }),
};

export function wsUrl(channel: string): string {
  const base =
    API_BASE || (typeof window === "undefined" ? "" : window.location.origin);
  const url = new URL(`/api/ws/${channel}`, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
