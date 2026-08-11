import type {
  BotSettings,
  Market,
  LogItem,
  Performance,
  Position,
  ScannerResult,
  StatusPayload,
  Trade,
  ExchangeSnapshot,
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
  markets: () => request<{ items: Market[] }>("/api/markets"),
  scanner: (limit = 40, timeframes = "15m") =>
    request<{ items: ScannerResult[] }>(`/api/scanner?limit=${limit}&timeframes=${timeframes}`),
  signals: () => request<{ items: ScannerResult[] }>("/api/signals"),
  positions: () => request<{ items: Position[] }>("/api/positions"),
  trades: () => request<{ items: Trade[] }>("/api/trades"),
  logs: () => request<{ items: LogItem[] }>("/api/logs"),
  performance: () => request<Performance>("/api/performance"),
  exchange: () => request<ExchangeSnapshot>("/api/exchange"),
  settings: () => request<BotSettings>("/api/settings"),
  updateSettings: (settings: BotSettings) =>
    request<BotSettings>("/api/settings", { method: "PUT", body: JSON.stringify(settings) }),
  bot: (action: "start" | "pause" | "stop") =>
    request<{ bot_state: StatusPayload["bot_state"] }>(`/api/bot/${action}`, { method: "POST" }),
  mode: (mode: "PAPER" | "DEMO") =>
    request<{ accepted: boolean; mode?: string; reason?: string }>(`/api/mode/${mode}`, { method: "POST" }),
};

export function wsUrl(channel: string): string {
  const base = API_BASE || (typeof window === "undefined" ? "" : window.location.origin);
  const url = new URL(`/api/ws/${channel}`, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
