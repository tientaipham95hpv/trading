"use client";

import {
  Activity,
  BarChart3,
  Bot,
  FileText,
  Gauge,
  ListFilter,
  LockKeyhole,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Search,
  Settings,
  ShieldAlert,
  ShieldX,
  Square,
  Trash2,
  TrendingUp,
  WalletCards,
  XCircle,
  Zap,
} from "lucide-react";
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from "lightweight-charts";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, wsUrl } from "./api";
import type {
  BacktestReport,
  BotSettings,
  Candle,
  DemoStability,
  ExchangeSnapshot,
  LogItem,
  Market,
  Performance,
  Position,
  ScannerResult,
  StatusPayload,
  Trade,
  WsState,
} from "./types";

type PageKey =
  | "dashboard"
  | "markets"
  | "scanner"
  | "positions"
  | "trades"
  | "strategies"
  | "analytics"
  | "risk"
  | "logs"
  | "settings";

const nav = [
  { key: "dashboard", href: "/", label: "Tổng quan", icon: Gauge },
  { key: "markets", href: "/markets", label: "Thị trường", icon: WalletCards },
  { key: "scanner", href: "/scanner", label: "Quét tín hiệu", icon: Activity },
  { key: "positions", href: "/positions", label: "Vị thế", icon: TrendingUp },
  { key: "trades", href: "/trades", label: "Lệnh đã chốt", icon: BarChart3 },
  { key: "strategies", href: "/strategies", label: "Chiến lược", icon: Bot },
  { key: "analytics", href: "/analytics", label: "Phân tích", icon: BarChart3 },
  { key: "risk", href: "/risk", label: "Rủi ro", icon: ShieldAlert },
  { key: "logs", href: "/logs", label: "Nhật ký", icon: FileText },
  { key: "settings", href: "/settings", label: "Cài đặt", icon: Settings },
] as const;

