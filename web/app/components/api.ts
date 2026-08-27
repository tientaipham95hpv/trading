import type {
  AIShadowConfig,
  BacktestOptimizerReport,
  BacktestReport,
  BotSettings,
  DemoStability,
  Candle,
  JournalCategory,
  JournalEntry,
  Market,
  LogItem,
  Performance,
  Position,
  OperationsStatus,
  RiskPayload,
  ScannerResult,
  StatusPayload,
  Trade,
  ExchangeSnapshot,
  ExitAnalytics,
  SmartEntryPayload,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";
const REQUEST_TIMEOUT_MS = 30_000;
const AUTH_TOKEN_KEY = "trading-api-token";
const AUTH_EXPIRED_EVENT = "trading-auth-expired";

class AuthenticationError extends Error {}

function authToken(): string {
  return typeof window === "undefined"
    ? ""
    : window.sessionStorage.getItem(AUTH_TOKEN_KEY) || "";
}

function normalizeRequestError(path: string, error: unknown): Error {
  if (error instanceof DOMException && error.name === "AbortError") {
    return new Error(`API ${path} quá thời gian phản hồi, đang giữ dữ liệu cũ.`);
  }
  if (error instanceof Error && /aborted/i.test(error.message)) {
    return new Error(`API ${path} quá thời gian phản hồi, đang giữ dữ liệu cũ.`);
  }
  return error instanceof Error ? error : new Error("Không tải được dữ liệu");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let lastError: unknown;
  const retryable = !init?.method || init.method === "GET";
  for (let attempt = 0; attempt < (retryable ? 2 : 1); attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        signal: init?.signal ?? controller.signal,
        cache: "no-store",
        headers: {
          "content-type": "application/json",
          ...(authToken() ? { authorization: `Bearer ${authToken()}` } : {}),
          ...(init?.headers || {}),
        },
      });
      if (response.status === 401) {
        window.sessionStorage.removeItem(AUTH_TOKEN_KEY);
        window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
        throw new AuthenticationError("Phiên vận hành đã hết hạn hoặc token không hợp lệ.");
      }
      if (!response.ok) throw new Error(await response.text());
      return response.json() as Promise<T>;
    } catch (error) {
      lastError = normalizeRequestError(path, error);
      if (error instanceof AuthenticationError) throw error;
      if (!retryable || attempt > 0) throw lastError;
      await new Promise((resolve) => window.setTimeout(resolve, 400));
    } finally {
      window.clearTimeout(timeout);
    }
  }
  throw lastError;
}

export const api = {
  hasToken: () => Boolean(authToken()),
  setToken: (token: string) =>
    window.sessionStorage.setItem(AUTH_TOKEN_KEY, token.trim()),
  clearToken: () => window.sessionStorage.removeItem(AUTH_TOKEN_KEY),
  authExpiredEvent: AUTH_EXPIRED_EVENT,
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
  journal: (
    category: JournalCategory = "ALL",
    limit = 100,
    since?: string,
  ) =>
    request<{ items: JournalEntry[] }>(
      `/api/journal?category=${encodeURIComponent(category)}&limit=${limit}${since ? `&since=${encodeURIComponent(since)}` : ""}`,
    ),
  performance: () => request<Performance>("/api/performance"),
  operations: () => request<OperationsStatus>("/api/operations"),
  exitAnalytics: () => request<ExitAnalytics>("/api/exit-analytics"),
  smartEntry: () => request<SmartEntryPayload>("/api/smart-entry"),
  exchange: () => request<ExchangeSnapshot>("/api/exchange"),
  settings: () => request<BotSettings>("/api/settings"),
  aiConfig: () => request<AIShadowConfig>("/api/ai/config"),
  updateAiConfig: (config: Partial<AIShadowConfig>) =>
    request<AIShadowConfig>("/api/ai/config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
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
  resetSafeMode: () =>
    request<{
      accepted: boolean;
      bot_state?: StatusPayload["bot_state"];
      reason?: string;
    }>("/api/safe-mode/reset", { method: "POST" }),
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
  if (authToken()) url.searchParams.set("access_token", authToken());
  return url.toString();
}