export function DashboardApp({ page }: { page: PageKey }) {
  const pathname = usePathname();
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [stability, setStability] = useState<DemoStability | null>(null);
  const [markets, setMarkets] = useState<Market[]>([]);
  const [scanner, setScanner] = useState<ScannerResult[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [performance, setPerformance] = useState<Performance | null>(null);
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [exchange, setExchange] = useState<ExchangeSnapshot | null>(null);
  const [wsState, setWsState] = useState<WsState>("OFFLINE");
  const [lastLiveAt, setLastLiveAt] = useState<number>(0);
  const lastLiveAtRef = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  async function refresh() {
    setIsRefreshing(true);
    try {
      const [
        nextStatus,
        nextStability,
        nextMarkets,
        nextScanner,
        nextPositions,
        nextTrades,
        nextPerformance,
        nextExchange,
        nextSettings,
        nextLogs,
      ] = await Promise.all([
        api.status(),
        api.stability(),
        api.markets(),
        api.scanner(40, "15m"),
        api.positions(),
        api.trades(),
        api.performance(),
        api.exchange(),
        api.settings(),
        api.logs(),
      ]);
      setStatus(nextStatus);
      setStability(nextStability);
      setMarkets(nextMarkets.items);
      setScanner(nextScanner.items);
      setPositions(nextPositions.items);
      setTrades(nextTrades.items);
      setPerformance(nextPerformance);
      setExchange(nextExchange);
      setSettings(nextSettings);
      setLogs(nextLogs.items);
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Không tải được dữ liệu",
      );
    } finally {
      setHasLoaded(true);
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    const firstLoad = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => {
      window.clearTimeout(firstLoad);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const sockets: WebSocket[] = [];
    const reconnects: number[] = [];
    let closed = false;

    type RealtimePayload = {
      channel?: string;
      data?: StatusPayload | ExchangeSnapshot | Performance;
      items?: Position[];
    };

    function markLive() {
      setWsState("LIVE");
      lastLiveAtRef.current = Date.now();
      setLastLiveAt(lastLiveAtRef.current);
    }

    function connect(
      channel: "system" | "exchange" | "positions" | "performance",
    ) {
      const socket = new WebSocket(wsUrl(channel));
      sockets.push(socket);
      socket.onopen = () => {
        markLive();
      };
      socket.onmessage = (event) => {
        markLive();
        const payload = JSON.parse(event.data) as RealtimePayload;
        if (channel === "system" && payload.data) {
          const nextStatus = payload.data as StatusPayload;
          setStatus(nextStatus);
          setExchange(nextStatus.exchange);
        }
        if (channel === "exchange" && payload.data) {
          setExchange(payload.data as ExchangeSnapshot);
        }
        if (channel === "positions" && payload.items) {
          setPositions(payload.items);
        }
        if (channel === "performance" && payload.data) {
          setPerformance(payload.data as Performance);
        }
      };
      socket.onerror = () => setWsState("STALE");
      socket.onclose = () => {
        if (closed) return;
        setWsState("OFFLINE");
        reconnects.push(window.setTimeout(() => connect(channel), 2500));
      };
    }

    (["system", "exchange", "positions", "performance"] as const).forEach(
      connect,
    );
    const staleTimer = window.setInterval(() => {
      setWsState(Date.now() - lastLiveAtRef.current > 7000 ? "STALE" : "LIVE");
    }, 3000);
    return () => {
      closed = true;
      reconnects.forEach((reconnect) => window.clearTimeout(reconnect));
      window.clearInterval(staleTimer);
      sockets.forEach((socket) => socket.close());
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const [nextTrades, nextLogs, nextScanner] = await Promise.all([
          api.trades(),
          api.logs(),
          api.scanner(40, "15m"),
        ]);
        setTrades(nextTrades.items);
        setLogs(nextLogs.items);
        setScanner(nextScanner.items);
      } catch {
        setWsState((current) => (current === "LIVE" ? "STALE" : current));
      }
    }, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const currentPage = nav.find((item) => item.key === page) ?? nav[0];

  return (
    <main className="grid min-h-screen grid-cols-1 bg-[#070b12] text-slate-100 lg:grid-cols-[264px_1fr]">
      <aside className="min-w-0 border-r border-white/10 bg-[#0a101a] text-white lg:sticky lg:top-0 lg:h-screen">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3 lg:block lg:px-5 lg:py-5">
          <div>
            <p className="text-xs font-bold uppercase text-cyan-300">
              USD-M Futures
            </p>
            <h1 className="mt-1 text-lg font-bold lg:text-xl">
              Trading Cockpit
            </h1>
          </div>
          <StatusBadge value={wsState} />
        </div>
        <nav className="scrollbar-none flex gap-1 overflow-x-auto px-3 py-2 lg:grid lg:max-h-none lg:grid-cols-1 lg:overflow-y-auto lg:p-3">
          {nav.map((item) => {
            const Icon = item.icon;
            const active =
              item.href === pathname ||
              (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link
                className={`flex min-h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-semibold transition lg:gap-3 ${
                  active
                    ? "bg-cyan-300 text-slate-950 shadow-sm shadow-cyan-500/20"
                    : "text-slate-300 hover:bg-white/10 hover:text-white"
                }`}
                href={item.href}
                key={item.key}
              >
                <Icon size={18} />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <section className="min-w-0">
        <header className="sticky top-0 z-10 flex flex-col gap-3 border-b border-white/10 bg-[#0b111d]/95 px-4 py-3 shadow-sm shadow-black/30 backdrop-blur md:px-5 md:py-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase text-cyan-300">
              Control Surface
            </p>
            <h2 className="text-xl font-bold md:text-2xl">
              {currentPage.label}
            </h2>
            <StatusLine
              exchange={exchange ?? status?.exchange ?? null}
              isRefreshing={isRefreshing}
              lastLiveAt={lastLiveAt}
              status={status}
              wsState={wsState}
            />
          </div>
          <div className="hidden flex-wrap items-center gap-2 md:flex xl:justify-end">
            <ModeSelector
              current={normalizeMode(status?.mode)}
              liveAllowed={status?.live_readiness.allowed ?? false}
              onDone={refresh}
            />
            <BotControls onDone={refresh} />
            <Pill
              label="Chế độ"
              value={normalizeMode(status?.mode)}
              tone="neutral"
            />
            <Pill
              label="LIVE"
              value={status?.live_enabled ? "ON" : "OFF"}
              tone={status?.live_enabled ? "danger" : "safe"}
            />
            <Pill
              label="Bot"
              value={viBotState(status?.bot_state)}
              tone={status?.safe_mode ? "danger" : "neutral"}
            />
            <Pill
              label="Exchange"
              value={viExchangeConnection(
                exchange?.connection ?? status?.exchange.connection,
              )}
              tone={
                (exchange?.connection ?? status?.exchange.connection) ===
                "CONNECTED"
                  ? "safe"
                  : "danger"
              }
            />
            <button
              className="inline-flex min-h-9 items-center gap-2 rounded-md border border-white/15 bg-white/10 px-3 py-2 text-sm font-bold text-slate-100 transition hover:bg-white/15 disabled:opacity-60"
              disabled={isRefreshing}
              onClick={() => void refresh()}
              type="button"
            >
              <RefreshCw
                className={isRefreshing ? "animate-spin" : ""}
                size={16}
              />
              {isRefreshing ? "Đang tải" : "Làm mới"}
            </button>
          </div>
        </header>

        <div className="p-4 md:p-5">
          {error && (
            <div className="mb-4 rounded-md border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}
          {!hasLoaded && <LoadingGrid />}
          {page === "dashboard" && (
            <Dashboard
              exchange={exchange ?? status?.exchange ?? null}
              markets={markets}
              onDone={refresh}
              performance={performance}
              positions={positions}
              scanner={scanner}
              stability={stability}
              status={status}
            />
          )}
          {page === "markets" && <Markets markets={markets} />}
          {page === "scanner" && <Scanner scanner={scanner} />}
          {page === "positions" && (
            <Positions markets={markets} positions={positions} />
          )}
          {page === "trades" && <Trades trades={trades} />}
          {page === "strategies" && <Strategies scanner={scanner} />}
          {page === "analytics" && (
            <Analytics performance={performance} trades={trades} />
          )}
          {page === "risk" && <Risk onDone={refresh} status={status} />}
          {page === "logs" && <Logs logs={logs} />}
          {page === "settings" && settings && (
            <SettingsPage onSaved={refresh} settings={settings} />
          )}
        </div>
      </section>
    </main>
  );
}

function Dashboard({
  exchange,
  markets,
  onDone,
  performance,
  positions,
  scanner,
  stability,
  status,
}: {
  exchange: ExchangeSnapshot | null;
  markets: Market[];
  onDone: () => Promise<void>;
  performance: Performance | null;
  positions: Position[];
  scanner: ScannerResult[];
  stability: DemoStability | null;
  status: StatusPayload | null;
}) {
  const equitySeries = useMemo(
    () => buildEquitySeries(performance),
    [performance],
  );
  const chartSymbol =
    exchange?.positions[0]?.symbol ??
    status?.auto_trader?.last_symbol ??
    scanner.find((item) => item.action !== "NO_TRADE")?.symbol ??
    markets[0]?.symbol ??
    "BTCUSDT";
  const chartSymbols = useMemo(
    () =>
      Array.from(
        new Set([
          chartSymbol,
          ...markets.slice(0, 80).map((item) => item.symbol),
          ...scanner.slice(0, 40).map((item) => item.symbol),
        ]),
      ),
    [chartSymbol, markets, scanner],
  );
  return (
    <div className="grid gap-4">
      <ActivitySummary exchange={exchange} status={status} />
      <CommandCenter exchange={exchange} onDone={onDone} status={status} />
      <CriticalOverview
        exchange={exchange}
        performance={performance}
        positions={positions}
        status={status}
      />
      <MarketChart symbol={chartSymbol} symbols={chartSymbols} />
      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <OpenPositionsPanel positions={exchange?.positions ?? []} />
        <SignalFocus scanner={scanner} />
      </div>
      <DataPanel title="Đường vốn">
        <div className="mb-3 flex items-center justify-between gap-3">
          <span className="text-sm font-semibold text-slate-400">
            Số dư {money(performance?.balance)}
          </span>
          <span
            className={`text-sm font-black ${(performance?.realized_pnl ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}
          >
            Đã chốt {money(performance?.realized_pnl)}
          </span>
        </div>
        <EquityChart values={equitySeries} />
      </DataPanel>
      <StabilityPanel stability={stability} />
      <LiveReadinessPanel onDone={onDone} status={status} />
    </div>
  );
}

function CriticalOverview({
  exchange,
  performance,
  positions,
  status,
}: {
  exchange: ExchangeSnapshot | null;
  performance: Performance | null;
  positions: Position[];
  status: StatusPayload | null;
}) {
  const openPositions =
    exchange?.positions.length ??
    performance?.open_positions ??
    positions.length;
  const maxPositions = Math.max(status?.risk.max_open_positions ?? 1, 1);
  const positionUsage = (openPositions / maxPositions) * 100;
  const marginBalance =
    exchange?.balance.margin_balance ?? performance?.equity ?? 0;
  const available = exchange?.balance.available ?? 0;
  const usedMargin = Math.max(0, marginBalance - available);
  const marginUsage =
    marginBalance > 0 ? (usedMargin / marginBalance) * 100 : 0;
  const unrealized =
    exchange?.balance.unrealized_pnl ?? performance?.unrealized_pnl ?? 0;
  const realized = performance?.realized_pnl ?? 0;

  return (
    <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <div className="rounded-lg border border-cyan-300/20 bg-[#0d1724] p-4 shadow-sm shadow-cyan-950/30 md:p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-xs font-black uppercase text-cyan-300">
              Tài khoản DEMO realtime
            </p>
            <h3 className="mt-2 text-3xl font-black leading-tight md:text-4xl">
              {money(performance?.equity ?? exchange?.balance.margin_balance)}
            </h3>
            <p className="mt-2 text-sm font-semibold text-slate-400">
              Available {money(available)} / Balance{" "}
              {money(exchange?.balance.balance ?? performance?.balance)}
            </p>
          </div>
          <div className="grid min-w-[220px] gap-2">
            <Pill
              label="Mode"
              value={normalizeMode(status?.mode)}
              tone={status?.mode === "LIVE" ? "danger" : "safe"}
            />
            <Pill
              label="Exchange"
              value={viExchangeConnection(exchange?.connection)}
              tone={exchange?.connection === "CONNECTED" ? "safe" : "danger"}
            />
            <Pill
              label="Bot"
              value={viBotState(status?.bot_state)}
              tone={status?.bot_state === "RUNNING" ? "safe" : "neutral"}
            />
          </div>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-4">
          <Metric label="Vốn ban đầu" value={money(performance?.initial_capital)} />
          <Metric
            label="Lãi/lỗ ròng"
            value={money(performance?.net_pnl)}
            tone={(performance?.net_pnl ?? 0) >= 0 ? "good" : "bad"}
          />
          <Metric
            label="Tăng/giảm vốn"
            value={signedPercent(performance?.return_percent)}
            tone={(performance?.return_percent ?? 0) >= 0 ? "good" : "bad"}
          />
          <Metric
            label="Lãi/lỗ đang mở"
            value={money(unrealized)}
            tone={unrealized >= 0 ? "good" : "bad"}
          />
          <Metric label="Tổng lệnh" value={String(performance?.total_trades ?? 0)} />
          <Metric label="Lệnh thắng" value={String(performance?.winning_trades ?? 0)} tone="good" />
          <Metric label="Lệnh thua" value={String(performance?.losing_trades ?? 0)} tone="bad" />
          <Metric
            label="Tỷ lệ thắng"
            value={percent((performance?.win_rate ?? 0) * 100)}
          />
        </div>
      </div>
      <div className="grid gap-4">
        <RiskUsageCard
          label="Vị thế mở"
          maxLabel={`${openPositions}/${maxPositions}`}
          tone={positionUsage >= 100 ? "bad" : "good"}
          value={positionUsage}
        />
        <RiskUsageCard
          label="Margin đang dùng"
          maxLabel={`${money(usedMargin)} / ${money(marginBalance)}`}
          tone={
            marginUsage >= (status?.risk.max_total_margin ?? 0.3) * 100
              ? "bad"
              : "good"
          }
          value={marginUsage}
        />
        <RiskUsageCard
          label="Tổng risk cho phép"
          maxLabel={percent((status?.risk.max_total_open_risk ?? 0) * 100)}
          tone="neutral"
          value={Math.min(positionUsage, 100)}
        />
      </div>
    </section>
  );
}

function RiskUsageCard({
  label,
  maxLabel,
  tone,
  value,
}: {
  label: string;
  maxLabel: string;
  tone: "good" | "bad" | "neutral";
  value: number;
}) {
  const color =
    tone === "bad"
      ? "bg-red-400"
      : tone === "good"
        ? "bg-emerald-300"
        : "bg-cyan-300";
  return (
    <section className="rounded-lg border border-white/10 bg-[#0d1724] p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-black uppercase text-slate-400">{label}</p>
        <strong className="text-sm text-slate-100">{maxLabel}</strong>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${Math.max(0, Math.min(value, 100))}%` }}
        />
      </div>
    </section>
  );
}

function OpenPositionsPanel({
  positions,
}: {
  positions: ExchangeSnapshot["positions"];
}) {
  return (
    <DataPanel title="Vị thế đang mở">
      <div className="grid gap-3">
        {positions.length ? (
          positions.map((position) => (
            <article
              className="grid gap-3 rounded-md border border-white/10 bg-white/[0.03] p-3 md:grid-cols-[1fr_auto]"
              key={`${position.symbol}-${position.side}`}
            >
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="text-lg">{position.symbol}</strong>
                  <span
                    className={`rounded px-2 py-1 text-xs font-black ${position.side === "LONG" ? "bg-emerald-400/15 text-emerald-300" : "bg-red-400/15 text-red-300"}`}
                  >
                    {viSide(position.side)}
                  </span>
                  <span className="rounded bg-white/10 px-2 py-1 text-xs font-black text-slate-300">
                    {position.leverage ?? "-"}x
                  </span>
                </div>
                <p className="mt-2 text-sm font-semibold text-slate-400">
                  Entry {money(position.entry_price)} / Mark{" "}
                  {money(position.mark_price)} / Thanh lý{" "}
                  {money(position.liquidation_price)}
                </p>
              </div>
              <div className="text-left md:text-right">
                <p
                  className={`text-xl font-black ${position.unrealized_pnl >= 0 ? "text-emerald-300" : "text-red-300"}`}
                >
                  {money(position.unrealized_pnl)}
                </p>
                <p className="mt-1 text-xs font-semibold text-slate-400">
                  Qty {number(position.quantity)}
                </p>
              </div>
            </article>
          ))
        ) : (
          <EmptyState
            message="Bot chưa có vị thế mở trên exchange."
            title="Chưa có vị thế"
          />
        )}
      </div>
    </DataPanel>
  );
}

function SignalFocus({ scanner }: { scanner: ScannerResult[] }) {
  const candidates = scanner
    .filter((item) => item.action !== "NO_TRADE")
    .slice(0, 5);
  return (
    <DataPanel title="Tín hiệu đáng chú ý">
      <div className="grid gap-3">
        {candidates.length ? (
          candidates.map((item) => (
            <article
              className="rounded-md border border-white/10 bg-white/[0.03] p-3"
              key={`${item.symbol}-${item.timeframe}`}
            >
              <div className="flex items-center justify-between gap-3">
                <strong>{item.symbol}</strong>
                <span
                  className={`rounded px-2 py-1 text-xs font-black ${item.action === "LONG" ? "bg-emerald-400/15 text-emerald-300" : "bg-red-400/15 text-red-300"}`}
                >
                  {viAction(item.action)}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-sm">
                <InfoPair
                  label="Score"
                  value={String(Math.max(item.long_score, item.short_score))}
                />
                <InfoPair label="RR" value={number(item.risk_reward)} />
                <InfoPair label="TF" value={item.timeframe} />
              </div>
            </article>
          ))
        ) : (
          <EmptyState
            message="Scanner chưa có tín hiệu đủ điều kiện auto entry."
            title="Đang chờ"
          />
        )}
      </div>
    </DataPanel>
  );
}

function CommandCenter({
  exchange,
  onDone,
  status,
}: {
  exchange: ExchangeSnapshot | null;
  onDone: () => Promise<void>;
  status: StatusPayload | null;
}) {
  return (
    <section className="grid gap-4 rounded-lg border border-white/10 bg-[#0d1724] p-4 shadow-sm xl:grid-cols-[1.2fr_1fr]">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <ModeCard
          label="Trading mode"
          value={normalizeMode(status?.mode)}
          tone={status?.mode === "LIVE" ? "danger" : "warning"}
        />
        <ModeCard
          label="Exchange"
          value={viExchangeConnection(exchange?.connection)}
          tone={exchange?.connection === "CONNECTED" ? "safe" : "danger"}
        />
        <ModeCard
          label="LIVE gate"
          value={status?.live_readiness.allowed ? "READY" : "LOCKED"}
          tone={status?.live_readiness.allowed ? "warning" : "safe"}
        />
        <ModeCard
          label="Auto loop"
          value={viAutoStatus(status?.auto_trader?.last_status)}
          tone={
            status?.auto_trader?.last_status === "ORDER_SUBMITTED"
              ? "safe"
              : "warning"
          }
        />
      </div>
      <div className="flex flex-col justify-center gap-3 xl:items-end">
        <p className="max-w-xl text-sm font-semibold text-slate-400 xl:text-right">
          {status?.mode === "LIVE"
            ? "LIVE đang dùng tiền thật. Kiểm tra lệnh và rủi ro trước mọi thao tác."
            : "Đang ở môi trường an toàn. Có thể kiểm tra kết nối, signal và lệnh demo tại đây."}
        </p>
        <div className="flex flex-wrap items-center justify-start gap-2 xl:justify-end">
          <ModeSelector
            current={normalizeMode(status?.mode)}
            liveAllowed={status?.live_readiness.allowed ?? false}
            onDone={onDone}
          />
          <LiveQuickActions onDone={onDone} status={status} />
          <BotControls onDone={onDone} />
        </div>
      </div>
    </section>
  );
}

function MarketChart({
  symbol,
  symbols,
}: {
  symbol: string;
  symbols: string[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [interval, setInterval] = useState("15m");
  const [selectedSymbol, setSelectedSymbol] = useState(symbol);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const effectiveSymbol = symbols.includes(selectedSymbol)
    ? selectedSymbol
    : symbol;

  useEffect(() => {
    let alive = true;
    async function load() {
      setBusy(true);
      try {
        const response = await api.klines(effectiveSymbol, interval, 220);
        if (!alive) return;
        setCandles(response.items);
        setError(null);
      } catch (reason) {
        if (!alive) return;
        setError(
          reason instanceof Error ? reason.message : "Không tải được biểu đồ",
        );
      } finally {
        if (alive) setBusy(false);
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 5_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [effectiveSymbol, interval]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      height: 360,
      layout: { background: { color: "#0d1724" }, textColor: "#cbd5e1" },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.12)" },
        horzLines: { color: "rgba(148, 163, 184, 0.12)" },
      },
      rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.18)" },
      timeScale: {
        borderColor: "rgba(148, 163, 184, 0.18)",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: 1 },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#059669",
      downColor: "#dc2626",
      borderVisible: false,
      wickUpColor: "#059669",
      wickDownColor: "#dc2626",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return;
    seriesRef.current.setData(
      candles.map((item) => ({
        time: Math.floor(item.open_time / 1000) as Time,
        open: item.open,
        high: item.high,
        low: item.low,
        close: item.close,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  const last = candles.at(-1);
  const first = candles.at(0);
  const change =
    last && first ? ((last.close - first.open) / first.open) * 100 : null;

  return (
    <section className="rounded-lg border border-white/10 bg-[#0d1724] shadow-sm">
      <div className="flex flex-col gap-3 border-b border-white/10 p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs font-bold uppercase text-cyan-300">
            Biểu đồ coin
          </p>
          <div className="mt-1 flex flex-wrap items-end gap-3">
            <h3 className="text-xl font-black">{effectiveSymbol}</h3>
            <span className="text-sm font-bold text-slate-400">
              {last ? money(last.close) : "-"}
            </span>
            <span
              className={`text-sm font-bold ${(change ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}
            >
              {change === null ? "-" : signedPercent(change)}
            </span>
            <span className="rounded-full bg-emerald-400/15 px-2 py-1 text-[11px] font-black uppercase text-emerald-300">
              Realtime 5s
            </span>
          </div>
        </div>
        <div className="grid gap-2 md:flex md:flex-wrap md:items-center md:justify-end">
          <select
            className="min-h-9 rounded-md border border-white/15 bg-[#111c2b] px-3 text-sm font-bold text-slate-100"
            onChange={(event) => setSelectedSymbol(event.target.value)}
            value={effectiveSymbol}
          >
            {symbols.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <div className="grid grid-cols-5 gap-1 md:flex md:flex-wrap md:gap-2">
            {(["1m", "5m", "15m", "1h", "4h"] as const).map((value) => (
              <button
                className={`rounded-md px-2 py-2 text-xs font-black transition md:px-3 ${interval === value ? "bg-cyan-300 text-slate-950" : "bg-white/10 text-slate-300 hover:bg-white/15"}`}
                key={value}
                onClick={() => setInterval(value)}
                type="button"
              >
                {value}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="relative p-2 md:p-4">
        <div className="h-[300px] w-full md:h-[420px]" ref={containerRef} />
        {busy && (
          <div className="absolute right-5 top-5 rounded-full bg-[#0d1724]/90 px-3 py-1 text-xs font-bold text-slate-300 shadow">
            Đang tải
          </div>
        )}
        {error && (
          <div className="absolute inset-x-5 bottom-5 rounded-md border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-200">
            {error}
          </div>
        )}
      </div>
    </section>
  );
}

function ModeCard({
  label,
  tone,
  value,
}: {
  label: string;
  value: string;
  tone: "safe" | "warning" | "danger";
}) {
  const iconColor =
    tone === "safe"
      ? "text-emerald-300"
      : tone === "warning"
        ? "text-amber-300"
        : "text-red-300";
  return (
    <div className="rounded-md border border-white/10 bg-white/[0.03] p-4 transition hover:border-white/20">
      <div
        className={`mb-3 flex h-9 w-9 items-center justify-center rounded-md bg-white/10 ${iconColor}`}
      >
        {tone === "danger" ? (
          <ShieldAlert size={18} />
        ) : tone === "warning" ? (
          <Radio size={18} />
        ) : (
          <LockKeyhole size={18} />
        )}
      </div>
      <p className="text-xs font-bold uppercase text-slate-400">{label}</p>
      <strong className="mt-1 block break-words text-2xl leading-tight">
        {value}
      </strong>
    </div>
  );
}

function ActivitySummary({
  exchange,
  status,
}: {
  exchange: ExchangeSnapshot | null;
  status: StatusPayload | null;
}) {
  const isRunning = status?.bot_state === "RUNNING";
  const connected = exchange?.connection === "CONNECTED";
  const hasOrders = Boolean(exchange?.orders.length);
  const hasPositions = Boolean(exchange?.positions.length);
  const title =
    isRunning && connected
      ? "Bot đang online"
      : status?.safe_mode
        ? "Bot đang SAFE_MODE"
        : "Bot chưa sẵn sàng";
  const detail =
    hasOrders || hasPositions
      ? `Đang có ${exchange?.orders.length ?? 0} order và ${exchange?.positions.length ?? 0} vị thế trên ${exchange?.mode ?? status?.mode ?? "mode hiện tại"}.`
      : (status?.auto_trader?.last_reason ??
        "Backend đang chạy và kết nối exchange, nhưng hiện chưa có lệnh/vị thế mở.");
  const tone =
    status?.safe_mode || status?.emergency_stop
      ? "border-red-200 bg-red-50 text-red-800"
      : isRunning && connected
        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
        : "border-amber-200 bg-amber-50 text-amber-800";

  return (
    <section className={`rounded-lg border px-4 py-3 shadow-sm ${tone}`}>
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="font-bold">{title}</h3>
          <p className="mt-1 text-sm font-semibold opacity-80">{detail}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill
            label="Mode"
            value={status?.mode ?? "-"}
            tone={status?.mode === "LIVE" ? "danger" : "safe"}
          />
          <Pill
            label="Bot"
            value={viBotState(status?.bot_state)}
            tone={isRunning ? "safe" : "neutral"}
          />
          <Pill
            label="Exchange"
            value={viExchangeConnection(exchange?.connection)}
            tone={connected ? "safe" : "danger"}
          />
          <Pill
            label="Auto"
            value={viAutoStatus(status?.auto_trader?.last_status)}
            tone={
              status?.auto_trader?.last_status === "ORDER_SUBMITTED"
                ? "safe"
                : "neutral"
            }
          />
        </div>
      </div>
    </section>
  );
}

function StabilityPanel({ stability }: { stability: DemoStability | null }) {
  const incidents =
    stability?.incidents.filter((item) => item.status === "OPEN") ?? [];
  const labels: Record<string, string> = {
    sample_size: "Số lệnh",
    sample_duration: "Thời gian",
    positive_expectancy: "Expectancy",
    sl_protection: "Bảo vệ SL",
    user_stream: "User stream",
    reconciliation: "Đối soát",
    duplicate_orders: "Trùng order",
    order_ownership: "Ownership",
    safe_mode: "Safe mode",
  };
  return (
    <DataPanel title="DEMO stability & incidents">
      <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
        <div className="rounded-md border border-cyan-300/20 bg-cyan-300/[0.04] p-4">
          <p className="text-xs font-black uppercase text-slate-400">
            Readiness score
          </p>
          <p className="mt-2 text-4xl font-black text-cyan-200">
            {stability?.score ?? 0}/100
          </p>
          <p
            className={`mt-2 text-sm font-black ${stability?.verdict === "READY" ? "text-emerald-300" : "text-amber-300"}`}
          >
            {stability?.verdict ?? "LOADING"}
          </p>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-cyan-300"
              style={{ width: `${stability?.score ?? 0}%` }}
            />
          </div>
          <p className="mt-3 text-xs font-semibold text-slate-400">
            {String(stability?.metrics.trades ?? 0)}/50 lệnh ·{" "}
            {Number(stability?.metrics.sample_days ?? 0).toFixed(2)}/7 ngày
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {Object.entries(stability?.checks ?? {}).map(([key, check]) => (
            <div
              className={`rounded-md border p-3 ${check.passed ? "border-emerald-400/20 bg-emerald-400/[0.04]" : "border-amber-400/20 bg-amber-400/[0.04]"}`}
              key={key}
            >
              <div className="flex items-center justify-between gap-2">
                <strong className="text-sm">{labels[key] ?? key}</strong>
                <span
                  className={
                    check.passed ? "text-emerald-300" : "text-amber-300"
                  }
                >
                  {check.passed ? "PASS" : "WAIT"}
                </span>
              </div>
              <p className="mt-2 text-xs font-semibold text-slate-400">
                {check.detail}
              </p>
            </div>
          ))}
        </div>
      </div>
      <div className="mt-4 border-t border-white/10 pt-4">
        <div className="flex items-center justify-between gap-3">
          <strong className="text-sm">Incident đang mở</strong>
          <Pill
            label="Active"
            value={String(incidents.length)}
            tone={
              incidents.some((item) => item.severity === "CRITICAL")
                ? "danger"
                : incidents.length
                  ? "neutral"
                  : "safe"
            }
          />
        </div>
        <div className="mt-3 grid gap-2">
          {incidents.length ? (
            incidents.slice(0, 5).map((incident) => (
              <div
                className="rounded-md border border-red-400/20 bg-red-400/[0.05] p-3"
                key={incident.id}
              >
                <div className="flex justify-between gap-3">
                  <strong className="text-sm text-red-200">
                    {incident.key}
                  </strong>
                  <span className="text-xs font-black text-red-300">
                    {incident.severity}
                  </span>
                </div>
                <p className="mt-1 text-xs font-semibold text-slate-400">
                  {incident.message}
                </p>
              </div>
            ))
          ) : (
            <p className="text-sm font-semibold text-emerald-300">
              Không có incident vận hành đang mở.
            </p>
          )}
        </div>
      </div>
    </DataPanel>
  );
}

function LiveReadinessPanel({
  onDone,
  status,
}: {
  onDone: () => Promise<void>;
  status: StatusPayload | null;
}) {
  const readiness = status?.live_readiness;
  async function toggleLive(enabled: boolean) {
    await api.liveConfig({ live_enabled: enabled });
    await onDone();
  }
  const checks = readiness
    ? [
        ["All tests", readiness.all_tests_pass],
        ["Demo stable", readiness.demo_stable],
        ["SL protection", readiness.sl_protection_pass],
        ["Reconnect", readiness.reconnect_pass],
        ["Reconciliation", readiness.reconciliation_pass],
        ["Duplicate order", readiness.duplicate_order_tests_pass],
      ]
    : [];
  return (
    <DataPanel title="LIVE readiness">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Pill
          label="Runtime LIVE"
          value={readiness?.live_enabled ? "ON" : "OFF"}
          tone={readiness?.live_enabled ? "danger" : "safe"}
        />
        <button
          className="inline-flex items-center gap-2 rounded-md border border-white/15 bg-white/10 px-3 py-2 text-sm font-bold text-slate-100 hover:bg-white/15 disabled:opacity-50"
          disabled={
            readiness?.allowed !== true && readiness?.live_enabled !== true
          }
          onClick={() => void toggleLive(!(readiness?.live_enabled ?? false))}
          type="button"
        >
          <Zap size={16} />
          {readiness?.live_enabled ? "Tắt LIVE gate" : "Bật LIVE gate"}
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {checks.map(([label, ok]) => (
          <Pill
            key={String(label)}
            label={String(label)}
            value={ok ? "PASS" : "BLOCK"}
            tone={ok ? "safe" : "danger"}
          />
        ))}
      </div>
      {readiness?.blockers.length ? (
        <p className="mt-3 text-sm font-semibold text-red-300">
          {readiness.blockers.join(" / ")}
        </p>
      ) : null}
    </DataPanel>
  );
}

function Markets({ markets }: { markets: Market[] }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<keyof Market>("quote_volume");
  const rows = useMemo(
    () =>
      markets
        .filter((item) => item.symbol.includes(query.toUpperCase()))
        .sort((a, b) => Number(b[sort] ?? 0) - Number(a[sort] ?? 0)),
    [markets, query, sort],
  );
  return (
    <DataPanel
      controls={
        <TableControls
          query={query}
          setQuery={setQuery}
          sort={sort}
          setSort={setSort}
          sortOptions={[
            "quote_volume",
            "price_change_percent",
            "spread_bps",
            "funding_rate",
          ]}
        />
      }
      title="Thị trường"
    >
      <Table
        columns={[
          "Mã",
          "Giá",
          "24h%",
          "Khối lượng",
          "Chênh lệch",
          "Phí funding",
          "Tuổi niêm yết",
        ]}
        rows={rows.map((item) => [
          item.symbol,
          money(item.last_price),
          signedPercent(item.price_change_percent),
          compact(item.quote_volume),
          `${item.spread_bps.toFixed(2)} bps`,
          percent(item.funding_rate * 100),
          item.listing_age_days
            ? `${Math.floor(item.listing_age_days)} ngày`
            : "-",
        ])}
      />
    </DataPanel>
  );
}

function Scanner({ scanner }: { scanner: ScannerResult[] }) {
  const [query, setQuery] = useState("");
  const [signal, setSignal] = useState("ALL");
  const rows = scanner.filter(
    (item) =>
      item.symbol.includes(query.toUpperCase()) &&
      (signal === "ALL" || item.action === signal),
  );
  return (
    <DataPanel
      controls={
        <div className="flex flex-wrap gap-2">
          <SearchBox query={query} setQuery={setQuery} />
          <select
            className="rounded-md border border-white/15 bg-[#111c2b] px-3 py-2 text-sm text-slate-100"
            onChange={(event) => setSignal(event.target.value)}
            value={signal}
          >
            <option value="ALL">Tất cả</option>
            <option>LONG</option>
            <option>SHORT</option>
            <option value="NO_TRADE">Không vào lệnh</option>
          </select>
        </div>
      }
      title="Quét tín hiệu realtime"
    >
      <Table
        columns={[
          "Mã",
          "Giá",
          "24h%",
          "Khối lượng",
          "Trạng thái thị trường",
          "Điểm Long",
          "Điểm Short",
          "Tín hiệu",
          "ATR",
          "Phí funding",
        ]}
        rows={rows.map((item) => [
          item.symbol,
          money(item.price),
          signedPercent(item.price_change_percent),
          compact(item.quote_volume),
          viRegime(item.regime),
          String(item.long_score),
          String(item.short_score),
          viAction(item.action),
          number(item.indicators.atr),
          percent(item.funding_rate * 100),
        ])}
      />
    </DataPanel>
  );
}

function Positions({
  markets,
  positions,
}: {
  markets: Market[];
  positions: Position[];
}) {
  const marks = new Map(markets.map((item) => [item.symbol, item.last_price]));
  return (
    <DataPanel title="Vị thế">
      <Table
        columns={[
          "Mã",
          "Hướng",
          "Giá vào",
          "Giá hiện tại",
          "Khối lượng",
          "SL",
          "TP",
          "PNL",
          "ROE",
        ]}
        rows={positions.map((item) => {
          const current =
            item.mark_price ?? marks.get(item.symbol) ?? item.entry_price;
          const pnl =
            item.unrealized_pnl ??
            (item.side === "LONG"
              ? (current - item.entry_price) * item.remaining_quantity
              : (item.entry_price - current) * item.remaining_quantity);
          const cost = item.entry_price * item.remaining_quantity;
          return [
            item.symbol,
            viSide(item.side),
            money(item.entry_price),
            money(current),
            number(item.remaining_quantity),
            money(item.stop_loss),
            item.take_profits.map(money).join(" / "),
            money(pnl),
            percent((pnl / cost) * 100),
          ];
        })}
      />
    </DataPanel>
  );
}

function Trades({ trades }: { trades: Trade[] }) {
  const [query, setQuery] = useState("");
  const [side, setSide] = useState("ALL");
  const [result, setResult] = useState("ALL");
  const rows = trades.filter((trade) => {
    const okQuery = trade.symbol.includes(query.toUpperCase());
    const okSide = side === "ALL" || trade.side === side;
    const okResult =
      result === "ALL" ||
      (result === "WIN" ? trade.net_pnl > 0 : trade.net_pnl <= 0);
    return okQuery && okSide && okResult;
  });
  return (
    <DataPanel
      controls={
        <div className="flex flex-wrap gap-2">
          <SearchBox query={query} setQuery={setQuery} />
          <select
            className="rounded-md border border-white/15 bg-[#111c2b] px-3 py-2 text-sm text-slate-100"
            onChange={(event) => setSide(event.target.value)}
            value={side}
          >
            <option value="ALL">Tất cả</option>
            <option>LONG</option>
            <option>SHORT</option>
          </select>
          <select
            className="rounded-md border border-white/15 bg-[#111c2b] px-3 py-2 text-sm text-slate-100"
            onChange={(event) => setResult(event.target.value)}
            value={result}
          >
            <option value="ALL">Tất cả</option>
            <option value="WIN">Thắng</option>
            <option value="LOSS">Thua</option>
          </select>
        </div>
      }
      title="Lệnh đã chốt"
    >
      <Table
        columns={[
          "Mã",
          "Hướng",
          "Thời gian",
          "Giá vào",
          "Giá thoát",
          "Khối lượng",
          "PNL ròng",
          "Phí",
          "Lý do",
          "Kết quả",
        ]}
        rows={rows.map((trade) => [
          trade.symbol,
          viSide(trade.side),
          new Date(trade.created_at).toLocaleString("vi-VN"),
          trade.entry_price > 0 ? money(trade.entry_price) : "-",
          trade.exit_price > 0 ? money(trade.exit_price) : "-",
          trade.quantity > 0 ? number(trade.quantity) : "-",
          money(trade.net_pnl),
          money(trade.fee),
          viCloseReason(trade.reason),
          trade.net_pnl > 0 ? "Thắng" : "Thua",
        ])}
      />
    </DataPanel>
  );
}

function viCloseReason(reason: string): string {
  const value = reason.toUpperCase();
  if (value === "TP" || value.includes("TAKE_PROFIT")) return "Chốt lời theo mục tiêu";
  if (value === "SL" || value.includes("STOP")) return "Chạm Stop Loss";
  if (value === "LIQUIDATION") return "Thanh lý vị thế";
  if (value === "REALIZED_PNL") return "Đóng vị thế đã khớp";
  return reason || "Đóng vị thế thủ công hoặc theo thị trường";
}

function Strategies({ scanner }: { scanner: ScannerResult[] }) {
  const strategies = [
    {
      name: "Trend Pullback",
      rule: "Đi theo trend EMA20/50/200, chờ pullback có MACD/ADX/volume xác nhận.",
      entry:
        "Ưu tiên khi Long/Short score >= ngưỡng, RR >= 1.8, ATR không quá nóng.",
    },
    {
      name: "Breakout",
      rule: "Bắt phá vùng Bollinger/VWAP khi volume tăng và spread còn thấp.",
      entry: "Chỉ vào khi breakout cùng hướng, có SL theo ATR và đủ 3 TP.",
    },
  ];
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {strategies.map((strategy) => {
        const active = scanner.filter(
          (item) => item.strategy === strategy.name,
        );
        const best = [...active].sort(
          (a, b) =>
            Math.max(b.long_score, b.short_score) -
            Math.max(a.long_score, a.short_score),
        )[0];
        return (
          <section
            className="rounded-lg border border-white/10 bg-[#0d1724] p-4"
            key={strategy.name}
          >
            <h3 className="font-bold">{strategy.name}</h3>
            <p className="mt-2 text-sm font-semibold text-slate-300">
              {strategy.rule}
            </p>
            <p className="mt-1 text-sm text-slate-400">{strategy.entry}</p>
            <div className="mt-4 grid gap-2 text-sm">
              <InfoPair
                label="Tín hiệu đang đạt"
                value={String(active.length)}
              />
              <InfoPair
                label="Kèo tốt nhất"
                value={
                  best
                    ? `${best.symbol} ${viAction(best.action)} ${Math.max(best.long_score, best.short_score)}/100`
                    : "Chưa có"
                }
              />
              <InfoPair
                label="RR"
                value={best?.risk_reward ? number(best.risk_reward) : "-"}
              />
            </div>
          </section>
        );
      })}
    </div>
  );
}

function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-white/[0.04] px-3 py-2">
      <span className="font-bold text-slate-400">{label}</span>
      <strong className="text-right">{value}</strong>
    </div>
  );
}

function Analytics({
  performance,
  trades,
}: {
  performance: Performance | null;
  trades: Trade[];
}) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Metric label="Vốn ban đầu" value={money(performance?.initial_capital)} />
      <Metric label="Vốn hiện tại" value={money(performance?.balance)} />
      <Metric label="Lãi/lỗ ròng" value={money(performance?.net_pnl)} />
      <Metric label="Tăng/giảm vốn" value={signedPercent(performance?.return_percent)} />
      <Metric label="Lãi/lỗ gồm vị thế mở" value={money(performance?.equity_pnl)} />
      <Metric label="Phí" value={money(performance?.fees_paid)} />
      <Metric label="Phí funding" value={money(performance?.funding_paid)} />
      <Metric label="Profit Factor" value={profitFactor(performance)} />
      <Metric label="DD" value={money(performance?.max_drawdown)} />
      <Metric label="Sharpe" value={number(performance?.sharpe)} />
      <Metric label="Sortino" value={number(performance?.sortino)} />
      <Metric label="Expectancy" value={money(performance?.expectancy)} />
      <Metric
        label="Tỷ lệ thắng"
        value={percent((performance?.win_rate ?? 0) * 100)}
      />
      <Metric label="Tổng lệnh" value={String(performance?.total_trades ?? 0)} />
      <Metric label="Lệnh thắng" value={String(performance?.winning_trades ?? 0)} />
      <Metric label="Lệnh thua" value={String(performance?.losing_trades ?? 0)} />
      <BacktestPanel />
      <section className="rounded-lg border border-white/10 bg-[#0d1724] p-4 md:col-span-3">
        <h3 className="mb-3 font-bold">Phân bổ kết quả lệnh</h3>
        <Table
          columns={["Kết quả", "Số lượng"]}
          rows={[
            ["Thắng", String(trades.filter((item) => item.net_pnl > 0).length)],
            ["Thua", String(trades.filter((item) => item.net_pnl <= 0).length)],
          ]}
        />
      </section>
    </div>
  );
}

function BacktestPanel() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("15m");
  const [candidateScore, setCandidateScore] = useState(75);
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState("");
  async function run() {
    setRunning(true);
    setMessage("");
    try {
      setReport(
        await api.runBacktest({
          symbol: symbol.toUpperCase(), interval, limit: 1000,
          baseline: { name: "Baseline", min_score: 70, risk_fraction: 0.005, stop_atr_multiplier: 1.2, take_profit_r_multiples: [1, 1.8, 2.6], take_profit_fractions: [0.4, 0.3, 0.3] },
          candidate: { name: "Candidate", min_score: candidateScore, risk_fraction: 0.005, stop_atr_multiplier: 1.2, take_profit_r_multiples: [1, 1.8, 2.6], take_profit_fractions: [0.4, 0.3, 0.3] },
        }),
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Không chạy được backtest");
    } finally { setRunning(false); }
  }
  const cards = report ? [report.baseline, report.candidate].filter((item): item is NonNullable<typeof item> => item !== null) : [];
  return (
    <section className="rounded-lg border border-white/10 bg-[#0d1724] p-4 md:col-span-3">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div><label className="mb-1 block text-xs text-slate-400">Cặp</label><input className="rounded border border-white/10 bg-[#08111d] px-3 py-2" value={symbol} onChange={(event) => setSymbol(event.target.value)} /></div>
        <div><label className="mb-1 block text-xs text-slate-400">Khung</label><select className="rounded border border-white/10 bg-[#08111d] px-3 py-2" value={interval} onChange={(event) => setInterval(event.target.value)}><option>5m</option><option>15m</option><option>1h</option><option>4h</option></select></div>
        <div><label className="mb-1 block text-xs text-slate-400">Score Candidate</label><input className="w-28 rounded border border-white/10 bg-[#08111d] px-3 py-2" type="number" min={0} max={100} value={candidateScore} onChange={(event) => setCandidateScore(Number(event.target.value))} /></div>
        <button className="rounded bg-cyan-500 px-4 py-2 font-bold text-slate-950 disabled:opacity-50" disabled={running} onClick={run} type="button">{running ? "Đang chạy…" : "Chạy so sánh"}</button>
      </div>
      <p className="mb-4 text-xs text-amber-300">Candidate chỉ dùng để thử nghiệm, không tự áp dụng vào DEMO/LIVE. Khớp ở nến kế tiếp và ưu tiên SL khi cùng nến chạm SL/TP.</p>
      {message && <p className="text-sm text-red-300">{message}</p>}
      {report && <div className="mb-3 text-xs text-slate-500">{report.symbol} · {report.interval} · {report.candle_count} nến · dữ liệu {report.dataset_fingerprint.slice(0, 12)}</div>}
      <div className="grid gap-4 md:grid-cols-2">{cards.map((item) => <div className="rounded border border-white/10 p-4" key={item.config_fingerprint}><h4 className="mb-3 font-black">{item.config.name}</h4><div className="grid grid-cols-2 gap-2 text-sm"><span>PNL</span><b>{money(item.metrics.pnl)}</b><span>Profit Factor</span><b>{number(item.metrics.profit_factor)}</b><span>Max DD</span><b>{percent(item.max_drawdown_percent)}</b><span>Expectancy</span><b>{money(item.metrics.expectancy)}</b><span>Winrate</span><b>{percent(item.metrics.winrate * 100)}</b><span>Average R</span><b>{number(item.average_r)}</b><span>Sharpe / Sortino</span><b>{number(item.metrics.sharpe)} / {number(item.metrics.sortino)}</b><span>OOS trades</span><b>{item.metrics.out_of_sample_trades}</b></div></div>)}</div>
    </section>
  );
}

function Risk({
  onDone,
  status,
}: {
  onDone: () => Promise<void>;
  status: StatusPayload | null;
}) {
  const risk = status?.risk;
  const readiness = status?.live_readiness;
  async function setCheck(
    key: keyof StatusPayload["live_readiness"],
    value: boolean,
  ) {
    await api.liveConfig({ [key]: value });
    await onDone();
  }
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 md:grid-cols-3">
        <Metric
          label="Rủi ro mỗi lệnh"
          value={percent((risk?.risk_per_trade ?? 0) * 100)}
        />
        <Metric
          label="Rủi ro tối đa mỗi lệnh"
          value={percent((risk?.max_risk_per_trade ?? 0) * 100)}
        />
        <Metric
          label="Tổng rủi ro mở"
          value={percent((risk?.max_total_open_risk ?? 0) * 100)}
        />
        <Metric
          label="Margin mỗi lệnh"
          value={percent((risk?.max_margin_per_trade ?? 0) * 100)}
        />
        <Metric
          label="Tổng margin"
          value={percent((risk?.max_total_margin ?? 0) * 100)}
        />
        <Metric
          label="Lỗ tối đa mỗi ngày"
          value={percent((risk?.max_daily_loss ?? 0) * 100)}
        />
        <Metric
          label="Weekly DD"
          value={percent((risk?.max_weekly_drawdown ?? 0) * 100)}
        />
        <Metric
          label="Vị thế tối đa"
          value={String(risk?.max_open_positions ?? "-")}
        />
        <Metric
          label="Đòn bẩy tối đa"
          value={`${risk?.max_leverage ?? "-"}x`}
        />
        <Metric
          label="Exposure tối đa"
          value={percent((risk?.max_portfolio_exposure ?? 0) * 100)}
        />
        <Metric
          label="Correlation tối đa"
          value={String(risk?.max_correlated_positions ?? "-")}
        />
        <Metric
          label="Loss streak"
          value={String(risk?.max_loss_streak ?? "-")}
        />
        <Metric
          label="RR tối thiểu"
          value={number(risk?.minimum_risk_reward)}
        />
      </div>
      <DataPanel title="LIVE preflight">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(
            [
              ["all_tests_pass", "All tests pass"],
              ["demo_stable", "Demo stable"],
              ["sl_protection_pass", "SL protection"],
              ["reconnect_pass", "Reconnect"],
              ["reconciliation_pass", "Reconciliation"],
              ["duplicate_order_tests_pass", "Duplicate order"],
            ] as const
          ).map(([key, label]) => (
            <label
              className="flex items-center justify-between gap-3 rounded-md border border-white/10 bg-white/[0.03] px-3 py-3 text-sm font-bold"
              key={key}
            >
              <span>{label}</span>
              <input
                checked={Boolean(readiness?.[key])}
                onChange={(event) => void setCheck(key, event.target.checked)}
                type="checkbox"
              />
            </label>
          ))}
        </div>
        {readiness?.blockers.length ? (
          <p className="mt-3 text-sm font-semibold text-red-300">
            {readiness.blockers.join(" / ")}
          </p>
        ) : null}
      </DataPanel>
    </div>
  );
}

function Logs({ logs }: { logs: LogItem[] }) {
  return (
    <DataPanel title="Nhật ký">
      <Table
        columns={["Thời gian", "Cấp độ", "Nội dung"]}
        rows={logs.map((item) => [
          new Date(item.created_at).toLocaleString("vi-VN"),
          item.level,
          item.message,
        ])}
      />
    </DataPanel>
  );
}

function SettingsPage({
  settings,
  onSaved,
}: {
  settings: BotSettings;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    await api.updateSettings(draft);
    await onSaved();
    setSaving(false);
  }
  return (
    <section className="rounded-lg border border-white/10 bg-[#0d1724] p-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <NumberField
          label="Khối lượng tối thiểu"
          value={draft.min_quote_volume}
          onChange={(value) => setDraft({ ...draft, min_quote_volume: value })}
        />
        <NumberField
          label="Spread tối đa bps"
          value={draft.max_spread_bps}
          onChange={(value) => setDraft({ ...draft, max_spread_bps: value })}
        />
        <NumberField
          label="Tuổi niêm yết tối thiểu"
          value={draft.min_listing_age_days}
          onChange={(value) =>
            setDraft({ ...draft, min_listing_age_days: value })
          }
        />
        <NumberField
          label="Điểm vào lệnh tối thiểu"
          value={draft.min_score_to_trade}
          onChange={(value) =>
            setDraft({ ...draft, min_score_to_trade: value })
          }
        />
        <NumberField
          label="Phí taker"
          value={draft.taker_fee_rate}
          step={0.0001}
          onChange={(value) => setDraft({ ...draft, taker_fee_rate: value })}
        />
        <NumberField
          label="Trượt giá bps"
          value={draft.slippage_bps}
          onChange={(value) => setDraft({ ...draft, slippage_bps: value })}
        />
        <NumberField
          label="Rủi ro mỗi lệnh"
          value={draft.risk_per_trade}
          step={0.0005}
          onChange={(value) => setDraft({ ...draft, risk_per_trade: value })}
        />
        <NumberField
          label="Rủi ro tối đa mỗi lệnh"
          value={draft.max_risk_per_trade}
          step={0.001}
          onChange={(value) =>
            setDraft({ ...draft, max_risk_per_trade: value })
          }
        />
        <NumberField
          label="Tổng rủi ro mở"
          value={draft.max_total_open_risk}
          step={0.001}
          onChange={(value) =>
            setDraft({ ...draft, max_total_open_risk: value })
          }
        />
        <NumberField
          label="Margin mỗi lệnh"
          value={draft.max_margin_per_trade}
          step={0.01}
          onChange={(value) =>
            setDraft({ ...draft, max_margin_per_trade: value })
          }
        />
        <NumberField
          label="Tổng margin"
          value={draft.max_total_margin}
          step={0.01}
          onChange={(value) => setDraft({ ...draft, max_total_margin: value })}
        />
        <NumberField
          label="Daily loss"
          value={draft.max_daily_loss}
          step={0.001}
          onChange={(value) => setDraft({ ...draft, max_daily_loss: value })}
        />
        <NumberField
          label="Weekly DD"
          value={draft.max_weekly_drawdown}
          step={0.001}
          onChange={(value) =>
            setDraft({ ...draft, max_weekly_drawdown: value })
          }
        />
        <NumberField
          label="Đòn bẩy tối đa"
          value={draft.max_leverage}
          onChange={(value) => setDraft({ ...draft, max_leverage: value })}
        />
        <NumberField
          label="Vị thế tối đa"
          value={draft.max_open_positions}
          onChange={(value) =>
            setDraft({ ...draft, max_open_positions: value })
          }
        />
      </div>
      <div className="mt-4 flex justify-end">
        <button
          className="rounded-md bg-cyan-300 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-60"
          disabled={saving}
          onClick={() => void save()}
          type="button"
        >
          Lưu cài đặt
        </button>
      </div>
    </section>
  );
}

function BotControls({ onDone }: { onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  async function act(action: "start" | "pause" | "stop") {
    setBusy(action);
    try {
      await api.bot(action);
      await onDone();
    } finally {
      setBusy(null);
    }
  }
  async function control(
    action: "pause-new-trades" | "cancel-orders" | "close-all",
  ) {
    if (
      action !== "pause-new-trades" &&
      !window.confirm(
        action === "close-all"
          ? "Đóng toàn bộ vị thế đang mở?"
          : "Hủy toàn bộ order đang chờ?",
      )
    )
      return;
    setBusy(action);
    try {
      await api.control(action);
      await onDone();
    } finally {
      setBusy(null);
    }
  }
  async function emergency() {
    if (!window.confirm("Bật Emergency Stop và khóa bot ngay?")) return;
    setBusy("emergency");
    try {
      await api.emergencyStop();
      await onDone();
    } finally {
      setBusy(null);
    }
  }
  const disabled = busy !== null;
  return (
    <div className="flex flex-wrap gap-2">
      <div className="flex rounded-md border border-white/15 bg-white/10 p-1 shadow-sm">
        <ActionIcon
          busy={busy === "start"}
          disabled={disabled}
          label="Chạy bot"
          onClick={() => void act("start")}
          tone="safe"
        >
          <Play size={16} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "pause"}
          disabled={disabled}
          label="Tạm dừng bot"
          onClick={() => void act("pause")}
          tone="warning"
        >
          <Pause size={16} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "stop"}
          disabled={disabled}
          label="Dừng bot"
          onClick={() => void act("stop")}
          tone="danger"
        >
          <Square size={16} />
        </ActionIcon>
      </div>
      <div className="flex rounded-md border border-red-400/30 bg-white/10 p-1 shadow-sm">
        <ActionIcon
          busy={busy === "pause-new-trades"}
          disabled={disabled}
          label="Tạm dừng lệnh mới"
          onClick={() => void control("pause-new-trades")}
          tone="warning"
        >
          <ShieldX size={16} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "cancel-orders"}
          disabled={disabled}
          label="Hủy order"
          onClick={() => void control("cancel-orders")}
          tone="orange"
        >
          <XCircle size={16} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "close-all"}
          disabled={disabled}
          label="Đóng toàn bộ vị thế"
          onClick={() => void control("close-all")}
          tone="danger"
        >
          <Trash2 size={16} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "emergency"}
          disabled={disabled}
          label="Emergency Stop"
          onClick={() => void emergency()}
          tone="solidDanger"
        >
          <ShieldAlert size={16} />
        </ActionIcon>
      </div>
    </div>
  );
}

function ActionIcon({
  busy,
  children,
  disabled,
  label,
  onClick,
  tone,
}: {
  busy: boolean;
  children: React.ReactNode;
  disabled: boolean;
  label: string;
  onClick: () => void;
  tone: "safe" | "warning" | "orange" | "danger" | "solidDanger";
}) {
  const toneClass: Record<
    "safe" | "warning" | "orange" | "danger" | "solidDanger",
    string
  > = {
    safe: "text-emerald-300 hover:bg-emerald-400/10",
    warning: "text-amber-300 hover:bg-amber-400/10",
    orange: "text-orange-300 hover:bg-orange-400/10",
    danger: "text-red-300 hover:bg-red-400/10",
    solidDanger: "bg-red-700 text-white hover:bg-red-800",
  };
  return (
    <button
      aria-label={label}
      className={`grid h-9 w-9 place-items-center rounded transition disabled:cursor-not-allowed disabled:opacity-50 ${toneClass[tone]}`}
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {busy ? <RefreshCw className="animate-spin" size={16} /> : children}
    </button>
  );
}

function LiveQuickActions({
  onDone,
  status,
}: {
  onDone: () => Promise<void>;
  status: StatusPayload | null;
}) {
  const [busy, setBusy] = useState(false);
  async function prepare() {
    setBusy(true);
    try {
      const response = await api.prepareLive();
      if (!response.accepted && response.reason) {
        window.alert(response.reason);
      }
      await onDone();
    } finally {
      setBusy(false);
    }
  }
  async function goLive() {
    if (
      !window.confirm(
        "Chuyển sang LIVE sẽ cho bot dùng tài khoản thật. Chỉ tiếp tục khi Boss đã kiểm tra rủi ro.",
      )
    )
      return;
    setBusy(true);
    try {
      await api.mode("LIVE");
      await onDone();
    } finally {
      setBusy(false);
    }
  }
  if (status?.mode === "LIVE") {
    return <Pill label="LIVE" value="Đang chạy tiền thật" tone="danger" />;
  }
  return (
    <div className="flex rounded-md border border-amber-400/30 bg-amber-400/10 p-1 shadow-sm">
      <button
        className="min-h-9 rounded px-3 text-xs font-black text-amber-200 transition hover:bg-amber-400/15 disabled:opacity-50"
        disabled={busy}
        onClick={() => void prepare()}
        type="button"
      >
        {busy ? "Đang kiểm tra" : "Chuẩn bị LIVE"}
      </button>
      <button
        className="min-h-9 rounded bg-red-700 px-3 text-xs font-black text-white transition hover:bg-red-800 disabled:opacity-50"
        disabled={busy || !status?.live_readiness.allowed}
        onClick={() => void goLive()}
        title={
          !status?.live_readiness.allowed
            ? "Cần chuẩn bị LIVE trước"
            : "Chuyển sang LIVE"
        }
        type="button"
      >
        LIVE
      </button>
    </div>
  );
}

function StatusLine({
  exchange,
  isRefreshing,
  lastLiveAt,
  status,
  wsState,
}: {
  exchange: ExchangeSnapshot | null;
  isRefreshing: boolean;
  lastLiveAt: number;
  status: StatusPayload | null;
  wsState: WsState;
}) {
  const parts = [
    status ? `Mode ${status.mode}` : "Đang tải trạng thái",
    `Realtime ${viWsState(wsState)}`,
    exchange
      ? `Exchange ${viExchangeConnection(exchange.connection)}`
      : "Exchange -",
    lastLiveAt > 0
      ? `Cập nhật ${new Date(lastLiveAt).toLocaleTimeString("vi-VN")}`
      : null,
  ].filter(Boolean);
  return (
    <p
      className="mt-1 max-w-3xl truncate text-sm font-semibold text-slate-400"
      title={parts.join(" • ")}
    >
      {isRefreshing ? "Đang đồng bộ dữ liệu..." : parts.join(" • ")}
    </p>
  );
}

function LoadingGrid() {
  return (
    <div
      className="mb-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4"
      aria-label="Đang tải dữ liệu"
    >
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          className="h-24 animate-pulse rounded-lg border border-white/10 bg-white/[0.04] p-4 shadow-sm"
          key={index}
        >
          <div className="h-3 w-24 rounded bg-white/10" />
          <div className="mt-4 h-7 w-32 rounded bg-white/10" />
        </div>
      ))}
    </div>
  );
}

function ModeSelector({
  current,
  liveAllowed,
  onDone,
}: {
  current: "DEMO" | "LIVE";
  liveAllowed: boolean;
  onDone: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  async function change(mode: "DEMO" | "LIVE") {
    if (mode === current) return;
    if (
      mode === "LIVE" &&
      !window.confirm(
        "Chuyển sang LIVE sẽ dùng tài khoản thật. Boss xác nhận tiếp tục?",
      )
    )
      return;
    setBusy(true);
    try {
      await api.mode(mode);
      await onDone();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex rounded-md border border-white/15 bg-white/10 p-1 shadow-sm">
      {(["DEMO", "LIVE"] as const).map((mode) => (
        <button
          className={`min-h-8 rounded px-3 py-1 text-xs font-black transition ${current === mode ? "bg-cyan-300 text-slate-950" : "text-slate-300 hover:bg-white/10 disabled:text-slate-600 disabled:hover:bg-transparent"}`}
          disabled={busy || (mode === "LIVE" && !liveAllowed)}
          key={mode}
          onClick={() => void change(mode)}
          title={
            mode === "LIVE" && !liveAllowed
              ? "LIVE đang bị khóa bởi preflight"
              : `Đổi sang ${mode}`
          }
          type="button"
        >
          {mode}
        </button>
      ))}
    </div>
  );
}

function DataPanel({
  children,
  controls,
  title,
}: {
  children: React.ReactNode;
  controls?: React.ReactNode;
  title: string;
}) {
  return (
    <section className="rounded-lg border border-white/10 bg-[#0d1724] shadow-sm">
      <div className="flex flex-col gap-3 border-b border-white/10 p-3 md:p-4 xl:flex-row xl:items-center xl:justify-between">
        <h3 className="text-base font-bold">{title}</h3>
        {controls}
      </div>
      <div className="overflow-x-auto p-3 md:p-4">{children}</div>
    </section>
  );
}

function Table({ columns, rows }: { columns: string[]; rows: string[][] }) {
  if (!rows.length) {
    return (
      <EmptyState
        message="Không có dòng nào ở trạng thái hiện tại."
        title="Trống"
      />
    );
  }
  return (
    <>
      <div className="grid gap-3 sm:hidden">
        {rows.map((row, rowIndex) => (
          <article
            className="rounded-md border border-white/10 bg-white/[0.03] p-3"
            key={`${row[0]}-${rowIndex}`}
          >
            <div className="mb-2 flex items-center justify-between gap-3">
              <strong className="truncate text-base text-slate-100">
                {row[0]}
              </strong>
              {row[1] ? (
                <span className="shrink-0 rounded bg-white/10 px-2 py-1 text-xs font-black text-slate-300">
                  {row[1]}
                </span>
              ) : null}
            </div>
            <div className="grid gap-2">
              {row.slice(2).map((cell, index) => (
                <div
                  className="flex items-start justify-between gap-3 text-sm"
                  key={`${columns[index + 2]}-${cell}-${index}`}
                >
                  <span className="font-bold text-slate-400">
                    {columns[index + 2]}
                  </span>
                  <span className="max-w-[58%] break-words text-right font-semibold text-slate-100">
                    {cell}
                  </span>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
      <table className="hidden w-full min-w-[880px] border-collapse text-sm sm:table">
        <thead>
          <tr className="border-b border-white/10 bg-white/[0.03] text-left text-xs uppercase text-slate-400">
            {columns.map((column) => (
              <th className="px-3 py-3 font-bold" key={column}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr
              className="border-b border-white/5 transition hover:bg-white/[0.04] last:border-0"
              key={`${row[0]}-${rowIndex}`}
            >
              {row.map((cell, cellIndex) => (
                <td
                  className="whitespace-nowrap px-3 py-3"
                  key={`${cell}-${cellIndex}`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TableControls<T extends string>({
  query,
  setQuery,
  sort,
  setSort,
  sortOptions,
}: {
  query: string;
  setQuery: (value: string) => void;
  sort: T;
  setSort: (value: T) => void;
  sortOptions: readonly T[];
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <SearchBox query={query} setQuery={setQuery} />
      <label className="inline-flex min-h-10 items-center gap-2 rounded-md border border-white/15 bg-[#111c2b] px-3 py-2 text-sm shadow-sm focus-within:border-cyan-300">
        <ListFilter size={16} />
        <span className="text-slate-400">Sắp xếp</span>
        <select
          className="bg-transparent text-slate-100 outline-none"
          onChange={(event) => setSort(event.target.value as T)}
          value={sort}
        >
          {sortOptions.map((item) => (
            <option key={item} value={item}>
              {viSortLabel(item)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function SearchBox({
  query,
  setQuery,
}: {
  query: string;
  setQuery: (value: string) => void;
}) {
  return (
    <label className="inline-flex min-h-10 items-center gap-2 rounded-md border border-white/15 bg-[#111c2b] px-3 py-2 text-sm shadow-sm focus-within:border-cyan-300">
      <Search size={16} />
      <input
        className="w-36 bg-transparent text-slate-100 outline-none placeholder:text-slate-500"
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Tìm mã"
        value={query}
      />
    </label>
  );
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "bad";
}) {
  const color =
    tone === "good"
      ? "text-emerald-300"
      : tone === "bad"
        ? "text-red-300"
        : "text-slate-100";
  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.03] p-3 shadow-sm transition hover:border-white/20 md:p-4">
      <p className="text-xs font-bold uppercase text-slate-400">{label}</p>
      <strong
        className={`mt-2 block break-words text-xl leading-tight md:text-2xl ${color}`}
      >
        {value}
      </strong>
    </section>
  );
}

function NumberField({
  label,
  onChange,
  step = 1,
  value,
}: {
  label: string;
  onChange: (value: number) => void;
  step?: number;
  value: number;
}) {
  return (
    <label className="grid gap-2 text-sm font-bold text-slate-300">
      {label}
      <input
        className="rounded-md border border-white/15 bg-[#111c2b] px-3 py-2 font-normal text-slate-100 shadow-sm outline-none focus:border-cyan-300"
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

function StatusBadge({ value }: { value: WsState }) {
  const className =
    value === "LIVE"
      ? "bg-emerald-100 text-emerald-800"
      : value === "STALE"
        ? "bg-amber-100 text-amber-800"
        : "bg-red-100 text-red-800";
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-black ${className}`}>
      {viWsState(value)}
    </span>
  );
}

function Pill({
  label,
  tone,
  value,
}: {
  label: string;
  value: string;
  tone: "neutral" | "safe" | "danger";
}) {
  const color =
    tone === "safe"
      ? "text-emerald-700"
      : tone === "danger"
        ? "text-red-700"
        : "text-slate-700";
  return (
    <span className="max-w-full truncate rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-bold">
      <span className="text-slate-400">{label}</span>{" "}
      <span className={color}>{value}</span>
    </span>
  );
}

function EquityChart({ values }: { values: number[] }) {
  if (!values.length) {
    return (
      <div className="grid h-64 place-items-center rounded-md bg-white/[0.03] text-sm text-slate-400">
        Chưa có lịch sử vốn từ backend.
      </div>
    );
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * 100;
      const y = 100 - ((value - min) / Math.max(max - min, 1)) * 100;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      className="h-64 w-full rounded-md bg-white/[0.03]"
      preserveAspectRatio="none"
      viewBox="0 0 100 100"
    >
      <polyline
        fill="none"
        points={points}
        stroke="#67e8f9"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
      {values.length === 1 && (
        <line
          stroke="#67e8f9"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
          x1="0"
          x2="100"
          y1="50"
          y2="50"
        />
      )}
    </svg>
  );
}

function EmptyState({ message, title }: { title: string; message: string }) {
  return (
    <div className="rounded-md border border-dashed border-white/15 bg-white/[0.03] p-8 text-center">
      <h3 className="font-bold">{title}</h3>
      <p className="mt-2 text-sm text-slate-400">{message}</p>
    </div>
  );
}

function buildEquitySeries(performance: Performance | null) {
  return performance ? [performance.equity] : [];
}

function profitFactor(performance: Performance | null) {
  if (
    !performance ||
    performance.realized_pnl <= 0 ||
    performance.fees_paid <= 0
  )
    return "-";
  return (performance.realized_pnl / performance.fees_paid).toFixed(2);
}

function viAction(value: ScannerResult["action"]) {
  if (value === "NO_TRADE") return "Không vào lệnh";
  return value;
}

function viBotState(value: StatusPayload["bot_state"] | undefined) {
  if (value === "RUNNING") return "Đang chạy";
  if (value === "PAUSED") return "Tạm dừng";
  if (value === "SAFE_MODE") return "SAFE_MODE";
  if (value === "STOPPED") return "Đã dừng";
  return "Đã dừng";
}

function normalizeMode(
  value: StatusPayload["mode"] | undefined,
): "DEMO" | "LIVE" {
  return value === "LIVE" ? "LIVE" : "DEMO";
}

function viRegime(value: string) {
  const labels: Record<string, string> = {
    TRENDING_UP: "Xu hướng tăng",
    TRENDING_DOWN: "Xu hướng giảm",
    RANGING: "Đi ngang",
    HIGH_VOL: "Biến động cao",
    LOW_VOL: "Biến động thấp",
    PANIC: "Hoảng loạn",
  };
  return labels[value] ?? value;
}

function viSide(value: string) {
  if (value === "LONG") return "Long";
  if (value === "SHORT") return "Short";
  return value || "-";
}

function viExchangeConnection(
  value: ExchangeSnapshot["connection"] | undefined,
) {
  if (value === "CONNECTED") return "Đã kết nối";
  if (value === "STALE") return "Chậm";
  if (value === "SAFE_MODE") return "SAFE_MODE";
  return "Chưa kết nối";
}

function viAutoStatus(value: string | undefined) {
  const labels: Record<string, string> = {
    IDLE: "Đang chờ",
    BLOCKED: "Bị chặn",
    SCANNING: "Đang quét",
    NO_SIGNAL: "Chưa có signal",
    NO_ACCEPTED_SIGNAL: "Signal bị chặn",
    WAITING_POSITION: "Đang giữ lệnh",
    SUBMITTING: "Đang vào lệnh",
    ORDER_SUBMITTED: "Đã vào lệnh",
    ORDER_ERROR: "Lỗi lệnh",
    ERROR: "Lỗi worker",
  };
  return labels[value ?? ""] ?? "Đang chờ";
}

function viWsState(value: WsState) {
  if (value === "LIVE") return "RT";
  if (value === "STALE") return "Chậm";
  return "Offline";
}

function viSortLabel(value: string) {
  const labels: Record<string, string> = {
    quote_volume: "Khối lượng",
    price_change_percent: "Biến động 24h",
    spread_bps: "Chênh lệch",
    funding_rate: "Phí funding",
  };
  return labels[value] ?? value;
}

function money(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `$${value.toLocaleString("en-US", { maximumFractionDigits: value > 10 ? 2 : 6 })}`;
}

function compact(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function percent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(2)}%`;
}

function signedPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function number(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
}
