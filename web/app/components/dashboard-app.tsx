"use client";

import {
  Activity,
  BarChart3,
  Bell,
  Brain,
  Bot,
  Building2,
  ChevronRight,
  Clock,
  Crosshair,
  Database,
  Gauge,
  GitCompare,
  ListFilter,
  LogOut,
  Menu,
  MessageSquare,
  Pause,
  Play,
  RefreshCw,
  RotateCw,
  Search,
  Server,
  Settings,
  Shield,
  ShieldAlert,
  ShieldX,
  Square,
  Star,
  Target,
  Trash2,
  TrendingUp,
  WalletCards,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
} from "lightweight-charts";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, wsUrl } from "./api";
import { AuthGate } from "./auth-gate";
import type {
  AiSignal,
  AIShadowConfig,
  BotSettings,
  Candle,
  ExchangeSnapshot,
  ExitAnalytics,
  SmartEntryPayload,
  JournalCategory,
  JournalEntry,
  LogItem,
  Market,
  OperationsStatus,
  Performance,
  Position,
  ScannerResult,
  StatusPayload,
  RiskPayload,
  Trade,
  WsState,
} from "./types";

type PageKey =
  | "dashboard"
  | "markets"
  | "scanner"
  | "positions"
  | "orders"
  | "trades"
  | "strategies"
  | "analytics"
  | "risk"
  | "logs"
  | "journal"
  | "settings";

const nav = [
  { key: "dashboard", href: "/", label: "Tổng quan", icon: Gauge },
  { key: "markets", href: "/markets", label: "Thị trường", icon: WalletCards },
  { key: "scanner", href: "/signals", label: "Tín hiệu", icon: Activity },
  { key: "positions", href: "/positions", label: "Vị thế", icon: TrendingUp },
  { key: "orders", href: "/orders", label: "Lệnh chờ", icon: ListFilter },
  { key: "trades", href: "/history", label: "Lịch sử", icon: BarChart3 },
  { key: "strategies", href: "/strategy", label: "Chiến lược", icon: Bot },
  { key: "analytics", href: "/analytics", label: "Phân tích", icon: BarChart3 },
  { key: "risk", href: "/risk", label: "Rủi ro", icon: ShieldAlert },
  { key: "journal", href: "/journal", label: "Nhật ký", icon: Clock },
  { key: "settings", href: "/settings", label: "Cài đặt", icon: Settings },
] as const;

const pageTitles: Record<PageKey, string> = {
  dashboard: "Tổng quan",
  markets: "Thị trường",
  scanner: "Tín hiệu",
  positions: "Vị thế",
  orders: "Lệnh chờ",
  trades: "Lịch sử giao dịch",
  strategies: "Chiến lược",
  analytics: "Phân tích hiệu suất",
  risk: "Quản trị rủi ro",
  logs: "Nhật ký hệ thống",
  journal: "Nhật ký giao dịch",
  settings: "Cài đặt",
};

/* ── Sidebar nav helpers ── */

const navItems = Object.fromEntries(nav.map((item) => [item.key, item])) as Record<string, (typeof nav)[number]>;

function NavGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className="px-2 mb-1.5 text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--text-muted)]">
        {label}
      </p>
      <div className="flex flex-col gap-0.5">
        {children}
      </div>
    </div>
  );
}

function NavItem({ item }: { item: { key: string; href: string; label: string; icon: React.ComponentType<{ size?: number; className?: string }> } }) {
  const pathname = usePathname();
  const Icon = item.icon;
  const active =
    item.href === pathname ||
    (item.href !== "/" && pathname.startsWith(item.href));

  return (
    <Link
      href={item.href}
      className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-[13px] font-medium transition-all ${
        active
          ? "bg-[rgba(59,130,246,0.08)] text-[var(--color-info)]"
          : "text-[var(--text-secondary)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--text-primary)]"
      }`}
    >
      <Icon size={16} className="flex-shrink-0" />
      <span>{item.label}</span>
    </Link>
  );
}

function StatusPill({ label, tone }: { label: string; tone: "neutral" | "success" | "danger" }) {
  const colors = {
    neutral: "bg-[rgba(255,255,255,0.04)] text-[var(--text-secondary)]",
    success: "bg-[rgba(34,197,94,0.08)] text-[var(--color-profit)]",
    danger: "bg-[rgba(239,68,68,0.08)] text-[var(--color-loss)]",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${colors[tone]}`}>
      {label}
    </span>
  );
}

/* ──────────────────────────── MAIN COMPONENT ──────────────────────────── */

export function DashboardApp({ page }: { page: PageKey }) {
  return <AuthGate><DashboardContent page={page} /></AuthGate>;
}

function DashboardContent({ page }: { page: PageKey }) {
  const pathname = usePathname();
  const router = useRouter();
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [portfolioRisk, setPortfolioRisk] = useState<RiskPayload | null>(null);
  const [markets, setMarkets] = useState<Market[]>([]);
  const [scanner, setScanner] = useState<ScannerResult[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [journalEntries, setJournalEntries] = useState<JournalEntry[]>([]);
  const [journalFilter, setJournalFilter] = useState<JournalCategory>("ALL");
  const [performance, setPerformance] = useState<Performance | null>(null);
  const [exitAnalytics, setExitAnalytics] = useState<ExitAnalytics | null>(null);
  const [smartEntry, setSmartEntry] = useState<SmartEntryPayload | null>(null);
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [aiConfig, setAiConfig] = useState<AIShadowConfig | null>(null);
  const [exchange, setExchange] = useState<ExchangeSnapshot | null>(null);
  const [operations, setOperations] = useState<OperationsStatus | null>(null);
  const [wsState, setWsState] = useState<WsState>("OFFLINE");
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const systemServices = deriveSystemServices(status, exchange, operations);
  const [lastLiveAt, setLastLiveAt] = useState<number>(0);
  const lastLiveAtRef = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  const refresh = useCallback(async function refresh() {
    setIsRefreshing(true);
    try {
      const results = await Promise.allSettled([
        api.status().then(setStatus),
        api.markets().then((payload) => setMarkets(payload.items)),
        api.signals().then((payload) => setScanner(payload.items)),
        api.positions().then((payload) => setPositions(payload.items)),
        api.trades().then((payload) => setTrades(payload.items)),
        api.performance().then(setPerformance),
        api.exitAnalytics().then(setExitAnalytics),
        api.smartEntry().then(setSmartEntry),
        api.exchange().then(setExchange),
        api.operations().then(setOperations),
        api.settings().then(setSettings),
        api.aiConfig().then(setAiConfig),
        api.logs().then((payload) => setLogs(payload.items)),
        api.journal(journalFilter).then((payload) => setJournalEntries(payload.items)),
        api.risk().then(setPortfolioRisk),
      ]);
      const failed = results.filter((result) => result.status === "rejected");
      setError(
        failed.length
          ? `${failed.length} nhóm dữ liệu đang chậm, dashboard giữ dữ liệu cũ.`
          : null,
      );
    } catch {
      setError("Không tải được dữ liệu dashboard");
    } finally {
      setHasLoaded(true);
      setIsRefreshing(false);
    }
  }, [journalFilter]);

  useEffect(() => {
    const firstLoad = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => {
      window.clearTimeout(firstLoad);
      window.clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    const sockets = new Map<string, WebSocket>();
    const reconnects: number[] = [];
    const attempts = new Map<string, number>();
    let closed = false;

    type RealtimePayload = {
      channel?: string;
      data?: StatusPayload | ExchangeSnapshot | Performance;
      items?: Position[];
      exchange?: ExchangeSnapshot;
    };

    function markExchangeFreshness(freshness: ExchangeSnapshot["freshness"] | undefined) {
      if (freshness === "LIVE") {
        setWsState("LIVE");
        lastLiveAtRef.current = Date.now();
        setLastLiveAt(lastLiveAtRef.current);
      } else if (freshness === "STALE") {
        setWsState("STALE");
      } else if (freshness === "OFFLINE") {
        setWsState("OFFLINE");
      }
    }

    function connect(
      channel: "system" | "exchange" | "positions" | "performance",
    ) {
      const previous = sockets.get(channel);
      if (previous && previous.readyState < WebSocket.CLOSING) return;
      const socket = new WebSocket(wsUrl(channel));
      sockets.set(channel, socket);
      socket.onopen = () => {
        attempts.set(channel, 0);
      };
      socket.onmessage = async (event) => {
        const payload = JSON.parse(event.data) as RealtimePayload;
        if (channel === "system" && payload.data) {
          const nextStatus = payload.data as StatusPayload;
          setStatus(nextStatus);
          setExchange(nextStatus.exchange);
          markExchangeFreshness(nextStatus.exchange.freshness);
        }
        if (channel === "exchange" && payload.data) {
          const nextExchange = payload.data as ExchangeSnapshot;
          setExchange(nextExchange);
          markExchangeFreshness(nextExchange.freshness);
        }
        if (channel === "positions" && payload.items) {
          setPositions(payload.items);
          markExchangeFreshness(payload.exchange?.freshness);
        }
        if (channel === "performance" && payload.data) {
          const realtime = payload.data as Performance & { exchange_freshness?: ExchangeSnapshot["freshness"] };
          markExchangeFreshness(realtime.exchange_freshness);
          setPerformance((previous) => {
            if (!previous) return realtime;
            return {
              ...realtime,
              realized_pnl: previous.realized_pnl,
              fees_paid: previous.fees_paid,
              funding_paid: previous.funding_paid,
              win_rate: previous.win_rate,
              realized_pnl_events: previous.realized_pnl_events,
              winning_realized_pnl_events: previous.winning_realized_pnl_events,
              losing_realized_pnl_events: previous.losing_realized_pnl_events,
              breakeven_realized_pnl_events: previous.breakeven_realized_pnl_events,
              total_trades: previous.total_trades,
              winning_trades: previous.winning_trades,
              losing_trades: previous.losing_trades,
              breakeven_trades: previous.breakeven_trades,
              profit_factor: previous.profit_factor,
              max_drawdown: previous.max_drawdown,
              sharpe: previous.sharpe,
              sortino: previous.sortino,
              expectancy: previous.expectancy,
            };
          });
        }
      };
      socket.onerror = () => setWsState("STALE");
      socket.onclose = () => {
        sockets.delete(channel);
        if (closed) return;
        setWsState("STALE");
        const attempt = (attempts.get(channel) ?? 0) + 1;
        attempts.set(channel, attempt);
        const delay = Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5));
        const jitter = Math.floor(Math.random() * 500);
        reconnects.push(window.setTimeout(() => connect(channel), delay + jitter));
      };
    }

    (["system", "exchange", "positions", "performance"] as const).forEach(
      connect,
    );
    const staleTimer = window.setInterval(() => {
      setWsState((current) =>
        lastLiveAtRef.current > 0 && Date.now() - lastLiveAtRef.current <= 10_000
          ? current
          : current === "OFFLINE" ? "OFFLINE" : "STALE",
      );
    }, 3000);
    return () => {
      closed = true;
      reconnects.forEach((reconnect) => window.clearTimeout(reconnect));
      window.clearInterval(staleTimer);
      sockets.forEach((socket) => socket.close());
      sockets.clear();
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const [nextLogs, nextScanner] = await Promise.all([
          api.logs(),
          api.signals(),
        ]);
        setLogs(nextLogs.items);
        setScanner(nextScanner.items);
      } catch {
        setWsState((current) => (current === "LIVE" ? "STALE" : current));
      }
    }, 10_000);
    return () => window.clearInterval(timer);
  }, []);

  const currentPageTitle = pageTitles[page];

  return (
    <div className="flex min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      {/* ── Desktop sidebar ── */}
      <aside className="hidden lg:flex lg:flex-col lg:fixed lg:top-0 lg:left-0 lg:bottom-0 lg:w-[var(--sidebar-width)] lg:border-r lg:border-[var(--border-default)] lg:bg-[var(--bg-surface)] lg:z-30">
        {/* Logo */}
        <div className="flex items-center gap-2.5 h-14 px-5 border-b border-[var(--border-default)]">
          <div className="w-8 h-8 rounded-lg bg-[var(--color-info)] flex items-center justify-center flex-shrink-0">
            <Bot size={18} className="text-white" />
          </div>
          <div className="min-w-0">
            <span className="block truncate text-sm font-bold tracking-tight text-[var(--text-primary)]">Terminal Thuật toán</span>
            <span className="block text-[10px] text-[var(--text-muted)]">Giao dịch Crypto</span>
          </div>
        </div>

        {/* Nav groups */}
        <nav className="flex-1 overflow-y-auto scrollbar-thin py-3 px-3">
          <NavGroup label="Không gian làm việc">
            <NavItem item={navItems.dashboard} />
            <NavItem item={navItems.markets} />
            <NavItem item={navItems.scanner} />
          </NavGroup>

          <NavGroup label="Giao dịch">
            <NavItem item={navItems.positions} />
            <NavItem item={navItems.orders} />
            <NavItem item={navItems.trades} />
          </NavGroup>

          <NavGroup label="Phân tích & AI">
            <NavItem item={navItems.strategies} />
            <NavItem item={navItems.analytics} />
            <NavItem item={navItems.risk} />
          </NavGroup>

          <NavGroup label="Hệ thống">
            <NavItem item={navItems.journal} />
            <NavItem item={navItems.settings} />
          </NavGroup>
        </nav>

        {/* Bottom: connection status */}
        <div className="px-4 py-3 border-t border-[var(--border-default)]">
          <div className="flex items-center gap-2 text-xs">
            <div className={`status-dot ${wsState === "LIVE" ? "status-dot-live" : wsState === "STALE" ? "status-dot-stale" : "status-dot-offline"}`} />
            <span className="text-[var(--text-muted)]">{viWsState(wsState)}</span>
          </div>
        </div>
      </aside>

      {/* ── Main content ── */}
      <div className="flex-1 min-w-0 lg:ml-[var(--sidebar-width)]">
        {/* ── Top bar ── */}
        <header className="sticky top-0 z-20 border-b border-[var(--border-default)] bg-[var(--bg-base)]/90 backdrop-blur-xl">
          <div className="flex items-center justify-between h-14 px-4 lg:px-5">
            {/* Left: page title */}
            <div className="flex items-center gap-3 min-w-0">
              <h1 className="text-[15px] font-bold text-[var(--text-primary)] truncate">
                {currentPageTitle}
              </h1>
            </div>

            {/* Center: DEMO/LIVE status */}
            <div className="hidden lg:flex items-center gap-2">
              <StatusPill
                label={normalizeMode(status?.mode)}
                tone={status?.mode === "LIVE" ? "danger" : "neutral"}
              />
              {exchange?.connection === "CONNECTED" ? (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-semibold bg-[rgba(34,197,94,0.08)] text-[var(--color-profit)]">
                  <div className="status-dot status-dot-live" />
                  Binance đã kết nối
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-semibold bg-[rgba(239,68,68,0.08)] text-[var(--color-loss)]">
                  <div className="status-dot status-dot-offline" />
                  Binance mất kết nối
                </span>
              )}
            </div>

            {/* Right: minimal controls */}
            <div className="flex items-center gap-2">
              {/* Journal / notifications */}
              <Link
                className="sidebar-icon-btn"
                href="/journal"
                title="Nhật ký và cảnh báo"
              >
                <Zap size={16} />
                {error && <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[var(--color-loss)]" />}
              </Link>
              {/* Settings */}
              <Link
                href="/settings"
                className="sidebar-icon-btn"
                title="Cài đặt"
              >
                <Settings size={16} />
              </Link>
              {/* Mode toggle (compact) */}
              <ModeBadge current={normalizeMode(status?.mode)} liveAllowed={Boolean(status?.live_readiness?.allowed)} onDone={refresh} />
              <button
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.03)] px-2.5 py-1.5 text-[11px] font-bold text-[var(--text-muted)] transition hover:bg-[rgba(255,255,255,0.06)] hover:text-[var(--text-secondary)]"
                onClick={() => setSystemStatusOpen(true)}
                title="Trạng thái hệ thống"
                type="button"
              >
                <Activity size={13} />
                <span className="hidden sm:inline">Hệ thống</span>
              </button>
              <button
                className="sidebar-icon-btn"
                onClick={() => {
                  api.clearToken();
                  router.push("/");
                  router.refresh();
                }}
                title="Đăng xuất"
                type="button"
              >
                <LogOut size={16} />
              </button>
            </div>
          </div>

          {/* Status line for mobile */}
          <div className="px-4 pb-2 xl:hidden">
            <StatusLine
              exchange={exchange ?? status?.exchange ?? null}
              isRefreshing={isRefreshing}
              lastLiveAt={lastLiveAt}
              status={status}
              wsState={wsState}
            />
          </div>
        </header>

        {/* ── Page content ── */}
        <div className="p-4 lg:p-5 pb-20 lg:pb-5">
          {error && (
            <div className="mb-4 rounded-lg border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.06)] px-4 py-3 text-sm text-[var(--color-loss)] flex items-center gap-2">
              <div className="status-dot status-dot-offline" />
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
              status={status}
            />
          )}
          {page === "markets" && <Markets markets={markets} positions={positions} scanner={scanner} />}
          {page === "scanner" && <Scanner scanner={scanner} />}
          {page === "positions" && (
            <Positions markets={markets} positions={positions} />
          )}
          {page === "orders" && <Orders orders={exchange?.orders ?? []} trades={trades} />}
          {page === "trades" && <Trades trades={trades} />}
          {page === "strategies" && <Strategies scanner={scanner} />}
          {page === "analytics" && (
            <Analytics
              exitAnalytics={exitAnalytics}
              smartEntry={smartEntry}
              performance={performance}
              trades={trades}
            />
          )}
          {page === "risk" && <Risk onDone={refresh} status={status} portfolioRisk={portfolioRisk} />}
          {page === "logs" && <Logs logs={logs} />}
          {page === "journal" && (
            <JournalPage
              entries={journalEntries}
              filter={journalFilter}
              onFilterChange={setJournalFilter}
              onRefresh={refresh}
            />
          )}
          {page === "settings" && settings && (
            <SettingsPage
              key={
                aiConfig
                  ? `${aiConfig.model}:${aiConfig.outcome_horizon}:${aiConfig.minimum_training_samples}`
                  : "ai-loading"
              }
              aiConfig={aiConfig}
              onSaved={refresh}
              settings={settings}
            />
          )}
        </div>
      </div>

      {/* ── Điều hướng mobile ── */}
      <nav aria-label="Điều hướng chính" className="mobile-bottom-bar lg:hidden">
        {nav.slice(0, 4).map((item) => {
          const Icon = item.icon;
          const active = item.href === pathname || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              aria-current={active ? "page" : undefined}
              className={`mobile-nav-item ${active ? "text-[var(--color-info)]" : "text-[var(--text-muted)]"}`}
              href={item.href}
              key={item.key}
            >
              <Icon size={18} />
              <span>{item.label}</span>
            </Link>
          );
        })}
        <button
          aria-expanded={mobileMenuOpen}
          className={`mobile-nav-item ${mobileMenuOpen ? "text-[var(--color-info)]" : "text-[var(--text-muted)]"}`}
          onClick={() => setMobileMenuOpen(true)}
          type="button"
        >
          <Menu size={18} />
          <span>Thêm</span>
        </button>
      </nav>

      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Tất cả chức năng">
          <button className="absolute inset-0 bg-black/70" aria-label="Đóng menu" onClick={() => setMobileMenuOpen(false)} type="button" />
          <div className="mobile-menu-sheet">
            <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
              <div>
                <h2 className="text-sm font-bold">Tất cả chức năng</h2>
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">Terminal giao dịch thuật toán</p>
              </div>
              <button className="sidebar-icon-btn" aria-label="Đóng menu" onClick={() => setMobileMenuOpen(false)} type="button"><X size={17} /></button>
            </div>
            <div className="grid grid-cols-2 gap-2 p-4">
              {nav.map((item) => {
                const Icon = item.icon;
                const active = item.href === pathname || (item.href !== "/" && pathname.startsWith(item.href));
                return <Link className={`mobile-menu-link ${active ? "mobile-menu-link-active" : ""}`} href={item.href} key={item.key} onClick={() => setMobileMenuOpen(false)}><Icon size={17}/><span>{item.label}</span></Link>;
              })}
            </div>
          </div>
        </div>
      )}

      {/* Ngăn trạng thái hệ thống */}
      <SystemStatusDrawer open={systemStatusOpen} onClose={() => setSystemStatusOpen(false)} services={systemServices} wsState={wsState} />
    </div>
  );
}

/* ──────────────────────────── SHARED PAGE PRIMITIVES ──────────────────────────── */

function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div className="min-w-0">
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ──────────────────────────── DASHBOARD PAGE ──────────────────────────── */

function Dashboard({
  exchange,
  markets,
  onDone,
  performance,
  positions,
  scanner,
  status,
}: {
  exchange: ExchangeSnapshot | null;
  markets: Market[];
  onDone: () => Promise<void>;
  performance: Performance | null;
  positions: Position[];
  scanner: ScannerResult[];
  status: StatusPayload | null;
}) {
  const equitySeries = useMemo(
    () => buildEquitySeries(performance),
    [performance],
  );
  const [activeChartSymbol, setActiveChartSymbol] = useState<string | null>(null);
  const chartSymbol =
    exchange?.positions[0]?.symbol ??
    status?.auto_trader?.last_symbol ??
    scanner.find((item) => item.action !== "NO_TRADE")?.symbol ??
    markets[0]?.symbol ??
    "BTCUSDT";
  const selectedChartSymbol = activeChartSymbol ?? chartSymbol;
  const chartSymbols = useMemo(
    () =>
      Array.from(
        new Set([
          selectedChartSymbol,
          ...markets.slice(0, 80).map((item) => item.symbol),
          ...scanner.slice(0, 40).map((item) => item.symbol),
        ]),
      ),
    [selectedChartSymbol, markets, scanner],
  );
  return (
    <div className="grid gap-4">
      <PageHeader
        title="Tổng quan danh mục"
        description="Theo dõi vốn, hiệu suất và cơ hội giao dịch theo thời gian thực."
      />
      <PerformanceKpis
        exchange={exchange}
        performance={performance}
        positions={positions}
        status={status}
      />
      <DataPanel title="Đường cong vốn">
        <EquityChart values={equitySeries} />
      </DataPanel>
      <section>
        <div className="mb-3 flex items-end justify-between gap-3">
          <div><h2 className="text-base font-bold">Tổng quan thị trường</h2><p className="mt-1 text-xs text-[var(--text-muted)]">Giá, khối lượng và tín hiệu kỹ thuật trực tiếp từ Binance.</p></div>
        </div>
        <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_320px]">
          <MarketChart
            key={selectedChartSymbol}
            markets={markets}
            positions={positions}
            scanner={scanner}
            symbol={selectedChartSymbol}
            symbols={chartSymbols}
          />
          <TerminalRail markets={markets} onSelectSymbol={setActiveChartSymbol} scanner={scanner} symbol={selectedChartSymbol} />
        </div>
      </section>
      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <OpenPositionsPanel positions={exchange?.positions ?? []} />
        <SignalFocus scanner={scanner} />
      </div>
      <details className="terminal-disclosure">
        <summary>Điều khiển bot và chế độ giao dịch</summary>
        <div className="pt-3"><CommandCenter exchange={exchange} onDone={onDone} status={status} /></div>
      </details>
    </div>
  );
}

/* ──────────────────────────── PERFORMANCE KPIs ──────────────────────────── */

function PerformanceKpis({
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
  const unrealized =
    exchange?.balance.unrealized_pnl ?? performance?.unrealized_pnl ?? 0;
  const dailyPnl = performance?.equity_pnl ?? unrealized;

  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Tổng vốn" value={money(performance?.equity ?? exchange?.balance.margin_balance)} />
      <Metric
        label="PnL hôm nay"
        value={money(dailyPnl)}
        tone={dailyPnl >= 0 ? "good" : "bad"}
      />
      <Metric
        label="Tỷ lệ thắng"
        value={percent((performance?.win_rate ?? 0) * 100)}
        tone={(performance?.win_rate ?? 0) >= 0.5 ? "good" : "neutral"}
      />
      <Metric label="Vị thế đang mở" value={`${openPositions} / ${maxPositions}`} />
    </section>
  );
}

/* ──────────────────────────── COMMAND CENTER ──────────────────────────── */

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
    <section className="glass-card p-4">
      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <ModeCard
            label="Chế độ giao dịch"
            value={normalizeMode(status?.mode)}
            tone={status?.mode === "LIVE" ? "danger" : "warning"}
          />
          <ModeCard
            label="Sàn giao dịch"
            value={viExchangeConnection(exchange?.connection)}
            tone={exchange?.connection === "CONNECTED" ? "safe" : "danger"}
          />
          <ModeCard
            label="Điều kiện LIVE"
            value={status?.live_readiness?.allowed ? "SẴN SÀNG" : "ĐANG KHÓA"}
            tone={status?.live_readiness?.allowed ? "warning" : "safe"}
          />
          <ModeCard
            label="Vòng lặp tự động"
            value={viAutoStatus(status?.auto_trader?.last_status)}
            tone={
              status?.auto_trader?.last_status === "ORDER_SUBMITTED"
                ? "safe"
                : "warning"
            }
          />
        </div>
        <div className="flex flex-col justify-center gap-3 xl:items-end">
          <p className="max-w-xl text-sm text-[var(--text-secondary)] xl:text-right">
            {status?.mode === "LIVE"
              ? "LIVE đang dùng tiền thật. Kiểm tra lệnh và rủi ro trước mọi thao tác."
              : "Đang ở môi trường an toàn. Có thể kiểm tra kết nối, signal và lệnh demo tại đây."}
          </p>
          <div className="flex flex-wrap items-center justify-start gap-2 xl:justify-end">
            <ModeBadge current={normalizeMode(status?.mode)} liveAllowed={Boolean(status?.live_readiness?.allowed)} onDone={onDone} />
            <LiveQuickActions onDone={onDone} status={status} />
            <BotControls onDone={onDone} status={status} />
          </div>
        </div>
      </div>
    </section>
  );
}

/* ──────────────────────────── OPEN POSITIONS ──────────────────────────── */

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
              className="glass-card p-3 md:grid md:grid-cols-[1fr_auto] md:gap-3"
              key={`${position.symbol}-${position.side}`}
            >
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="text-lg num-display">{position.symbol}</strong>
                  <span
                    className={`badge ${position.side === "LONG" ? "bg-[rgba(34,197,94,0.12)] text-[var(--color-profit)]" : "bg-[rgba(239,68,68,0.12)] text-[var(--color-loss)]"}`}
                  >
                    {viSide(position.side)}
                  </span>
                  <span className="badge bg-[rgba(255,255,255,0.04)] text-[var(--text-secondary)]">
                    {position.leverage ?? "-"}x
                  </span>
                </div>
                <p className="mt-2 text-sm text-[var(--text-secondary)] num-display">
                  Giá vào {money(position.entry_price)} / Giá hiện tại{" "}
                  {money(position.mark_price)} / Thanh lý{" "}
                  {money(position.liquidation_price)}
                </p>
              </div>
              <div className="text-left md:text-right">
                <p
                  className={`text-xl font-black num-display ${position.unrealized_pnl >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]"}`}
                >
                  {money(position.unrealized_pnl)}
                </p>
                <p className="mt-1 text-xs text-[var(--text-muted)] num-display">
                  Khối lượng {number(position.quantity)}
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

/* ──────────────────────────── SIGNAL FOCUS ──────────────────────────── */

function SignalFocus({ scanner }: { scanner: ScannerResult[] }) {
  const grouped = new Map<string, Partial<Record<"15m" | "1h" | "4h", ScannerResult>>>();
  for (const item of scanner) {
    if (!["15m", "1h", "4h"].includes(item.timeframe)) continue;
    const frames = grouped.get(item.symbol) ?? {};
    frames[item.timeframe as "15m" | "1h" | "4h"] = item;
    grouped.set(item.symbol, frames);
  }
  const focus = Array.from(grouped.entries())
    .map(([symbol, frames]) => ({
      symbol,
      frames,
      bestScore: Math.max(...Object.values(frames).map((item) => item ? Math.max(item.long_score, item.short_score) : 0)),
    }))
    .filter((item) => item.bestScore >= 75)
    .sort((a, b) => b.bestScore - a.bestScore)
    .slice(0, 5);

  const frameState = (item: ScannerResult | undefined, frame: string) => {
    if (!item) return `${frame}: thiếu dữ liệu`;
    const score = Math.max(item.long_score, item.short_score);
    if (item.regime === "HIGH_VOL" || item.regime === "PANIC") return `${frame}: ${item.regime}`;
    if (item.action === "NO_TRADE") return `${frame}: chưa trigger (${score}/85)`;
    return `${frame}: ${viAction(item.action)} ${score}`;
  };

  return (
    <DataPanel title="Tín hiệu & điều kiện vào lệnh">
      <p className="mb-3 text-xs leading-5 text-[var(--text-muted)]">
        Bot dùng 4h xác định xu hướng, 1h xác nhận setup và 15m chỉ để canh điểm vào lệnh. Không vào lệnh nếu ba khung chưa đồng thuận.
      </p>
      <div className="grid gap-3">
        {focus.length ? (
          focus.map(({ symbol, frames, bestScore }) => {
            const trigger = frames["15m"];
            const confirmation = frames["1h"];
            const trend = frames["4h"];
            const ready = Boolean(
              trigger?.action !== "NO_TRADE" &&
              confirmation?.action === trigger?.action &&
              trend?.regime === (trigger?.action === "LONG" ? "TRENDING_UP" : "TRENDING_DOWN"),
            );
            return (
              <article className="glass-card p-3" key={symbol}>
                <div className="flex items-center justify-between gap-3">
                  <strong className="num-display">{symbol}</strong>
                  <span className={`badge ${ready ? "bg-[rgba(34,197,94,0.12)] text-[var(--color-profit)]" : "bg-[var(--color-warning)]/15 text-[var(--color-warning)]"}`}>
                    {ready ? "Đủ đồng thuận" : "Đang chờ xác nhận"}
                  </span>
                </div>
                <div className="mt-2 grid gap-1 text-xs text-[var(--text-secondary)]">
                  <span>{frameState(trend, "4h")}</span>
                  <span>{frameState(confirmation, "1h")}</span>
                  <span>{frameState(trigger, "15m")}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                  <InfoPair label="Điểm cao nhất" value={String(bestScore)} />
                  <InfoPair label="RR 15m" value={number(trigger?.risk_reward)} />
                </div>
              </article>
            );
          })
        ) : (
          <EmptyState message="Chưa có setup gần ngưỡng entry; bot tiếp tục quét toàn bộ universe DEMO." title="Đang chờ" />
        )}
      </div>
    </DataPanel>
  );
}

/* ──────────────────────────── TERMINAL RAIL ──────────────────────────── */

function TerminalRail({
  markets,
  onSelectSymbol,
  scanner,
  symbol,
}: {
  markets: Market[];
  onSelectSymbol: (symbol: string) => void;
  scanner: ScannerResult[];
  symbol: string;
}) {
  const [watchedSymbols, setWatchedSymbols] = useState<string[]>(["BTCUSDT", "ETHUSDT", "SOLUSDT"]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("trading-watchlist-v1");
      if (saved) {
        const parsed = JSON.parse(saved) as unknown;
        if (Array.isArray(parsed)) {
          const normalized = parsed.filter((item): item is string => typeof item === "string").slice(0, 12);
          window.setTimeout(() => setWatchedSymbols(normalized), 0);
        }
      }
    } catch {
      // Giữ danh sách mặc định nếu dữ liệu trình duyệt không hợp lệ.
    }
  }, []);

  function setWatch(symbolToChange: string, enabled: boolean) {
    setWatchedSymbols((current) => {
      const next = enabled
        ? Array.from(new Set([...current, symbolToChange])).slice(0, 12)
        : current.filter((item) => item !== symbolToChange);
      window.localStorage.setItem("trading-watchlist-v1", JSON.stringify(next));
      return next;
    });
  }

  const watchlist = watchedSymbols
    .map((watched) => markets.find((item) => item.symbol === watched))
    .filter((item): item is Market => Boolean(item));
  const suggestedSymbols = Array.from(
    new Map(
      scanner
        .filter((item) => item.action !== "NO_TRADE" && !watchedSymbols.includes(item.symbol))
        .sort((a, b) => Math.max(b.long_score, b.short_score) - Math.max(a.long_score, a.short_score))
        .map((item) => [item.symbol, item]),
    ).values(),
  ).filter((item) => markets.some((market) => market.symbol === item.symbol)).slice(0, 3);
  const latestByFrame = new Map<string, ScannerResult>();
  for (const item of scanner) {
    if (item.symbol !== symbol || !["4h", "1h", "15m"].includes(item.timeframe)) continue;
    latestByFrame.set(item.timeframe, item);
  }
  const currentSignal = latestByFrame.get("15m");
  return (
    <div className="grid content-start gap-4">
      <DataPanel
        controls={
          <button
            className="btn-secondary !min-h-7 !px-2 !py-1 text-[11px]"
            disabled={!symbol || watchedSymbols.includes(symbol)}
            onClick={() => setWatch(symbol, true)}
            title={watchedSymbols.includes(symbol) ? "Mã này đã được theo dõi" : "Thêm mã đang xem vào danh sách"}
            type="button"
          >
            <Star size={12} /> {watchedSymbols.includes(symbol) ? "Đã theo dõi" : "Theo dõi mã này"}
          </button>
        }
        title="Danh sách theo dõi"
      >
        <div className="grid gap-1">
          {watchlist.length ? watchlist.map((item) => (
            <div className={`flex items-center gap-2 rounded-lg px-3 py-2.5 transition ${item.symbol === symbol ? "border border-[rgba(59,130,246,0.2)] bg-[rgba(59,130,246,0.08)]" : "border border-transparent bg-[rgba(255,255,255,0.02)] hover:bg-[rgba(255,255,255,0.03)]"}`} key={item.symbol}>
              <button className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left" onClick={() => onSelectSymbol(item.symbol)} title={`Mở biểu đồ ${item.symbol}`} type="button">
                <span className="min-w-0">
                  <strong className="block truncate text-sm num-display">{item.symbol.replace("USDT", "")}</strong>
                  <span className="text-[11px] text-[var(--text-muted)]">{compact(item.quote_volume)} khối lượng 24h</span>
                </span>
                <span className="text-right">
                  <strong className="block text-sm num-display">{money(item.last_price)}</strong>
                  <span className={`text-[11px] font-bold num-display ${item.price_change_percent >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]"}`}>{signedPercent(item.price_change_percent)}</span>
                </span>
              </button>
              <button aria-label={`Bỏ theo dõi ${item.symbol}`} className="sidebar-icon-btn !h-7 !w-7 border-0" onClick={() => setWatch(item.symbol, false)} title="Bỏ theo dõi" type="button"><Star className="fill-current text-[var(--color-warning)]" size={13} /></button>
            </div>
          )) : <EmptyState message="Mở một mã trên biểu đồ rồi chọn Theo dõi mã này." title="Chưa theo dõi mã nào" />}
        </div>
        {suggestedSymbols.length > 0 && (
          <div className="mt-3 border-t border-[var(--border-default)] pt-3">
            <p className="mb-2 text-[10px] font-bold uppercase tracking-wide text-[var(--text-muted)]">Gợi ý từ tín hiệu mạnh</p>
            <div className="grid gap-1">
              {suggestedSymbols.map((item) => <button className="flex items-center justify-between rounded-lg px-3 py-2 text-left text-xs text-[var(--text-secondary)] hover:bg-white/[0.04]" key={item.symbol} onClick={() => { setWatch(item.symbol, true); onSelectSymbol(item.symbol); }} type="button"><span><b className="text-[var(--text-primary)]">{item.symbol}</b> · {viAction(item.action)}</span><span className="flex items-center gap-1 text-[var(--color-ai)]"><Star size={12}/> Thêm · {Math.max(item.long_score, item.short_score)}</span></button>)}
            </div>
          </div>
        )}
      </DataPanel>
      <DataPanel title="Tín hiệu đa khung thời gian">
        <div className="grid gap-2">
          {["4h", "1h", "15m"].map((frame) => {
            const item = latestByFrame.get(frame);
            const active = item?.action !== "NO_TRADE" && item?.action !== undefined;
            return (
              <div className="flex items-center justify-between rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-3 py-2.5" key={frame}>
                <span className="text-xs font-bold uppercase text-[var(--text-muted)]">{frame}</span>
                <span className={`text-sm font-bold num-display ${active ? (item?.action === "LONG" ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]") : "text-[var(--text-muted)]"}`}>
                  {item ? viAction(item.action) : "Chưa có dữ liệu"}
                </span>
              </div>
            );
          })}
        </div>
        <div className="mt-3 rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] p-3">
          <span className="text-xs text-[var(--text-muted)]">Điểm vào 15m</span>
          <strong className="mt-1 block text-sm num-display">{currentSignal ? `${viAction(currentSignal.action)} · score ${Math.max(currentSignal.long_score, currentSignal.short_score)}` : "Đang chờ tín hiệu"}</strong>
        </div>
      </DataPanel>
    </div>
  );
}

/* ──────────────────────────── MARKET CHART ──────────────────────────── */

function MarketChart({
  positions,
  scanner,
  symbol,
  symbols,
  markets,
}: {
  positions: Position[];
  scanner: ScannerResult[];
  symbol: string;
  symbols: string[];
  markets?: Market[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ema20Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema50Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markerRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const fittedRangeRef = useRef<string | null>(null);
  const [history, setHistory] = useState<Candle[]>([]);
  const [liveCandle, setLiveCandle] = useState<Candle | null>(null);
  const [live, setLive] = useState(false);
  const [interval, setInterval] = useState("15m");
  const [selectedSymbol, setSelectedSymbol] = useState(symbol);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const effectiveSymbol = symbols.includes(selectedSymbol)
    ? selectedSymbol
    : symbol;
  const meta = (markets ?? []).find((item) => item.symbol === effectiveSymbol) ?? null;
  const candles = useMemo(() => {
    if (!liveCandle) return history;
    const index = history.findIndex((item) => item.open_time === liveCandle.open_time);
    if (index < 0) return [...history.slice(-219), liveCandle];
    const merged = history.slice();
    merged[index] = liveCandle;
    return merged;
  }, [history, liveCandle]);

  useEffect(() => {
    let alive = true;
    async function load() {
      setBusy(true);
      try {
        const response = await api.klines(effectiveSymbol, interval, 220);
        if (!alive) return;
        setHistory(response.items);
        setLiveCandle(null);
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
    return () => {
      alive = false;
    };
  }, [effectiveSymbol, interval]);

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return;
    // lightweight-charts draws on canvas, so CSS var(...) strings are not
    // resolved as colors. Use their concrete values or the canvas silently
    // falls back to black, making candles and indicator lines invisible.
    const chartColors = {
      background: "#111621",
      text: "#8492a6",
      profit: "#22c55e",
      loss: "#ef4444",
      warning: "#f59e0b",
      info: "#3b82f6",
      ai: "#a78bfa",
    };
    const chart = createChart(containerRef.current, {
      autoSize: true,
      height: 360,
      layout: { background: { color: chartColors.background }, textColor: chartColors.text },
      grid: {
        vertLines: { color: "rgba(255, 255, 255, 0.04)" },
        horzLines: { color: "rgba(255, 255, 255, 0.04)" },
      },
      rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.10)" },
      timeScale: {
        borderColor: "rgba(148, 163, 184, 0.10)",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: 1 },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: chartColors.profit,
      downColor: chartColors.loss,
      borderVisible: false,
      wickUpColor: chartColors.profit,
      wickDownColor: chartColors.loss,
    });
    const ema20 = chart.addSeries(LineSeries, {
      color: chartColors.warning,
      lineWidth: 2,
      title: "EMA20",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema50 = chart.addSeries(LineSeries, {
      color: chartColors.info,
      lineWidth: 2,
      title: "EMA50",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      color: "rgba(59, 130, 246, 0.25)",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 1);
    const rsi = chart.addSeries(LineSeries, {
      color: chartColors.ai,
      lineWidth: 2,
      title: "RSI14",
      priceLineVisible: false,
    }, 2);
    rsi.createPriceLine({
      price: 70,
      color: "rgba(239, 68, 68, 0.4)",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "Quá mua",
    });
    rsi.createPriceLine({
      price: 30,
      color: "rgba(34, 197, 94, 0.4)",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "Quá bán",
    });
    const macdLine = chart.addSeries(LineSeries, {
      color: chartColors.info,
      lineWidth: 2,
      title: "MACD",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 3);
    const macdSignal = chart.addSeries(LineSeries, {
      color: chartColors.warning,
      lineWidth: 2,
      title: "Signal",
      priceLineVisible: false,
      lastValueVisible: false,
    }, 3);
    const macdHistogram = chart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
    }, 3);
    const panes = chart.panes();
    panes[0]?.setStretchFactor(5);
    panes[1]?.setStretchFactor(1.25);
    panes[2]?.setStretchFactor(1.75);
    panes[3]?.setStretchFactor(1.75);
    chartRef.current = chart;
    seriesRef.current = series;
    volumeRef.current = volume;
    ema20Ref.current = ema20;
    ema50Ref.current = ema50;
    rsiRef.current = rsi;
    macdLineRef.current = macdLine;
    macdSignalRef.current = macdSignal;
    macdHistRef.current = macdHistogram;
    markerRef.current = createSeriesMarkers(series, []);
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volumeRef.current = null;
      ema20Ref.current = null;
      ema50Ref.current = null;
      rsiRef.current = null;
      macdLineRef.current = null;
      macdSignalRef.current = null;
      macdHistRef.current = null;
      markerRef.current = null;
      priceLinesRef.current = [];
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !history.length) return;
    seriesRef.current.setData(history.map((item) => ({
      time: Math.floor(item.open_time / 1000) as Time,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    })));
    volumeRef.current?.setData(history.map((item) => ({
      time: Math.floor(item.open_time / 1000) as Time,
      value: item.volume,
      color: item.close >= item.open ? "rgba(16, 185, 129, 0.40)" : "rgba(239, 68, 68, 0.40)",
    })));
    const rangeKey = `${effectiveSymbol}:${interval}`;
    if (fittedRangeRef.current !== rangeKey) {
      chartRef.current?.timeScale().fitContent();
      fittedRangeRef.current = rangeKey;
    }
  }, [history, effectiveSymbol, interval]);

  useEffect(() => {
    if (!seriesRef.current || !candles.length) return;
    ema20Ref.current?.setData(indicatorLine(candles, 20, ema(candles.map((item) => item.close), 20)));
    ema50Ref.current?.setData(indicatorLine(candles, 50, ema(candles.map((item) => item.close), 50)));
    rsiRef.current?.setData(indicatorLine(candles, 14, rsi(candles.map((item) => item.close), 14)));
    const closes = candles.map((item) => item.close);
    const macdValues = macd(closes, 12, 26, 9);
    const macdTimes = candles.map((item) => Math.floor(item.open_time / 1000) as Time);
    macdLineRef.current?.setData(macdTimes.map((time, i) => ({ time, value: macdValues.macdLine[i] })));
    macdSignalRef.current?.setData(macdTimes.map((time, i) => ({ time, value: macdValues.signalLine[i] })));
    macdHistRef.current?.setData(macdTimes.map((time, i) => ({
      time,
      value: macdValues.histogram[i],
      color: macdValues.histogram[i] >= 0 ? "rgba(16, 185, 129, 0.55)" : "rgba(239, 68, 68, 0.55)",
    })));
    priceLinesRef.current.forEach((line) => seriesRef.current?.removePriceLine(line));
    priceLinesRef.current = [];
    const position = positions.find((item) => item.symbol === effectiveSymbol && item.status === "OPEN");
    const signal = scanner.find((item) => item.symbol === effectiveSymbol && item.timeframe === "15m");
    const levels = [
      position && { price: position.entry_price, color: "#3b82f6", title: "ENTRY" },
      position && { price: position.stop_loss, color: "#ef4444", title: "SL" },
      ...(position?.take_profits ?? signal?.take_profits ?? []).map((price, index) => ({ price, color: "#22c55e", title: `TP${index + 1}` })),
      !position && signal?.stop_loss && { price: signal.stop_loss, color: "#ef4444", title: "SL" },
    ].filter((item): item is { price: number; color: string; title: string } => Boolean(item && Number.isFinite(item.price) && item.price > 0));
    priceLinesRef.current = levels.map((level) => seriesRef.current!.createPriceLine({ ...level, lineWidth: 1, lineStyle: 2, axisLabelVisible: true }));
    const markerSignal = scanner.find((item) => item.symbol === effectiveSymbol && item.timeframe === interval && item.action !== "NO_TRADE") ?? signal;
    markerRef.current?.setMarkers(markerSignal && markerSignal.action !== "NO_TRADE" && candles.at(-1) ? [{
      time: Math.floor(candles.at(-1)!.open_time / 1000) as Time,
      position: markerSignal.action === "LONG" ? "belowBar" : "aboveBar",
      shape: markerSignal.action === "LONG" ? "arrowUp" : "arrowDown",
      color: markerSignal.action === "LONG" ? "#34d399" : "#f87171",
      text: markerSignal.action === "LONG" ? "BUY" : "SELL",
    }] : []);
  }, [candles, effectiveSymbol, interval, positions, scanner]);

  useEffect(() => {
    let stopped = false;
    let retry: number | undefined;
    let attempt = 0;
    const connect = () => {
      const socket = new WebSocket(wsUrl(`kline:${effectiveSymbol}:${interval}`));
      socketRef.current = socket;
      socket.onopen = () => { attempt = 0; setLive(true); };
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as { candle?: Candle };
        if (!payload.candle) return;
        const next = payload.candle;
        const latest = next.open_time;
        setLiveCandle(next);
        seriesRef.current?.update({
          time: Math.floor(latest / 1000) as Time,
          open: next.open,
          high: next.high,
          low: next.low,
          close: next.close,
        });
        volumeRef.current?.update({
          time: Math.floor(latest / 1000) as Time,
          value: next.volume,
          color: next.close >= next.open ? "rgba(16, 185, 129, 0.40)" : "rgba(239, 68, 68, 0.40)",
        });
      };
      socket.onerror = () => setLive(false);
      socket.onclose = () => {
        setLive(false);
        if (stopped) return;
        attempt += 1;
        retry = window.setTimeout(connect, Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5)));
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) window.clearTimeout(retry);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [effectiveSymbol, interval]);

  const last = candles.at(-1);
  const first = candles.at(0);
  const change =
    last && first ? ((last.close - first.open) / first.open) * 100 : null;
  const latestRsi = candles.length
    ? rsi(candles.map((item) => item.close), 14).at(-1) ?? null
    : null;
  const latestMacd = candles.length ? macd(candles.map((item) => item.close), 12, 26, 9) : null;
  const latestMacdVal = latestMacd?.macdLine.at(-1) ?? null;
  const latestSignalVal = latestMacd?.signalLine.at(-1) ?? null;
  const latestHistVal = latestMacd?.histogram.at(-1) ?? null;
  const latestAtr = candles.length >= 14 ? atr(candles, 14) : null;
  const latestEma20 = candles.length >= 20 ? ema(candles.map((item) => item.close), 20).at(-1) ?? null : null;
  const latestEma50 = candles.length >= 50 ? ema(candles.map((item) => item.close), 50).at(-1) ?? null : null;

  return (
    <section className="glass-card overflow-hidden">
      <div className="panel-header flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-end gap-3">
            <h3 className="text-lg font-black num-display">{effectiveSymbol}</h3>
            <span className="text-sm font-bold text-[var(--text-secondary)] num-display">
              {last ? money(last.close) : "-"}
            </span>
            <span
              className={`text-sm font-bold num-display ${(change ?? 0) >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]"}`}
            >
              {change === null ? "-" : signedPercent(change)}
            </span>
            {meta ? (
              <span className="ml-1 hidden text-xs text-[var(--text-muted)] sm:inline">
                Vol {compact(meta.quote_volume)} · Spread {meta.spread_bps.toFixed(1)} bps · Funding {percent(meta.funding_rate * 100)}
              </span>
            ) : null}
            <span className="badge bg-[rgba(34,197,94,0.08)] text-[var(--color-profit)]">
              {live ? "Realtime" : "Đang kết nối"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="terminal-select"
            onChange={(event) => setSelectedSymbol(event.target.value)}
            value={effectiveSymbol}
          >
            {symbols.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <div className="flex gap-1">
            {(["1m", "5m", "15m", "1h", "4h", "1d"] as const).map((value) => (
              <button
                className={`rounded-lg px-2.5 py-1.5 text-xs font-bold transition ${interval === value ? "bg-[var(--color-info)] text-[var(--bg-base)]" : "text-[var(--text-secondary)] hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--text-primary)]"}`}
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
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px] font-bold text-[var(--text-muted)]">
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--color-warning)]" />EMA20 {latestEma20 === null ? "-" : money(latestEma20)}</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--color-info)]" />EMA50 {latestEma50 === null ? "-" : money(latestEma50)}</span>
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 bg-[var(--color-info)]/50" />Vol</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--color-ai)]" />RSI14 {latestRsi === null ? "-" : latestRsi.toFixed(1)}</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--color-info)]" />MACD {latestMacdVal === null ? "-" : latestMacdVal.toFixed(4)}</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--color-warning)]" />Signal {latestSignalVal === null ? "-" : latestSignalVal.toFixed(4)}</span>
          <span className="flex items-center gap-1.5">Hist {(latestHistVal ?? 0) >= 0 ? <span className="text-[var(--color-profit)]">{(latestHistVal ?? 0).toFixed(4)}</span> : <span className="text-[var(--color-loss)]">{(latestHistVal ?? 0).toFixed(4)}</span>}</span>
          {latestAtr !== null ? (
            <span className="flex items-center gap-1.5">ATR14 {money(latestAtr)}</span>
          ) : null}
        </div>
        <div className="h-[420px] w-full md:h-[560px]" ref={containerRef} />
        {busy && (
          <div className="absolute right-5 top-5 rounded-full bg-[var(--bg-elevated)]/90 px-3 py-1 text-xs font-bold text-[var(--text-secondary)] shadow border border-[var(--border-default)]">
            Đang tải
          </div>
        )}
        {error && (
          <div className="absolute inset-x-5 bottom-5 rounded-lg border border-[rgba(239,68,68,0.2)] bg-[var(--bg-elevated)]/95 px-3 py-2 text-sm text-[var(--color-loss)] backdrop-blur">
            {error}
          </div>
        )}
      </div>
    </section>
  );
}

/* ──────────────────────────── INDICATOR HELPERS ──────────────────────────── */

function ema(values: number[], period: number): number[] {
  if (!values.length) return [];
  const multiplier = 2 / (period + 1);
  return values.reduce<number[]>((result, value, index) => {
    result.push(index === 0 ? value : value * multiplier + result[index - 1] * (1 - multiplier));
    return result;
  }, []);
}

function rsi(values: number[], period: number): number[] {
  return values.map((_, index) => {
    if (index < period) return 50;
    let gains = 0;
    let losses = 0;
    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const delta = values[cursor] - values[cursor - 1];
      if (delta >= 0) gains += delta;
      else losses -= delta;
    }
    return losses === 0 ? 100 : 100 - 100 / (1 + gains / losses);
  });
}

function indicatorLine(candles: Candle[], period: number, values: number[]) {
  return candles.slice(period - 1).map((item, index) => ({
    time: Math.floor(item.open_time / 1000) as Time,
    value: values[index + period - 1],
  }));
}

function macd(closes: number[], fast: number, slow: number, signal: number) {
  const fastEma = ema(closes, fast);
  const slowEma = ema(closes, slow);
  const macdLine = fastEma.map((v, i) => v - slowEma[i]);
  const signalLine = ema(macdLine, signal);
  const histogram = macdLine.map((v, i) => v - signalLine[i]);
  return { macdLine, signalLine, histogram };
}

function atr(candles: Candle[], period: number): number {
  if (candles.length < period + 1) return 0;
  let sum = 0;
  for (let i = candles.length - period; i < candles.length; i++) {
    const high = candles[i].high;
    const low = candles[i].low;
    const prevClose = candles[i - 1].close;
    sum += Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
  }
  return sum / period;
}

/* ──────────────────────────── MODE CARD ──────────────────────────── */

function ModeCard({
  label,
  tone,
  value,
}: {
  label: string;
  value: string;
  tone: "safe" | "warning" | "danger";
}) {
  const dotClass =
    tone === "safe"
      ? "status-dot-live"
      : tone === "warning"
        ? "status-dot-stale"
        : "status-dot-offline";
  return (
    <div className="glass-card p-4 transition-all hover:border-[var(--border-strong)]">
      <div className="flex items-center gap-2 mb-2">
        <div className={`status-dot ${dotClass}`} />
        <p className="text-[11px] font-bold uppercase text-[var(--text-muted)] tracking-wider">{label}</p>
      </div>
      <strong className="block break-words text-lg font-black num-display">
        {value}
      </strong>
    </div>
  );
}

/* ──────────────────────────── MARKETS PAGE ──────────────────────────── */

function Markets({
  markets,
  positions,
  scanner,
}: {
  markets: Market[];
  positions: Position[];
  scanner: ScannerResult[];
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<keyof Market>("quote_volume");
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const rows = useMemo(
    () =>
      markets
        .filter((item) => item.symbol.includes(query.toUpperCase()))
        .sort((a, b) => Number(b[sort] ?? 0) - Number(a[sort] ?? 0)),
    [markets, query, sort],
  );
  const symbols = useMemo(() => markets.map((item) => item.symbol), [markets]);
  const activeSymbol = symbols.includes(selectedSymbol) ? selectedSymbol : symbols[0] ?? "";
  const activeMeta = (markets ?? []).find((item) => item.symbol === activeSymbol) ?? null;
  return (
    <div className="flex flex-1 flex-col gap-4 xl:flex-row">
      <div className="flex flex-[1.6] flex-col gap-3">
        <MarketChart
          markets={markets}
          positions={positions}
          scanner={scanner}
          symbol={activeSymbol}
          symbols={symbols}
        />
      </div>
      <div className="flex flex-1 flex-col gap-3">
        {activeMeta ? (
          <div className="grid grid-cols-2 gap-2 text-xs text-[var(--text-muted)] sm:grid-cols-4">
            {([
              ["Giá", money(activeMeta.last_price)],
              ["24h%", signedPercent(activeMeta.price_change_percent)],
              ["Khối lượng", compact(activeMeta.quote_volume)],
              ["Spread", `${activeMeta.spread_bps.toFixed(2)} bps`],
            ] as const).map(([label, value]) => (
              <div className="rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-3 py-2" key={label}>
                <div className="font-bold uppercase text-[var(--text-muted)]">{label}</div>
                <div className="mt-0.5 font-bold text-[var(--text-primary)] num-display">{value}</div>
              </div>
            ))}
          </div>
        ) : null}
        <DataPanel
          controls={
            <TableControls
              query={query}
              setQuery={setQuery}
              sort={sort}
              setSort={setSort}
              sortOptions={["quote_volume", "price_change_percent", "spread_bps", "funding_rate"]}
            />
          }
          title="Thị trường"
        >
          <Table
            columns={["Mã", "Giá", "24h%", "Khối lượng", "Chênh lệch", "Phí funding", "Tuổi niêm yết"]}
            rows={rows.map((item) => [
              <button
                className="rounded bg-transparent px-1 py-0.5 text-left font-bold transition hover:bg-[rgba(255,255,255,0.06)]"
                key={item.symbol}
                onClick={() => setSelectedSymbol(item.symbol)}
                type="button"
              >
                {item.symbol}
              </button>,
              money(item.last_price),
              signedPercent(item.price_change_percent),
              compact(item.quote_volume),
              `${item.spread_bps.toFixed(2)} bps`,
              percent(item.funding_rate * 100),
              item.listing_age_days ? `${Math.floor(item.listing_age_days)} ngày` : "-",
            ])}
          />
        </DataPanel>
      </div>
    </div>
  );
}

/* ──────────────────────────── SCANNER PAGE ──────────────────────────── */


/* ── AI signal transformer ── */

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

function buildAiSignals(items: ScannerResult[]): AiSignal[] {
  return items.map((item) => {
    const rsi = item.indicators.rsi ?? 50;
    const adx = item.indicators.adx ?? 20;
    const macdHistogram = item.indicators.macd_histogram ?? 0;
    const quoteVolume = item.quote_volume ?? 0;

    const action = item.action === "NO_TRADE" ? "HOLD" : item.action === "LONG" ? "BUY" : "SELL";
    const dominantScore = action === "BUY" ? item.long_score : action === "SELL" ? item.short_score : 0;
    const momentum = clamp(40 + (item.action === "LONG" ? 1 : -1) * (rsi - 50) * 0.6 + macdHistogram * 25, 0, 100);
    const trend = clamp(adx * 1.2 + (item.action === "LONG" ? 10 : item.action === "SHORT" ? -10 : 0), 0, 100);
    const volume = clamp(quoteVolume > 200_000_000 ? 80 : quoteVolume > 80_000_000 ? 60 : 40, 0, 100);
    const aiConfidence = clamp(dominantScore * 0.75 + adx * 0.25, 0, 100);
    const aiScore = clamp(aiConfidence * 0.5 + momentum * 0.25 + trend * 0.15 + volume * 0.1, 0, 100);

    return {
      symbol: item.symbol,
      decision: action,
      aiConfidence: Math.round(aiConfidence),
      momentum: Math.round(momentum),
      trend: Math.round(trend),
      volume: Math.round(volume),
      aiScore: Math.round(aiScore),
      entry: item.price,
      stopLoss: item.stop_loss,
      takeProfit: item.take_profits.at(0) ?? null,
      riskReward: item.risk_reward,
      timeframe: item.timeframe,
      regime: item.regime,
      strategy: item.strategy,
      reasons: item.reasons,
    };
  });
}

function Scanner({ scanner }: { scanner: ScannerResult[] }) {
  const signals = useMemo(() => buildAiSignals(scanner), [scanner]);
  const [query, setQuery] = useState("");
  const [signal, setSignal] = useState<"ALL" | "BUY" | "SELL" | "HOLD">("ALL");
  const [selectedSignal, setSelectedSignal] = useState<AiSignal | null>(null);

  const filtered = signals.filter(
    (item) =>
      item.symbol.includes(query.toUpperCase()) &&
      (signal === "ALL" || item.decision === signal),
  );

  const summary = useMemo(() => {
    const buyCount = signals.filter((s) => s.decision === "BUY").length;
    const sellCount = signals.filter((s) => s.decision === "SELL").length;
    const holdCount = signals.filter((s) => s.decision === "HOLD").length;
    const avgScore = signals.length ? Math.round(signals.reduce((a, s) => a + s.aiScore, 0) / signals.length) : 0;
    return { buyCount, sellCount, holdCount, avgScore, total: signals.length };
  }, [signals]);

  function actionTone(action: "BUY" | "SELL" | "HOLD") {
    if (action === "BUY") return { bg: "rgba(34,197,94,0.10)", text: "text-[var(--color-profit)]", border: "border-[rgba(34,197,94,0.25)]", label: "MUA" };
    if (action === "SELL") return { bg: "rgba(239,68,68,0.10)", text: "text-[var(--color-loss)]", border: "border-[rgba(239,68,68,0.25)]", label: "BÁN" };
    return { bg: "rgba(255,255,255,0.04)", text: "text-[var(--text-muted)]", border: "border-[var(--border-default)]", label: "GIỮ" };
  }

  function scoreTone(score: number) {
    if (score >= 70) return "text-[var(--color-profit)]";
    if (score >= 50) return "text-[var(--color-warning)]";
    return "text-[var(--text-muted)]";
  }

  function meterBar(value: number, color: string) {
    return (
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      </div>
    );
  }

  function SignalCard({ sig }: { sig: AiSignal }) {
    const tone = actionTone(sig.decision);
    const isActive = selectedSignal?.symbol === sig.symbol;
    return (
      <div
        className={`glass-card cursor-pointer border transition-all ${isActive ? "border-[var(--color-info)] bg-[rgba(59,130,246,0.06)]" : tone.border + " hover:border-[var(--border-strong)]"}`}
        onClick={() => setSelectedSignal(isActive ? null : sig)}
        role="button"
        tabIndex={0}
      >
        {/* Header row */}
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3 min-w-0">
            <Crosshair size={14} className="flex-shrink-0 text-[var(--text-muted)]" />
            <div className="min-w-0">
              <strong className="block truncate text-sm font-bold text-[var(--text-primary)] num-display">
                {sig.symbol.replace("USDT", "")}
              </strong>
              <span className="text-[10px] text-[var(--text-muted)]">{sig.timeframe} · {viRegime(sig.regime)}</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center rounded-md px-2.5 py-1 text-xs font-black ${tone.bg} ${tone.text}`}>
              {tone.label}
            </span>
            <div className="text-right">
              <span className={`block text-sm font-black num-display ${scoreTone(sig.aiScore)}`}>{sig.aiScore}</span>
              <span className="text-[10px] text-[var(--text-muted)]">Điểm AI</span>
            </div>
            <ChevronRight size={14} className={`flex-shrink-0 text-[var(--text-muted)] transition-transform ${isActive ? "rotate-90" : ""}`} />
          </div>
        </div>

        {/* Metric meters */}
        <div className="grid grid-cols-4 gap-3 border-t border-white/[0.04] px-4 py-3">
          <div className="grid gap-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Độ tin cậy</span>
              <span className={`text-xs font-bold num-display ${scoreTone(sig.aiConfidence)}`}>{sig.aiConfidence}%</span>
            </div>
            {meterBar(sig.aiConfidence, "bg-[var(--color-info)]")}
          </div>
          <div className="grid gap-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Động lượng</span>
              <span className={`text-xs font-bold num-display ${scoreTone(sig.momentum)}`}>{sig.momentum}%</span>
            </div>
            {meterBar(sig.momentum, "bg-[var(--color-warning)]")}
          </div>
          <div className="grid gap-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Xu hướng</span>
              <span className={`text-xs font-bold num-display ${scoreTone(sig.trend)}`}>{sig.trend}%</span>
            </div>
            {meterBar(sig.trend, "bg-[var(--color-profit)]")}
          </div>
          <div className="grid gap-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Khối lượng</span>
              <span className={`text-xs font-bold num-display ${scoreTone(sig.volume)}`}>{sig.volume}%</span>
            </div>
            {meterBar(sig.volume, "bg-[var(--color-loss)]")}
          </div>
        </div>

        {/* Expanded detail panel */}
        {isActive && (
          <div className="border-t border-white/[0.04] px-4 py-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div>
                <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Giá vào</span>
                <strong className="mt-1 block text-sm font-bold text-[var(--text-primary)] num-display">{sig.entry ? money(sig.entry) : "—"}</strong>
              </div>
              <div>
                <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Cắt lỗ</span>
                <strong className="mt-1 block text-sm font-bold text-[var(--color-loss)] num-display">{sig.stopLoss ? money(sig.stopLoss) : "—"}</strong>
              </div>
              <div>
                <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Chốt lời</span>
                <strong className="mt-1 block text-sm font-bold text-[var(--color-profit)] num-display">{sig.takeProfit ? money(sig.takeProfit) : "—"}</strong>
              </div>
              <div>
                <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Rủi ro / Lợi nhuận</span>
                <strong className={`mt-1 block text-sm font-bold num-display ${sig.riskReward && sig.riskReward >= 2 ? "text-[var(--color-profit)]" : sig.riskReward ? "text-[var(--color-warning)]" : "text-[var(--text-muted)]"}`}>{sig.riskReward ? `${number(sig.riskReward)}R` : "—"}</strong>
              </div>
            </div>

            {sig.reasons.length > 0 && (
              <div className="mt-3 rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] p-3">
                <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Lý do AI</span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {sig.reasons.slice(0, 5).map((reason, i) => (
                    <span className="rounded-md bg-[rgba(255,255,255,0.04)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)]" key={i}>{reason}</span>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-4 flex flex-wrap gap-2">
              <Link
                className="inline-flex items-center gap-2 rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.03)] px-3 py-2 text-xs font-bold text-[var(--text-secondary)] transition hover:bg-[rgba(255,255,255,0.06)] hover:text-[var(--text-primary)]"
                href={`/markets?symbol=${sig.symbol}`}
                onClick={(e) => e.stopPropagation()}
              >
                <Target size={12} />
                Xem thiết lập
              </Link>
              <button
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-bold transition ${sig.decision === "HOLD" ? "cursor-not-allowed border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] text-[var(--text-muted)]" : sig.decision === "BUY" ? "bg-[var(--color-profit)] text-white hover:brightness-110" : "bg-[var(--color-loss)] text-white hover:brightness-110"}`}
                disabled={sig.decision === "HOLD"}
                onClick={(e) => {
                  e.stopPropagation();
                  void navigator.clipboard.writeText(
                    JSON.stringify({
                      symbol: sig.symbol,
                      side: sig.decision,
                      entry: sig.entry,
                      stopLoss: sig.stopLoss,
                      takeProfit: sig.takeProfit,
                      riskReward: sig.riskReward,
                      confidence: sig.aiConfidence,
                      score: sig.aiScore,
                    }),
                  );
                }}
                title={sig.decision === "HOLD" ? "Không có lệnh để thực thi" : "Sao chép thiết lập lệnh"}
                type="button"
              >
                <Zap size={12} />
                Thực thi
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {/* Summary bar */}
      <div className="glass-card px-4 py-3">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Activity size={14} className="text-[var(--color-info)]" />
            <span className="text-xs font-bold text-[var(--text-muted)] uppercase">Terminal tín hiệu AI</span>
          </div>
          <div className="flex flex-wrap gap-3 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-[rgba(34,197,94,0.08)] px-2 py-1 text-[var(--color-profit)]">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-profit)]" />
              {summary.buyCount} BUY
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-[rgba(239,68,68,0.08)] px-2 py-1 text-[var(--color-loss)]">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-loss)]" />
              {summary.sellCount} SELL
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md bg-[rgba(255,255,255,0.04)] px-2 py-1 text-[var(--text-muted)]">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--text-muted)]" />
              {summary.holdCount} HOLD
            </span>
            <span className="text-[var(--text-muted)]">·</span>
            <span className="text-[var(--text-muted)]">Điểm trung bình: <span className={`font-bold num-display ${scoreTone(summary.avgScore)}`}>{summary.avgScore}</span></span>
            <span className="text-[var(--text-muted)]">·</span>
            <span className="text-[var(--text-muted)]">{summary.total} tổng</span>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            <SearchBox query={query} setQuery={setQuery} />
            <select
              className="terminal-select"
              onChange={(event) => setSignal(event.target.value as typeof signal)}
              value={signal}
            >
              <option value="ALL">Tất cả</option>
              <option value="BUY">Mua</option>
              <option value="SELL">Bán</option>
              <option value="HOLD">Giữ</option>
            </select>
          </div>
        </div>
      </div>

      {/* Signal grid */}
      {filtered.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((sig) => (
            <SignalCard key={sig.symbol} sig={sig} />
          ))}
        </div>
      ) : (
        <EmptyState message="Không có tín hiệu phù hợp bộ lọc." title="Chưa có tín hiệu" />
      )}
    </div>
  );
}

/* ──────────────────────────── POSITIONS PAGE ──────────────────────────── */

/* ──────────────────────────── POSITIONS TERMINAL ──────────────────────────── */

function Positions({
  markets,
  positions,
}: {
  markets: Market[];
  positions: Position[];
}) {
  const marks = useMemo(
    () => new Map(markets.map((item) => [item.symbol, item.last_price])),
    [markets],
  );
  const [selected, setSelected] = useState<Position | null>(null);

  const openPositions = positions.filter((p) => p.status === "OPEN");

  const stats = useMemo(() => {
    let totalExposure = 0;
    let totalPnl = 0;
    for (const p of openPositions) {
      const mark = p.mark_price ?? marks.get(p.symbol) ?? p.entry_price;
      const notional = p.entry_price * p.remaining_quantity;
      totalExposure += notional;
      totalPnl += p.unrealized_pnl ??
        (p.side === "LONG"
          ? (mark - p.entry_price) * p.remaining_quantity
          : (p.entry_price - mark) * p.remaining_quantity);
    }
    return { totalExposure, totalPnl };
  }, [openPositions, marks]);

  return (
    <div className="grid gap-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Vị thế đang mở" value={String(openPositions.length)} />
        <Metric
          label="Tổng mức tiếp xúc"
          value={money(stats.totalExposure)}
          tone={stats.totalExposure > 0 ? "neutral" : "neutral"}
        />
        <Metric
          label="PnL chưa chốt"
          value={money(stats.totalPnl)}
          tone={stats.totalPnl > 0 ? "good" : stats.totalPnl < 0 ? "bad" : "neutral"}
        />
        <Metric
          label="Rủi ro TB mỗi vị thế"
          value={
            openPositions.length > 0
              ? percent(
                  (openPositions.reduce((a, p) => {
                    const mark = p.mark_price ?? marks.get(p.symbol) ?? p.entry_price;
                    const risk = Math.abs(mark - p.stop_loss) * p.remaining_quantity;
                    const cost = p.entry_price * p.remaining_quantity;
                    return a + (cost > 0 ? (risk / cost) * 100 : 0);
                  }, 0)) / openPositions.length,
                )
              : "—"
          }
        />
      </div>

      {/* Position table */}
      <section className="glass-card overflow-hidden">
        <div className="panel-header">
          <h3>Terminal vị thế</h3>
        </div>
        <div className="overflow-x-auto">
          {openPositions.length > 0 ? (
            <table className="hidden w-full min-w-[880px] border-collapse text-sm sm:table">
              <thead>
                <tr className="border-b border-[var(--border-default)] text-left text-xs uppercase text-[var(--text-muted)]">
                  {["Mã", "Hướng", "Khối lượng", "Giá vào", "Giá hiện tại", "PnL", "PnL %", "Cắt lỗ", "Chốt lời"].map((col) => (
                    <th className="px-4 py-3 font-bold" key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {openPositions.map((item) => {
                  const mark = item.mark_price ?? marks.get(item.symbol) ?? item.entry_price;
                  const pnl =
                    item.unrealized_pnl ??
                    (item.side === "LONG"
                      ? (mark - item.entry_price) * item.remaining_quantity
                      : (item.entry_price - mark) * item.remaining_quantity);
                  const cost = item.entry_price * item.remaining_quantity;
                  const pnlPct = cost > 0 ? (pnl / cost) * 100 : 0;
                  const isActive = selected?.id === item.id;
                  const sideColor = item.side === "LONG" ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]";
                  const pnlColor = pnl >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]";
                  return (
                    <tr
                      className={`cursor-pointer border-b border-white/[0.04] transition hover:bg-white/[0.025] last:border-0 ${isActive ? "bg-[rgba(59,130,246,0.06)]" : ""}`}
                      key={item.id}
                      onClick={() => setSelected(isActive ? null : item)}
                    >
                      <td className="whitespace-nowrap px-4 py-3">
                        <strong className="font-bold text-[var(--text-primary)] num-display">{item.symbol.replace("USDT", "")}</strong>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-bold ${item.side === "LONG" ? "bg-[rgba(34,197,94,0.10)]" : "bg-[rgba(239,68,68,0.10)]"} ${sideColor}`}>
                          {item.side}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-semibold num-display">{number(item.remaining_quantity)}</td>
                      <td className="whitespace-nowrap px-4 py-3 font-semibold num-display">{money(item.entry_price)}</td>
                      <td className="whitespace-nowrap px-4 py-3 font-semibold num-display">{money(mark)}</td>
                      <td className={`whitespace-nowrap px-4 py-3 font-bold num-display ${pnlColor}`}>{money(pnl)}</td>
                      <td className={`whitespace-nowrap px-4 py-3 font-bold num-display ${pnlColor}`}>{signedPercent(pnlPct)}</td>
                      <td className="whitespace-nowrap px-4 py-3 font-semibold num-display text-[var(--color-loss)]">{money(item.stop_loss)}</td>
                      <td className="whitespace-nowrap px-4 py-3 font-semibold num-display text-[var(--color-profit)]">
                        {item.take_profits.length > 0 ? item.take_profits.map(money).join(" / ") : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="p-8 text-center">
              <EmptyState message="Không có vị thế đang mở." title="Không có vị thế mở" />
            </div>
          )}
        </div>
      </section>

      {/* Mobile cards */}
      <div className="grid gap-3 sm:hidden">
        {openPositions.map((item) => {
          const mark = item.mark_price ?? marks.get(item.symbol) ?? item.entry_price;
          const pnl =
            item.unrealized_pnl ??
            (item.side === "LONG"
              ? (mark - item.entry_price) * item.remaining_quantity
              : (item.entry_price - mark) * item.remaining_quantity);
          const cost = item.entry_price * item.remaining_quantity;
          const pnlPct = cost > 0 ? (pnl / cost) * 100 : 0;
          const pnlColor = pnl >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]";
          const isActive = selected?.id === item.id;
          return (
            <div
              className={`glass-card cursor-pointer p-3 transition-all ${isActive ? "border-[var(--color-info)] bg-[rgba(59,130,246,0.06)]" : ""}`}
              key={item.id}
              onClick={() => setSelected(isActive ? null : item)}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <strong className="text-sm font-bold text-[var(--text-primary)] num-display">{item.symbol.replace("USDT", "")}</strong>
                  <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${item.side === "LONG" ? "bg-[rgba(34,197,94,0.10)] text-[var(--color-profit)]" : "bg-[rgba(239,68,68,0.10)] text-[var(--color-loss)]"}`}>{viSide(item.side)}</span>
                </div>
                <div className="text-right">
                  <strong className={`block text-sm font-bold num-display ${pnlColor}`}>{money(pnl)}</strong>
                  <span className={`text-[11px] font-bold num-display ${pnlColor}`}>{signedPercent(pnlPct)}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Drawer */}
      {selected && (
        <PositionDrawer
          position={selected}
          markPrice={selected.mark_price ?? marks.get(selected.symbol) ?? selected.entry_price}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

/* ──────────────────────────── POSITION DRAWER ──────────────────────────── */

/* ──────────────────────────── POSITION DRAWER ──────────────────────────── */

function DrawerRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-white/[0.04] py-2.5 last:border-0">
      <span className="text-xs font-bold uppercase text-[var(--text-muted)]">{label}</span>
      <span className={`text-sm font-bold num-display ${tone ?? "text-[var(--text-primary)]"}`}>{value}</span>
    </div>
  );
}

function PositionDrawer({
  position,
  markPrice,
  onClose,
}: {
  position: Position;
  markPrice: number;
  onClose: () => void;
}) {
  const p = position;
  const pnl =
    p.unrealized_pnl ??
    (p.side === "LONG"
      ? (markPrice - p.entry_price) * p.remaining_quantity
      : (p.entry_price - markPrice) * p.remaining_quantity);
  const cost = p.entry_price * p.remaining_quantity;
  const pnlPct = cost > 0 ? (pnl / cost) * 100 : 0;

  // Risk = distance to SL × size
  const slDistance = Math.abs(markPrice - p.stop_loss);
  const riskAmount = slDistance * p.remaining_quantity;
  const riskPct = cost > 0 ? (riskAmount / cost) * 100 : 0;

  // R-multiple: PnL / initial risk
  const initialRisk = Math.abs(p.entry_price - p.stop_loss) * p.remaining_quantity;
  const rMultiple = initialRisk > 0 ? pnl / initialRisk : 0;

  // Distance to TP
  const primaryTp = p.take_profits.at(0) ?? null;
  const tpDistance = primaryTp ? Math.abs(primaryTp - markPrice) : null;

  const pnlColor = pnl >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]";
  const rColor = rMultiple >= 1 ? "text-[var(--color-profit)]" : rMultiple >= 0 ? "text-[var(--color-warning)]" : "text-[var(--color-loss)]";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

      {/* Drawer panel */}
      <div
        className="relative ml-auto flex h-full w-full max-w-sm flex-col border-l border-[var(--border-default)] bg-[var(--bg-elevated)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border-default)] px-5 py-4">
          <div className="flex items-center gap-3">
            <strong className="text-base font-black text-[var(--text-primary)] num-display">{p.symbol.replace("USDT", "")}</strong>
            <span className={`rounded-md px-2 py-0.5 text-xs font-bold ${p.side === "LONG" ? "bg-[rgba(34,197,94,0.10)] text-[var(--color-profit)]" : "bg-[rgba(239,68,68,0.10)] text-[var(--color-loss)]"}`}>{viSide(p.side)}</span>
          </div>
          <button
            className="rounded-lg p-1.5 transition hover:bg-[rgba(255,255,255,0.06)]"
            onClick={onClose}
            type="button"
          >
            <X size={16} className="text-[var(--text-muted)]" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* PnL hero */}
          <div className="mb-5 rounded-xl border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] p-4">
            <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">PnL chưa chốt</span>
            <strong className={`mt-1 block text-2xl font-black num-display ${pnlColor}`}>{money(pnl)}</strong>
            <span className={`text-sm font-bold num-display ${pnlColor}`}>{signedPercent(pnlPct)}</span>
          </div>

          {/* Metrics grid */}
          <div className="mb-5 grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] p-3">
              <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Bội số R</span>
              <strong className={`mt-1 block text-lg font-black num-display ${rColor}`}>{number(rMultiple)}R</strong>
            </div>
            <div className="rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] p-3">
              <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Rủi ro</span>
              <strong className="mt-1 block text-lg font-black num-display text-[var(--color-loss)]">{money(riskAmount)}</strong>
              <span className="text-[11px] text-[var(--text-muted)]">{percent(riskPct)} trên ký quỹ</span>
            </div>
          </div>

          {/* Detail rows */}
          <div className="rounded-xl border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-4">
            <DrawerRow label="Giá vào" value={money(p.entry_price)} />
            <DrawerRow label="Giá hiện tại" value={money(markPrice)} tone={pnlColor} />
            <DrawerRow label="Cắt lỗ" value={money(p.stop_loss)} tone="text-[var(--color-loss)]" />
            <DrawerRow
              label="Chốt lời"
              value={primaryTp ? money(primaryTp) : "—"}
              tone="text-[var(--color-profit)]"
            />
            <DrawerRow label="Khối lượng vị thế" value={number(p.remaining_quantity)} />
            <DrawerRow label="Giá trị danh nghĩa" value={money(cost)} />
            <DrawerRow label="Khoảng cách SL" value={`${money(slDistance)} (${percent(riskPct)})`} />
            {tpDistance !== null && (
              <DrawerRow label="Khoảng cách TP" value={money(tpDistance)} tone="text-[var(--color-profit)]" />
            )}
          </div>

          {/* Take profit ladder */}
          {p.take_profits.length > 1 && (
            <div className="mt-4">
              <span className="mb-2 block text-[10px] font-bold uppercase text-[var(--text-muted)]">Các mức chốt lời</span>
              <div className="grid gap-1.5">
                {p.take_profits.map((tp, i) => {
                  const tpR = initialRisk > 0 ? ((tp - p.entry_price) * (p.side === "LONG" ? 1 : -1)) / initialRisk : 0;
                  return (
                    <div className="flex items-center justify-between rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-3 py-2" key={i}>
                      <span className="text-xs text-[var(--text-muted)]">TP{i + 1}</span>
                      <strong className="text-sm font-bold text-[var(--color-profit)] num-display">{money(tp)}</strong>
                      <span className="text-xs font-bold text-[var(--text-muted)] num-display">{number(tpR)}R</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Status flags */}
          <div className="mt-4 flex flex-wrap gap-2">
            {p.break_even_active && (
              <span className="inline-flex items-center gap-1 rounded-md bg-[rgba(34,197,94,0.08)] px-2 py-1 text-[11px] font-bold text-[var(--color-profit)]">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-profit)]" />
                Hòa vốn
              </span>
            )}
            {p.trailing_stop_active && (
              <span className="inline-flex items-center gap-1 rounded-md bg-[rgba(59,130,246,0.08)] px-2 py-1 text-[11px] font-bold text-[var(--color-info)]">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-info)]" />
                Cắt lỗ bám đuổi
              </span>
            )}
            {p.leverage && p.leverage > 1 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-[rgba(245,158,11,0.08)] px-2 py-1 text-[11px] font-bold text-[var(--color-warning)]">
                {p.leverage}x Đòn bẩy
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────── ORDERS PAGE ──────────────────────────── */

function Orders({
  orders,
  trades,
}: {
  orders: ExchangeSnapshot['orders'];
  trades: Trade[];
}) {
  const [query, setQuery] = useState("");
  const [side, setSide] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const rows = orders.filter((order) => {
    const okQuery = order.symbol.includes(query.toUpperCase());
    const okSide = side === "ALL" || order.side === side;
    const okStatus = statusFilter === "ALL" || order.status === statusFilter;
    return okQuery && okSide && okStatus;
  });

  return (
    <div className="grid gap-4">
      <PageHeader title="Quản lý lệnh" description="Theo dõi lệnh đang chờ và lịch sử lệnh đã hoàn tất từ dữ liệu thật." />
      <DataPanel
        controls={
          <div className="flex flex-wrap gap-2">
            <SearchBox query={query} setQuery={setQuery} />
          <select
            className="terminal-select"
            onChange={(event) => setSide(event.target.value)}
            value={side}
          >
            <option value="ALL">Tất cả</option>
            <option value="BUY">Mua</option>
            <option value="SELL">Bán</option>
          </select>
          <select
            className="terminal-select"
            onChange={(event) => setStatusFilter(event.target.value)}
            value={statusFilter}
          >
            <option value="ALL">Tất cả</option>
            <option value="NEW">Mới</option>
            <option value="PARTIALLY_FILLED">Khớp 1 phần</option>
            <option value="FILLED">Khớp hết</option>
            <option value="CANCELED">Đã hủy</option>
          </select>
        </div>
      }
      title="Lệnh đang chờ"
    >
      <Table
        columns={["Mã", "Hướng", "Loại lệnh", "Giá", "SL", "Trạng thái", "Khối lượng", "Khớp", "ID"]}
        rows={rows.map((order) => [
          order.symbol,
          order.side === "BUY" ? "Mua" : "Bán",
          order.order_type,
          order.stop_price ? money(order.stop_price) : money(order.price),
          order.stop_price ? money(order.price) : "-",
          order.status,
          number(order.quantity),
          number(order.executed_quantity),
          String(order.order_id),
        ])}
      />
      </DataPanel>
      <DataPanel title="Lịch sử lệnh">
        <Table
          columns={["Thời gian", "Mã", "Hướng", "Giá vào", "Giá thoát", "PnL", "Kết quả"]}
          rows={trades.slice(0, 100).map((trade) => [
            new Date(trade.created_at).toLocaleString("vi-VN"),
            trade.symbol,
            viSide(trade.side),
            money(trade.entry_price),
            money(trade.exit_price),
            money(trade.net_pnl),
            trade.net_pnl > 0 ? "Thắng" : trade.net_pnl < 0 ? "Thua" : "Hòa vốn",
          ])}
        />
      </DataPanel>
    </div>
  );
}

/* ──────────────────────────── TRADES PAGE ──────────────────────────── */

function Trades({ trades }: { trades: Trade[] }) {
  const [query, setQuery] = useState("");
  const [side, setSide] = useState("ALL");
  const [result, setResult] = useState("ALL");
  const [period, setPeriod] = useState<"TODAY" | "7D" | "30D" | "ALL">("ALL");
  const [referenceTime] = useState(() => new Date());

  const filteredTrades = trades.filter((trade) => {
    const createdAt = new Date(trade.created_at).getTime();
    if (period === "TODAY") {
      const today = new Date(referenceTime);
      today.setHours(0, 0, 0, 0);
      if (createdAt < today.getTime()) return false;
    } else if (period === "7D") {
      if (createdAt < referenceTime.getTime() - 7 * 24 * 60 * 60 * 1000) return false;
    } else if (period === "30D") {
      if (createdAt < referenceTime.getTime() - 30 * 24 * 60 * 60 * 1000) return false;
    }

    const okQuery = trade.symbol.includes(query.toUpperCase());
    const okSide = side === "ALL" || trade.side === side;
    const okResult =
      result === "ALL" ||
      (result === "WIN" ? trade.net_pnl > 0 : trade.net_pnl <= 0);
    return okQuery && okSide && okResult;
  });

  const totalTrades = filteredTrades.length;
  const wins = filteredTrades.filter((t) => t.net_pnl > 0).length;
  const losses = filteredTrades.filter((t) => t.net_pnl <= 0).length;
  const netPnl = filteredTrades.reduce((sum, t) => sum + t.net_pnl, 0);

  return (
    <div className="grid gap-4">
      {/* Summary Metrics */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Tổng giao dịch" value={String(totalTrades)} />
        <Metric
          label="Lệnh thắng"
          value={String(wins)}
          tone={wins > 0 ? "good" : "neutral"}
        />
        <Metric
          label="Lệnh thua"
          value={String(losses)}
          tone={losses > 0 ? "bad" : "neutral"}
        />
        <Metric
          label="PnL ròng"
          value={money(netPnl)}
          tone={netPnl >= 0 ? "good" : "bad"}
        />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          className="terminal-select"
          value={period}
          onChange={(e) => setPeriod(e.target.value as typeof period)}
        >
          <option value="TODAY">Hôm nay</option>
          <option value="7D">7 ngày</option>
          <option value="30D">30 ngày</option>
          <option value="ALL">Tất cả</option>
        </select>
        <SearchBox query={query} setQuery={setQuery} />
        <select
          className="terminal-select"
          onChange={(event) => setSide(event.target.value)}
          value={side}
        >
          <option value="ALL">Tất cả vị thế</option>
          <option value="LONG">Mua (LONG)</option>
          <option value="SHORT">Bán (SHORT)</option>
        </select>
        <select
          className="terminal-select"
          onChange={(event) => setResult(event.target.value)}
          value={result}
        >
          <option value="ALL">Tất cả kết quả</option>
          <option value="WIN">Lệnh thắng</option>
          <option value="LOSS">Lệnh thua</option>
        </select>
      </div>

      {/* Trades Table */}
      <div className="glass-card overflow-hidden">
        <Table
          columns={["Ngày", "Cặp", "Hướng", "Giá vào", "Giá thoát", "PnL", "Chiến lược", "Thời gian giữ"]}
          rows={filteredTrades.map((trade) => {
            const createdAt = new Date(trade.created_at);
            const closedAt = new Date(trade.created_at);
            const durationMs = closedAt.getTime() - createdAt.getTime();
            const durationHours = durationMs / (1000 * 60 * 60);
            let durationStr = "-";
            if (durationMs > 0) {
              if (durationHours < 1) {
                durationStr = `${Math.round(durationMs / (1000 * 60))}m`;
              } else if (durationHours < 24) {
                durationStr = `${Math.round(durationHours)}h`;
              } else {
                durationStr = `${Math.round(durationHours / 24)}d`;
              }
            }

            return [
              createdAt.toLocaleDateString("vi-VN"),
              trade.symbol,
              viSide(trade.side),
              money(trade.entry_price),
              money(trade.exit_price),
              money(trade.net_pnl),
              trade.reason || "-",
              durationStr,
            ];
          })}
        />
      </div>
    </div>
  );
}

/* ──────────────────────────── STRATEGIES PAGE ──────────────────────────── */

function Strategies({ scanner }: { scanner: ScannerResult[] }) {
  const strategies = useMemo(() => {
    const grouped = new Map<string, ScannerResult[]>();
    for (const item of scanner) {
      const name = item.strategy?.trim();
      if (!name) continue;
      grouped.set(name, [...(grouped.get(name) ?? []), item]);
    }
    return Array.from(grouped, ([name, items]) => {
      const actionable = items.filter((item) => item.action !== "NO_TRADE");
      const scores = items.map((item) => Math.max(item.long_score, item.short_score));
      const riskRewards = items.map((item) => item.risk_reward).filter((value): value is number => value !== null);
      return {
        name,
        items,
        actionable: actionable.length,
        averageScore: scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : 0,
        bestRiskReward: riskRewards.length ? Math.max(...riskRewards) : null,
        timeframes: Array.from(new Set(items.map((item) => item.timeframe))).join(", "),
        symbols: new Set(items.map((item) => item.symbol)).size,
        latest: items.reduce((latest, item) => item.scanned_at > latest ? item.scanned_at : latest, ""),
      };
    }).sort((left, right) => right.actionable - left.actionable || right.averageScore - left.averageScore);
  }, [scanner]);

  return <div className="grid gap-5">
    <PageHeader title="Chiến lược giao dịch" description="Trạng thái chiến lược được tổng hợp trực tiếp từ bộ quét và dữ liệu thị trường hiện tại." />
    {strategies.length ? <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
      {strategies.map((strategy) => <section className="glass-card flex min-w-0 flex-col" key={strategy.name}>
        <div className="flex items-start justify-between gap-3 border-b border-[var(--border-default)] pb-3">
          <div className="min-w-0"><h3 className="truncate font-bold">{strategy.name}</h3><p className="mt-1 text-xs text-[var(--text-muted)]">{strategy.timeframes || "Chưa xác định khung thời gian"}</p></div>
          <StatusChip label="Trạng thái" value="ĐANG QUÉT" safe />
        </div>
        <div className="mt-3 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--border-default)]">
          <StrategyMetric label="Điểm TB" value={number(strategy.averageScore)} tone={strategy.averageScore >= 70 ? "good" : "neutral"} />
          <StrategyMetric label="Tín hiệu" value={String(strategy.actionable)} tone={strategy.actionable ? "good" : "neutral"} />
          <StrategyMetric label="Số mã" value={String(strategy.symbols)} tone="neutral" />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2"><InfoPair label="R:R tốt nhất" value={strategy.bestRiskReward === null ? "Chưa có" : `${number(strategy.bestRiskReward)}R`} /><InfoPair label="Mẫu đã quét" value={String(strategy.items.length)} /></div>
        <p className="mt-3 border-t border-[var(--border-default)] pt-3 text-xs text-[var(--text-muted)]">Cập nhật gần nhất: {strategy.latest ? new Date(strategy.latest).toLocaleString("vi-VN") : "Chưa có"}</p>
      </section>)}
    </div> : <EmptyState title="Chưa có dữ liệu chiến lược" message="Backend chưa trả về chiến lược từ bộ quét. Không hiển thị dữ liệu mô phỏng." />}
  </div>;
}
function StrategyMetric({ label, value, tone }: { label: string; value: string; tone: "good" | "neutral" }) { return <div className="bg-[var(--bg-surface)] px-3 py-2.5"><p className="text-[10px] font-bold uppercase tracking-wide text-[var(--text-muted)]">{label}</p><p className={`mt-1 text-sm font-bold num-display ${tone === "good" ? "text-[var(--color-profit)]" : "text-[var(--text-primary)]"}`}>{value}</p></div>; }

/* ──────────────────────────── INFO PAIR ──────────────────────────── */

function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg bg-[rgba(255,255,255,0.03)] px-3 py-2">
      <span className="font-bold text-[var(--text-muted)] text-xs">{label}</span>
      <strong className="text-right text-sm num-display">{value}</strong>
    </div>
  );
}

/* ──────────────────────────── ANALYTICS PAGE ──────────────────────────── */

function Analytics({
  exitAnalytics,
  smartEntry,
  performance,
  trades,
}: {
  exitAnalytics: ExitAnalytics | null;
  smartEntry: SmartEntryPayload | null;
  performance: Performance | null;
  trades: Trade[];
}) {
  type Range = "7D" | "30D" | "90D" | "ALL";
  const [range, setRange] = useState<Range>("30D");
  const cutoff = { "7D": 7, "30D": 30, "90D": 90, ALL: Infinity }[range];
  const filteredTrades = useMemo(() => {
    if (cutoff === Infinity) return trades;
    const threshold = new Date();
    threshold.setDate(threshold.getDate() - cutoff);
    return trades.filter((trade) => new Date(trade.created_at) >= threshold);
  }, [cutoff, trades]);
  const analytics = useMemo(() => buildAnalytics(filteredTrades, performance), [filteredTrades, performance]);

  return <div className="space-y-5">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--color-ai)]">Phân tích hiệu suất</p><h2 className="mt-1 text-xl font-bold">Hiệu suất giao dịch</h2><p className="mt-1 text-sm text-[var(--text-muted)]">Phân tích kết quả theo thời gian, chiến lược và mã giao dịch.</p></div><div className="inline-flex w-fit rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-1">{(["7D", "30D", "90D", "ALL"] as Range[]).map((item) => <button className={`rounded-md px-3 py-1.5 text-xs font-bold transition ${range === item ? "bg-[var(--color-info)] text-white" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"}`} key={item} onClick={() => setRange(item)} type="button">{item}</button>)}</div></div>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><Metric label="PnL ròng" value={money(analytics.netPnl)} tone={analytics.netPnl >= 0 ? "good" : "bad"} /><Metric label="Tỷ lệ thắng" value={percent(analytics.winRate)} tone={analytics.winRate >= 50 ? "good" : "bad"} /><Metric label="Hệ số lợi nhuận" value={analytics.profitFactor === null ? "–" : analytics.profitFactor.toFixed(2)} tone={(analytics.profitFactor ?? 0) >= 1 ? "good" : "bad"} /><Metric label="Sụt giảm tối đa" value={percent(analytics.maxDrawdown)} tone="bad" /><Metric label="Hệ số Sharpe" value={performance ? number(performance.sharpe) : "–"} tone={(performance?.sharpe ?? 0) > 0 ? "good" : "neutral"} /></div>
    <section className="glass-card p-4 lg:p-5"><div className="flex items-center justify-between gap-3"><div><h3 className="font-bold">Đường cong vốn</h3><p className="mt-1 text-xs text-[var(--text-muted)]">Diễn biến vốn dựa trên các lệnh đã đóng trong kỳ.</p></div><span className={`text-sm font-bold num-display ${analytics.netPnl >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]"}`}>{analytics.netPnl >= 0 ? "+" : ""}{money(analytics.netPnl)}</span></div><AnalyticsEquityCurve points={analytics.equityPoints} /></section>
    <div className="grid gap-4 xl:grid-cols-2"><AnalyticsBreakdown title="Hiệu suất theo chiến lược" subtitle="Nhóm theo chiến lược và lý do từ dữ liệu giao dịch." rows={analytics.byStrategy} /><AnalyticsBreakdown title="Hiệu suất theo mã" subtitle="Các mã có kết quả trong kỳ đã chọn." rows={analytics.bySymbol} /></div>
    <section className="glass-card p-4 lg:p-5"><div><h3 className="font-bold">Lịch giao dịch</h3><p className="mt-1 text-xs text-[var(--text-muted)]">Mỗi ô là PnL ròng của một ngày giao dịch. Đậm hơn = biên độ lớn hơn.</p></div><TradingHeatmap days={analytics.calendar} /></section>
    <div className="grid gap-4 md:grid-cols-3"><Metric label="Lệnh trong kỳ" value={String(filteredTrades.length)} /><Metric label="Lệnh thắng" value={String(analytics.wins)} tone="good" /><Metric label="Lệnh thua" value={String(analytics.losses)} tone="bad" /></div>
    <ExitAnalyticsPanel analytics={exitAnalytics} /><SmartEntryPanel analytics={smartEntry} />
  </div>;
}

type AnalyticsRow = { name: string; pnl: number; trades: number; winRate: number };
function buildAnalytics(trades: Trade[], performance: Performance | null) {
  const sorted = [...trades].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const netPnl = sorted.reduce((sum, item) => sum + item.net_pnl, 0);
  const wins = sorted.filter((item) => item.net_pnl > 0).length;
  const losses = sorted.filter((item) => item.net_pnl < 0).length;
  const grossProfit = sorted.filter((item) => item.net_pnl > 0).reduce((sum, item) => sum + item.net_pnl, 0);
  const grossLoss = Math.abs(sorted.filter((item) => item.net_pnl < 0).reduce((sum, item) => sum + item.net_pnl, 0));
  let equity = performance?.initial_capital ?? 0; let peak = equity; let maxDrawdown = 0;
  const equityPoints = sorted.map((item) => { equity += item.net_pnl; peak = Math.max(peak, equity); maxDrawdown = Math.max(maxDrawdown, peak ? ((peak - equity) / peak) * 100 : 0); return equity; });
  const toRows = (key: (trade: Trade) => string): AnalyticsRow[] => Object.entries(sorted.reduce<Record<string, Trade[]>>((groups, trade) => { const name = key(trade); (groups[name] ||= []).push(trade); return groups; }, {})).map(([name, items]) => ({ name, pnl: items.reduce((sum, item) => sum + item.net_pnl, 0), trades: items.length, winRate: items.filter((item) => item.net_pnl > 0).length / items.length * 100 })).sort((a, b) => b.pnl - a.pnl);
  const dates = Array.from({ length: 35 }, (_, index) => { const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - 34 + index); return day; });
  const calendar = dates.map((date) => { const id = date.toISOString().slice(0, 10); return { date: id, pnl: sorted.filter((item) => new Date(item.created_at).toISOString().slice(0, 10) === id).reduce((sum, item) => sum + item.net_pnl, 0) }; });
  return { netPnl, wins, losses, winRate: sorted.length ? wins / sorted.length * 100 : 0, profitFactor: grossLoss ? grossProfit / grossLoss : grossProfit ? null : 0, maxDrawdown, equityPoints, byStrategy: toRows((item) => item.reason || "Unclassified"), bySymbol: toRows((item) => item.symbol), calendar };
}
function AnalyticsEquityCurve({ points }: { points: number[] }) { if (!points.length) return <EmptyState title="Chưa có đường cong vốn" message="Chưa có lệnh đã đóng trong khoảng thời gian đã chọn." />; const min = Math.min(...points); const max = Math.max(...points); const polyline = points.map((value, index) => `${(index / Math.max(1, points.length - 1)) * 100},${100 - ((value - min) / Math.max(1, max - min)) * 82 - 9}`).join(" "); return <svg aria-label="Đường cong vốn" className="mt-5 h-64 w-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 100"><defs><linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1"><stop stopColor="#22c55e" stopOpacity=".28"/><stop offset="1" stopColor="#22c55e" stopOpacity="0"/></linearGradient></defs><polyline fill="none" points={polyline} stroke="#22c55e" strokeWidth="1.5" vectorEffect="non-scaling-stroke"/></svg>; }
function AnalyticsBreakdown({ title, subtitle, rows }: { title: string; subtitle: string; rows: AnalyticsRow[] }) { return <section className="glass-card overflow-hidden"><div className="border-b border-[var(--border-default)] p-4"><h3 className="font-bold">{title}</h3><p className="mt-1 text-xs text-[var(--text-muted)]">{subtitle}</p></div>{rows.length ? <div className="divide-y divide-[var(--border-default)]">{rows.slice(0, 6).map((row) => <div className="grid grid-cols-[1fr_auto_auto] items-center gap-3 px-4 py-3 text-sm" key={row.name}><div className="min-w-0"><p className="truncate font-semibold">{row.name}</p><p className="mt-0.5 text-xs text-[var(--text-muted)]">{row.trades} trades · {row.winRate.toFixed(0)}% win</p></div><span className={`num-display font-bold ${row.pnl >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]"}`}>{row.pnl >= 0 ? "+" : ""}{money(row.pnl)}</span><span className="h-2 w-2 rounded-full bg-[var(--color-info)]" /></div>)}</div> : <div className="p-4"><EmptyState title="Chưa có dữ liệu" message="Chọn khoảng thời gian khác hoặc chờ thêm lệnh được đóng." /></div>}</section>; }
function TradingHeatmap({ days }: { days: Array<{ date: string; pnl: number }> }) { const magnitude = Math.max(...days.map((day) => Math.abs(day.pnl)), 1); return <div className="mt-5 grid grid-cols-7 gap-2">{days.map((day) => { const opacity = Math.max(.12, Math.abs(day.pnl) / magnitude); const bg = day.pnl > 0 ? `rgba(34, 197, 94, ${opacity})` : day.pnl < 0 ? `rgba(239, 68, 68, ${opacity})` : "rgba(255,255,255,.035)"; return <div className="group relative aspect-square min-h-10 rounded-md border border-white/[0.04] p-1.5" key={day.date} style={{ background: bg }} title={`${day.date}: ${money(day.pnl)}`}><span className="text-[10px] text-[var(--text-secondary)]">{new Date(`${day.date}T00:00:00`).getDate()}</span><span className="absolute bottom-1.5 right-1.5 text-[9px] font-bold text-white/80">{day.pnl ? `${day.pnl > 0 ? "+" : ""}${Math.round(day.pnl)}` : ""}</span></div>; })}</div>; }

/* ──────────────────────────── EXIT ANALYTICS ──────────────────────────── */

function ExitAnalyticsPanel({ analytics }: { analytics: ExitAnalytics | null }) {
  const lifecycleMetrics = [
    ["Realized R", analytics?.realized_r, analytics?.realized_r_availability],
    ["MAE trung bình", analytics?.excursion.mae_r, analytics?.mae_availability],
    ["MFE trung bình", analytics?.excursion.mfe_r, analytics?.mfe_availability],
    ["Missed R trung bình", analytics?.excursion.missed_r, analytics?.missed_r_availability],
  ] as const;

  return (
    <section className="glass-card p-4 md:col-span-3 border-[var(--color-info)]/10">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-bold">Phân tích thoát lệnh · chỉ đọc</h3>
          <p className="mt-1 text-xs text-[var(--text-muted)]">
            Quan sát lịch sử thoát lệnh, không thay đổi cắt lỗ, chốt lời hoặc quá trình thực thi.
          </p>
        </div>
        <StatusChip label="Chế độ" value={analytics?.read_only ? "READ-ONLY" : "Đang tải"} safe={!!analytics?.read_only} />
      </div>
      <div className="grid gap-3 md:grid-cols-5">
        <Metric label="Lệnh đóng đã khớp" value={String(analytics?.summary.close_fills ?? 0)} />
        <Metric label="Realized PnL" value={money(analytics?.summary.realized_pnl)} />
        <Metric label="Commission" value={money(analytics?.summary.commission)} />
        <Metric label="Funding" value={money(analytics?.summary.funding)} />
        <Metric
          label="Net realized"
          value={money(analytics?.summary.net_realized_pnl)}
          tone={(analytics?.summary.net_realized_pnl ?? 0) >= 0 ? "good" : "bad"}
        />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <ExitBreakdown title="Theo nguyên nhân thoát" rows={analytics?.by_close_reason ?? []} />
        <ExitBreakdown title="Theo phía vị thế" rows={analytics?.by_side ?? []} />
        <ExitBreakdown title="Theo symbol" rows={analytics?.by_symbol ?? []} />
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-2">
        {lifecycleMetrics.map(([label, value, item]) => (
          <div className="rounded-lg bg-[rgba(255,255,255,0.03)] px-3 py-2 text-sm" key={label}>
            <strong>
              {label}: {item?.available && value != null ? `${value.toFixed(3)}R` : "Chưa đủ dữ liệu"}
            </strong>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Coverage {percent((item?.coverage ?? 0) * 100)} · {item?.reason ?? "Đã xác minh bằng lifecycle và nến đóng đầy đủ"}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-[var(--text-muted)]">
        Lifecycle đủ excursion: {analytics?.excursion.lifecycles ?? 0}. Không dùng nến entry đang hình thành hoặc nến chứa thời điểm thoát.
      </p>
      {(analytics?.notes ?? []).map((note) => (
        <p className="mt-2 text-xs text-[var(--text-muted)]" key={note}>• {note}</p>
      ))}
    </section>
  );
}

function ExitBreakdown({
  rows,
  title,
}: {
  rows: ExitAnalytics["by_symbol"];
  title: string;
}) {
  return (
    <div>
      <h4 className="mb-2 text-sm font-bold text-[var(--text-secondary)]">{title}</h4>
      <Table
        columns={["Nhóm", "Close fills", "Realized PnL"]}
        rows={rows.length
          ? rows.map((row) => [row.key, String(row.closes), money(row.realized_pnl)])
          : [["Chưa có dữ liệu", "0", money(0)]]}
      />
    </div>
  );
}

/* ──────────────────────────── SMART ENTRY PANEL ──────────────────────────── */

function SmartEntryPanel({ analytics }: { analytics: SmartEntryPayload | null }) {
  return (
    <section className="glass-card p-4 md:col-span-3 border-[var(--color-info)]/10">
      <h3 className="text-lg font-black">Phân tích điểm vào thông minh · chỉ quan sát</h3>
      <p className="mb-4 text-sm text-[var(--text-muted)]">Quan sát phương án từ nến đóng; không thay đổi Baseline hoặc gửi lệnh.</p>
      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="Tổng evidence" value={number(analytics?.summary.total ?? 0)} />
        <Metric label="Sẽ vào lệnh (mô phỏng)" value={number(analytics?.summary.WOULD_ENTER ?? 0)} />
        <Metric label="Bỏ qua (mô phỏng)" value={number(analytics?.summary.WOULD_SKIP ?? 0)} />
      </div>
      <div className="mt-3 grid gap-2 text-xs md:grid-cols-2">
        <p className="rounded-lg border border-[var(--color-profit)]/15 bg-[rgba(34,197,94,0.04)] p-2 text-[var(--color-profit)]"><b>Sẽ vào lệnh (mô phỏng):</b> đạt điều kiện Shadow để ghi nhận outcome; không gửi lệnh.</p>
        <p className="rounded-lg border border-[rgba(245,158,11,0.15)] bg-[rgba(245,158,11,0.04)] p-2 text-[var(--color-warning)]"><b>Bỏ qua (mô phỏng):</b> chưa đạt điều kiện hoặc thiếu dữ liệu xác minh; không gửi lệnh.</p>
      </div>
      <div className="mt-4 glass-card p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <b>Outcome collector</b>
          <span className={analytics?.collector.last_error ? "text-[var(--color-loss)]" : analytics?.collector.running ? "text-[var(--color-profit)]" : "text-[var(--color-warning)]"}>
            {analytics?.collector.last_error ? "RETRYING" : analytics?.collector.running ? "RUNNING" : "STOPPED"}
          </span>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <Metric label="Coverage hoàn tất" value={percent(analytics?.collector.coverage.completion_ratio ?? 0)} />
          <Metric label="Backlog / retry" value={`${number(analytics?.collector.coverage.pending_decisions ?? 0)} / ${number(analytics?.collector.coverage.retrying_decisions ?? 0)}`} />
          <Metric label="Lỗi vĩnh viễn" value={number(analytics?.collector.coverage.permanent_errors ?? 0)} />
          <Metric label="Outcome 4/12/24" value={`${number(analytics?.collector.coverage.outcomes_by_horizon["4"] ?? 0)} / ${number(analytics?.collector.coverage.outcomes_by_horizon["12"] ?? 0)} / ${number(analytics?.collector.coverage.outcomes_by_horizon["24"] ?? 0)}`} />
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <Metric label="Cycle đang chờ" value={number(analytics?.collector.last_cycle.decisions_pending ?? 0)} />
          <Metric label="Cycle hoàn tất" value={number(analytics?.collector.last_cycle.decisions_complete ?? 0)} />
          <Metric label="Cycle retry" value={number(analytics?.collector.last_cycle.decisions_retrying ?? 0)} />
          <Metric label="Outcome mới" value={number(analytics?.collector.last_cycle.outcomes_saved ?? 0)} />
        </div>
        {analytics?.collector.last_error && <p className="mt-2 break-all text-xs text-[var(--color-loss)]">Lần thử gần nhất: {analytics.collector.last_error}</p>}
        <p className="mt-2 text-xs text-[var(--text-muted)]">Chu kỳ {analytics?.collector.interval_seconds ?? 60}s · lần chạy gần nhất {analytics?.collector.last_run_at ? new Date(analytics.collector.last_run_at).toLocaleString("vi-VN") : "chưa chạy"} · backlog cũ nhất {analytics?.collector.coverage.oldest_pending_at ? new Date(analytics.collector.coverage.oldest_pending_at).toLocaleString("vi-VN") : "không có"} · lỗi liên tiếp {analytics?.collector.consecutive_failures ?? 0}</p>
      </div>
      <div className="mt-4 glass-card p-3 border-[var(--color-info)]/10">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <b>Báo cáo hiệu suất giả định</b>
          <span className="badge bg-[rgba(245,158,11,0.08)] text-[var(--color-warning)]">{analytics?.performance.confidence_status ?? "CHƯA ĐỦ DỮ LIỆU"}</span>
        </div>
        <p className="mt-1 text-xs text-[var(--text-muted)]">Cần tối thiểu {analytics?.performance.minimum_sample ?? 30} outcome; chỉ thống kê mô tả, không tối ưu threshold.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <Metric label="Sample outcome" value={number(analytics?.performance.sample_size ?? 0)} />
          <Metric label="Tỷ lệ thắng" value={analytics?.performance.overall.win_rate == null ? "Chưa có" : percent(analytics.performance.overall.win_rate)} />
          <Metric label="Return TB / trung vị" value={analytics?.performance.overall.average_return == null ? "Chưa có" : `${percent(analytics.performance.overall.average_return)} / ${percent(analytics.performance.overall.median_return ?? 0)}`} />
          <Metric label="MFE / MAE trung bình" value={analytics?.performance.overall.average_mfe == null ? "Chưa có" : `${percent(analytics.performance.overall.average_mfe)} / ${percent(analytics.performance.overall.average_mae ?? 0)}`} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">{Object.entries(analytics?.performance.dimensions.horizon ?? {}).map(([key, metric]) => <span className="rounded-lg bg-[rgba(255,255,255,0.03)] px-2 py-1" key={key}>{key} nến · n={metric.sample_size} · WR {metric.win_rate == null ? "-" : percent(metric.win_rate)} · TB {metric.average_return == null ? "-" : percent(metric.average_return)}</span>)}</div>
      </div>
      <div className="mt-4 grid gap-2">{(analytics?.items ?? []).slice(0, 15).map((item) => <div className="glass-card p-3" key={item.event_key}><div className="flex flex-wrap justify-between gap-2"><b>{item.symbol} · {item.side} · {item.timeframe}</b><span className={item.decision === "WOULD_ENTER" ? "text-[var(--color-profit)]" : "text-[var(--color-warning)]"}>{item.decision_label}</span></div><p className="mt-1 text-xs text-[var(--text-muted)]">{item.decision_description}</p><p className="mt-1 text-xs text-[var(--text-muted)]">Điểm {item.quality_score}/100 · Giá vào {number(item.entry_price)} · R:R {item.risk_reward === null ? "chưa xác minh" : number(item.risk_reward)} · {new Date(item.decision_at).toLocaleString("vi-VN")}</p>{item.reasons.length > 0 && <p className="mt-2 text-sm text-[var(--color-warning)]">{item.reasons.join("; ")}</p>}<div className="mt-2 flex flex-wrap gap-2 text-xs">{[4, 12, 24].map((horizon) => { const outcome = item.outcomes[String(horizon)]; return <span className="rounded-lg bg-[rgba(255,255,255,0.03)] px-2 py-1" key={horizon}>{horizon} nến: {outcome ? `${percent(outcome.return_fraction)} · MFE ${percent(outcome.mfe_fraction)} · MAE ${percent(outcome.mae_fraction)}` : "đang chờ đủ nến đóng"}</span>; })}</div></div>)}{(analytics?.items.length ?? 0) === 0 && <p className="text-sm text-[var(--text-muted)]">Chưa có phương án quan sát được ghi nhận.</p>}</div>
    </section>
  );
}

/* ──────────────────────────── RISK PAGE ──────────────────────────── */

function viRiskLevel(level: "LOW" | "MEDIUM" | "HIGH"): string {
  return level === "LOW" ? "THẤP" : level === "MEDIUM" ? "TRUNG BÌNH" : "CAO";
}

function RiskMeter({ label, value, max }: { label: string; value: number; max: number }) {
  const ratio = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const pct = Math.round(ratio * 100);
  const level: "LOW" | "MEDIUM" | "HIGH" = ratio < 0.45 ? "LOW" : ratio < 0.75 ? "MEDIUM" : "HIGH";
  const color = level === "LOW" ? "var(--color-profit)" : level === "MEDIUM" ? "var(--color-warning)" : "var(--color-loss)";
  const bg = level === "LOW" ? "rgba(34,197,94,0.08)" : level === "MEDIUM" ? "rgba(245,158,11,0.08)" : "rgba(239,68,68,0.08)";
  return (
    <div className="glass-card border border-white/[0.04] p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold uppercase tracking-wide text-[var(--text-muted)]">{label}</p>
        <span className="rounded-md px-2 py-1 text-[11px] font-bold" style={{ backgroundColor: bg, color }}>{viRiskLevel(level)}</span>
      </div>
      <div className="text-xl font-bold num-display" style={{ color }}>{money(value)}</div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.06]">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <p className="text-xs text-[var(--text-muted)]">{money(value)} / {money(max)}</p>
    </div>
  );
}

function RiskStatusBadge({ severity }: { severity: "LOW" | "MEDIUM" | "HIGH" }) {
  const map: Record<"LOW" | "MEDIUM" | "HIGH", [string, string, string]> = {
    LOW: ["RỦI RO THẤP", "var(--color-profit)", "rgba(34,197,94,0.08)"],
    MEDIUM: ["RỦI RO TRUNG BÌNH", "var(--color-warning)", "rgba(245,158,11,0.08)"],
    HIGH: ["RỦI RO CAO", "var(--color-loss)", "rgba(239,68,68,0.08)"],
  };
  const [label, color, bg] = map[severity];
  return (
    <div className="inline-flex items-center gap-2 rounded-lg border border-white/[0.06] px-3 py-2" style={{ backgroundColor: bg }}>
      <span className="status-dot" style={{ backgroundColor: color }} />
      <span className="text-sm font-bold" style={{ color }}>{label}</span>
    </div>
  );
}

function Risk({
  onDone,
  status,
  portfolioRisk,
}: {
  onDone: () => Promise<void>;
  status: StatusPayload | null;
  portfolioRisk: RiskPayload | null;
}) {
  const risk = status?.risk;
  const perf = status?.performance ?? null;
  const equity = status?.exchange?.balance?.margin_balance ?? 0;
  const readiness = status?.live_readiness;

  const exposure = portfolioRisk?.portfolio.gross_exposure ?? 0;
  const exposureLimit = risk?.max_portfolio_exposure
    ? risk.max_portfolio_exposure * ((equity ?? 0))
    : 0;
  const dailyLossUsed = perf ? Math.max(0, -(perf.net_pnl ?? 0)) : 0;
  const dailyLossLimit = risk?.max_daily_loss
    ? risk.max_daily_loss * ((equity ?? 0))
    : 0;
  const drawdown = perf ? Math.max(0, perf.max_drawdown ?? 0) : 0;
  const maxDrawdownPct = risk?.max_weekly_drawdown
    ? risk.max_weekly_drawdown * 100
    : 20;
  const currentDrawdownPct = equity > 0 ? (drawdown / equity) * 100 : 0;

  const ratioVal = (num: number, den: number) => (den > 0 ? num / den : 0);
  const worstRatio = Math.max(
    ratioVal(exposure, exposureLimit),
    ratioVal(dailyLossUsed, dailyLossLimit),
    ratioVal(currentDrawdownPct, maxDrawdownPct)
  );
  const riskStatus: "LOW" | "MEDIUM" | "HIGH" = worstRatio < 0.45 ? "LOW" : worstRatio < 0.75 ? "MEDIUM" : "HIGH";

  async function setCheck(key: keyof StatusPayload["live_readiness"], value: boolean) {
    await api.liveConfig({ [key]: value });
    await onDone();
  }

return (
    <div className="space-y-5">
  <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--color-info)]">Trung tâm rủi ro</p>
          <h2 className="mt-1 text-xl font-bold">Trung tâm rủi ro</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Tổng quan mức tiếp xúc, lỗ, sụt giảm và trạng thái rủi ro danh mục — ưu tiên rõ ràng, không gây rối.</p>
        </div>
        <RiskStatusBadge severity={riskStatus} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <RiskMeter label="Mức tiếp xúc hiện tại" value={exposure} max={exposureLimit} />
        <RiskMeter label="Mức tiếp xúc tối đa" value={exposureLimit} max={exposureLimit || 1} />
        <RiskMeter label="Lỗ trong ngày" value={dailyLossUsed} max={dailyLossLimit} />
        <RiskMeter label="Giới hạn lỗ ngày" value={dailyLossLimit} max={dailyLossLimit || 1} />
        <RiskMeter label="Mức sụt giảm" value={currentDrawdownPct} max={maxDrawdownPct} />
        <RiskMeter label="Sụt giảm tối đa" value={maxDrawdownPct} max={maxDrawdownPct || 1} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Trạng thái rủi ro" value={viRiskLevel(riskStatus)} tone={riskStatus === "HIGH" ? "bad" : riskStatus === "MEDIUM" ? "bad" : "good"} />
        <Metric label="Mức tiếp xúc hiện tại" value={`${money(exposure)} / ${money(exposureLimit)}`} />
        <Metric label="Mức tiếp xúc tối đa" value={money(exposureLimit)} />
        <Metric label="Lỗ trong ngày" value={`${money(dailyLossUsed)} / ${money(dailyLossLimit)}`} />
        <Metric label="Mức sụt giảm" value={`${percent(currentDrawdownPct)} / ${percent(maxDrawdownPct)}`} />
        <Metric label="Bộ máy rủi ro" value={portfolioRisk?.portfolio.mode ?? "N/A"} />
      </div>

      {(portfolioRisk?.portfolio.reasons.length ?? 0) > 0 && (
        <div className="rounded-lg border border-[rgba(239,68,68,0.18)] bg-[rgba(239,68,68,0.04)] px-4 py-3 text-sm text-[var(--color-loss)]">
          {portfolioRisk?.portfolio.reasons.join("; ")}
        </div>
      )}

      <DataPanel title="Bộ máy rủi ro danh mục · chế độ quan sát">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-[var(--text-muted)]">Chỉ quan sát và audit; chưa chặn Baseline DEMO, không tác động LIVE.</p>
          <span className="rounded-md bg-[rgba(245,158,11,0.08)] px-2 py-1 text-[11px] font-bold text-[var(--color-warning)]">ENFORCEMENT OFF</span>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <Metric label="Mức tiếp xúc gộp" value={`${money(portfolioRisk?.portfolio.gross_exposure)} · ${percent((portfolioRisk?.portfolio.gross_exposure_fraction ?? 0) * 100)}`} />
          <Metric label="Mức tiếp xúc ròng" value={`${money(portfolioRisk?.portfolio.net_exposure)} · ${percent((portfolioRisk?.portfolio.net_exposure_fraction ?? 0) * 100)}`} />
          <Metric label="Rủi ro mở đã xác minh" value={`${money(portfolioRisk?.portfolio.open_risk)} / ${money(portfolioRisk?.portfolio.open_risk_limit)}`} />
          <Metric label="Ngân sách rủi ro còn lại" value={money(portfolioRisk?.portfolio.open_risk_remaining)} />
          <Metric label="Giá trị LONG / SHORT" value={`${money(portfolioRisk?.portfolio.long_notional)} / ${money(portfolioRisk?.portfolio.short_notional)}`} />
          <Metric label="Quyết định quan sát" value={portfolioRisk?.portfolio.would_reject_new_entries ? "Sẽ từ chối lệnh mới" : "Còn dư địa theo danh mục"} />
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-xs text-[var(--text-muted)]">
              <tr>
                <th className="py-2">Symbol</th>
                <th>Phía / quantity</th>
                <th>Giá trị danh nghĩa</th>
                <th>Tỷ trọng</th>
                <th>Rủi ro đang mở</th>
                <th>Cắt lỗ</th>
              </tr>
            </thead>
            <tbody>
              {(portfolioRisk?.portfolio.positions ?? []).map((item) => (
                <tr className="border-t border-[var(--border-default)] table-row-hover" key={`${item.symbol}-${item.side}`}>
                  <td className="py-3 font-black num-display">{item.symbol}</td>
                  <td>{item.side} · {number(item.quantity)}</td>
                  <td className="num-display">{money(item.notional)}</td>
                  <td className="num-display">{percent(item.notional_fraction * 100)}</td>
                  <td className="num-display">{item.open_risk === null ? "Không xác minh" : money(item.open_risk)}</td>
                  <td className={item.protected ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]"}>{item.stop_loss ?? "Thiếu"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataPanel>

      <DataPanel title="LIVE preflight">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {([
            ["all_tests_pass", "All tests pass"],
            ["demo_stable", "Demo stable"],
            ["sl_protection_pass", "SL protection"],
            ["reconnect_pass", "Reconnect"],
            ["reconciliation_pass", "Reconciliation"],
            ["duplicate_order_tests_pass", "Duplicate order"],
          ] as const).map(([key, label]) => (
            <label className="glass-card flex items-center justify-between gap-3 px-3 py-3 text-sm font-bold cursor-pointer" key={key}>
              <span>{label}</span>
              <input checked={Boolean((readiness as Record<string, unknown> | null)?.[key])} onChange={(event) => void setCheck(key, event.target.checked)} type="checkbox" className="accent-cyan-500" />
            </label>
          ))}
        </div>
        {(readiness?.blockers?.length ?? 0) ? (
          <p className="mt-3 text-sm text-[var(--color-loss)]">{(readiness?.blockers ?? []).join(" / ")}</p>
        ) : null}
      </DataPanel>
    </div>
  );
}

/* ──────────────────────────── LOGS PAGE ──────────────────────────── */

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

/* ──────────────────────────── JOURNAL PAGE ──────────────────────────── */

const JOURNAL_FILTERS: { key: JournalCategory; label: string; color: string }[] = [
  { key: "ALL", label: "All", color: "var(--text-secondary)" },
  { key: "TRADING", label: "Giao dịch", color: "var(--color-info)" },
  { key: "AI", label: "AI", color: "var(--color-ai)" },
  { key: "RISK", label: "Rủi ro", color: "var(--color-warning)" },
  { key: "SYSTEM", label: "Hệ thống", color: "var(--text-muted)" },
  { key: "ERRORS", label: "Errors", color: "var(--color-loss)" },
];

const JOURNAL_CATEGORY_COLORS: Record<string, { bg: string; text: string; line: string }> = {
  TRADING: { bg: "rgba(59,130,246,0.10)", text: "var(--color-info)", line: "var(--color-info)" },
  AI: { bg: "rgba(167,139,250,0.10)", text: "var(--color-ai)", line: "var(--color-ai)" },
  RISK: { bg: "rgba(245,158,11,0.10)", text: "var(--color-warning)", line: "var(--color-warning)" },
  SYSTEM: { bg: "rgba(255,255,255,0.04)", text: "var(--text-muted)", line: "var(--text-muted)" },
  ERRORS: { bg: "rgba(239,68,68,0.10)", text: "var(--color-loss)", line: "var(--color-loss)" },
};

function JournalPage({
  entries,
  filter,
  onFilterChange,
  onRefresh,
}: {
  entries: JournalEntry[];
  filter: JournalCategory;
  onFilterChange: (category: JournalCategory) => void;
  onRefresh: () => Promise<void>;
}) {
  return (
    <div className="grid gap-4">
      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        {JOURNAL_FILTERS.map(({ key, label, color }) => {
          const active = filter === key;
          return (
            <button
              key={key}
              onClick={() => onFilterChange(key)}
              className="px-3 py-1.5 rounded-lg text-xs font-bold transition-all"
              style={
                active
                  ? {
                      background: "rgba(255,255,255,0.06)",
                      color,
                      border: `1px solid ${color}`,
                    }
                  : {
                      background: "transparent",
                      color: "var(--text-muted)",
                      border: "1px solid var(--border-default)",
                    }
              }
            >
              {label}
            </button>
          );
        })}
        <button
          onClick={() => void onRefresh()}
          className="ml-auto px-3 py-1.5 rounded-lg text-xs font-bold text-[var(--text-muted)] border border-[var(--border-default)] hover:bg-[rgba(255,255,255,0.03)] transition-all flex items-center gap-1.5"
          title="Làm mới"
        >
          <RefreshCw size={13} />
          Refresh
        </button>
      </div>

      {/* Timeline */}
      <section className="glass-card overflow-hidden">
        <div className="panel-header">
          <h3>Dòng thời gian ({entries.length})</h3>
        </div>
        <div className="relative p-4 md:p-5">
          {entries.length === 0 ? (
            <EmptyState
              message="Không có sự kiện nào cho bộ lọc hiện tại."
              title="Trống"
            />
          ) : (
            <div className="journal-timeline">
              {entries.map((entry, idx) => {
                const colors =
                  JOURNAL_CATEGORY_COLORS[entry.category] ??
                  JOURNAL_CATEGORY_COLORS.SYSTEM;
                return (
                  <div className="journal-entry" key={entry.id}>
                    {/* Vertical connector line */}
                    <div className="journal-connector">
                      <div
                        className="journal-dot"
                        style={{ background: colors.line }}
                      />
                      {idx < entries.length - 1 && (
                        <div className="journal-line" />
                      )}
                    </div>
                    {/* Content */}
                    <div className="journal-content">
                      <div className="flex items-center gap-3 mb-1">
                        <span className="journal-time num-display">
                          {(() => {
                            try {
                              const d = new Date(entry.timestamp);
                              return isNaN(d.getTime())
                                ? entry.timestamp
                                : d.toLocaleTimeString("vi-VN", {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                    second: "2-digit",
                                  });
                            } catch {
                              return entry.timestamp;
                            }
                          })()}
                        </span>
                        <span
                          className="journal-badge"
                          style={{
                            background: colors.bg,
                            color: colors.text,
                          }}
                        >
                          {entry.category}
                        </span>
                      </div>
                      <p className="journal-title">{entry.title}</p>
                      {entry.details && (
                        <p className="journal-details">{entry.details}</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

/* ──────────────────────────── SYSTEM STATUS DRAWER ──────────────────────────── */

type ServiceStatus = "OPERATIONAL" | "WARNING" | "ERROR" | "OFFLINE";

interface ServiceEntry {
  name: string;
  status: ServiceStatus;
  detail: string;
  icon: React.ReactNode;
}

function deriveSystemServices(
  status: StatusPayload | null,
  exchange: ExchangeSnapshot | null,
  operations: OperationsStatus | null,
): ServiceEntry[] {
  const apiStatus: ServiceStatus = status ? "OPERATIONAL" : "OFFLINE";
  const exchangeStatus: ServiceStatus =
    exchange?.connection === "CONNECTED"
      ? exchange.freshness === "LIVE"
        ? "OPERATIONAL"
        : "WARNING"
      : exchange?.connection === "SAFE_MODE"
        ? "ERROR"
        : "OFFLINE";
  const marketDataStatus: ServiceStatus =
    exchange?.freshness === "LIVE"
      ? "OPERATIONAL"
      : exchange?.freshness === "STALE"
        ? "WARNING"
        : "OFFLINE";
  const aiStatus: ServiceStatus =
    operations?.ai_analytics.collector?.running
      ? "OPERATIONAL"
      : operations?.ai_analytics.training?.mode
        ? "WARNING"
        : "OFFLINE";
  const telegramStatus: ServiceStatus =
    operations?.notifications.configured ? "OPERATIONAL" : "OFFLINE";
  const totalCacheHits = (operations?.gateway?.demo?.cache?.hits ?? 0) + (operations?.gateway?.live?.cache?.hits ?? 0);
  const totalCacheMisses = (operations?.gateway?.demo?.cache?.misses ?? 0) + (operations?.gateway?.live?.cache?.misses ?? 0);
  const cacheStatus: ServiceStatus =
    totalCacheHits + totalCacheMisses > 0
      ? totalCacheHits / (totalCacheHits + totalCacheMisses) > 0.5
        ? "OPERATIONAL"
        : "WARNING"
      : "OFFLINE";
  const reconcileStatus: ServiceStatus =
    operations?.reconciliation?.safe_mode
      ? "ERROR"
      : operations?.reconciliation?.last_reconciled_at
        ? "OPERATIONAL"
        : "OFFLINE";
  const marketWeight = operations?.gateway?.market?.usage?.market_weight_last_minute ?? 0;
  const rateLimitStatus: ServiceStatus =
    marketWeight > 0
      ? marketWeight < 50
        ? "OPERATIONAL"
        : marketWeight < 90
          ? "WARNING"
          : "ERROR"
      : "OFFLINE";
  const autoLoopStatus: ServiceStatus =
    status?.auto_trader?.running
      ? "OPERATIONAL"
      : "OFFLINE";

  return [
    { name: "API", status: apiStatus, detail: status ? "Backend đã kết nối" : "Đang kết nối...", icon: <Server size={14} /> },
    { name: "Sàn giao dịch", status: exchangeStatus, detail: viExchangeConnection(exchange?.connection), icon: <Building2 size={14} /> },
    { name: "Dữ liệu thị trường", status: marketDataStatus, detail: viExchangeFreshness(exchange?.freshness), icon: <BarChart3 size={14} /> },
    { name: "Bộ máy AI", status: aiStatus, detail: operations?.ai_analytics.training?.mode ?? "Đang tải", icon: <Brain size={14} /> },
    { name: "Telegram", status: telegramStatus, detail: operations?.notifications.configured ? "Đã kết nối" : "Đã tắt", icon: <MessageSquare size={14} /> },
    { name: "Bộ nhớ đệm", status: cacheStatus, detail: totalCacheHits + totalCacheMisses > 0 ? `${((totalCacheHits / (totalCacheHits + totalCacheMisses)) * 100).toFixed(0)}% lượt truy cập thành công` : "Đang tải", icon: <Database size={14} /> },
    { name: "Đối soát", status: reconcileStatus, detail: operations?.reconciliation?.last_reconciled_at ? `Lần cuối: ${new Date(operations.reconciliation.last_reconciled_at).toLocaleTimeString()}` : "Đang tải", icon: <GitCompare size={14} /> },
    { name: "Giới hạn API", status: rateLimitStatus, detail: marketWeight > 0 ? `Tải: ${marketWeight}/phút` : "Đang tải", icon: <Gauge size={14} /> },
    { name: "Vòng lặp tự động", status: autoLoopStatus, detail: status?.auto_trader?.running ? `Chu kỳ: ${status.auto_trader.cycles}` : "Đã dừng", icon: <RotateCw size={14} /> },
  ];
}

function statusClass(s: ServiceStatus): string {
  if (s === "OPERATIONAL") return "system-status-operational";
  if (s === "WARNING") return "system-status-warning";
  if (s === "ERROR") return "system-status-error";
  return "system-status-offline";
}

function viServiceStatus(status: ServiceStatus): string {
  if (status === "OPERATIONAL") return "HOẠT ĐỘNG";
  if (status === "WARNING") return "CẢNH BÁO";
  if (status === "ERROR") return "LỖI";
  return "NGẮT KẾT NỐI";
}

/* ── SystemStatusDrawer (Phase 16: enhanced with performance + runtime) ── */
function SystemStatusDrawerContent({
  onClose,
  services,
  wsState,
}: {
  onClose: () => void;
  services: ServiceEntry[];
  wsState: WsState;
}) {
  const [perfData, setPerfData] = useState<Performance | null>(null);
  useEffect(() => {
    api.performance().then(setPerfData).catch(() => {});
  }, []);
  const operational = services.filter((s) => s.status === "OPERATIONAL").length;
  const warnings = services.filter((s) => s.status === "WARNING").length;
  const errors = services.filter((s) => s.status === "ERROR" || s.status === "OFFLINE").length;
  const healthPct = services.length > 0 ? Math.round((operational / services.length) * 100) : 0;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div
        className="relative ml-auto flex h-full w-full max-w-sm flex-col border-l border-[var(--border-default)] bg-[var(--bg-elevated)] shadow-2xl system-status-drawer-panel"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border-default)] px-5 py-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)]">Trạng thái hệ thống</h3>
            <p className="mt-0.5 text-xs text-[var(--text-muted)]">
              {operational}/{services.length} dịch vụ hoạt động
            </p>
          </div>
          <button className="rounded-lg p-1.5 transition hover:bg-[rgba(255,255,255,0.06)]" onClick={onClose} type="button">
            <X size={16} className="text-[var(--text-muted)]" />
          </button>
        </div>

        {/* Health overview bar */}
        <div className="border-b border-[var(--border-default)] px-5 py-3">
          <div className="flex items-center justify-between text-[11px]">
            <span className="font-bold text-[var(--text-secondary)]">Sức khỏe hệ thống</span>
            <span className={`font-bold ${healthPct === 100 ? "text-[var(--color-profit)]" : healthPct > 60 ? "text-[var(--color-warning)]" : "text-[var(--color-loss)]"}`}>{healthPct}%</span>
          </div>
          <div className="mt-2 progress-track">
            <div
              className={`progress-fill ${healthPct === 100 ? "bg-[var(--color-profit)]" : healthPct > 60 ? "bg-[var(--color-warning)]" : "bg-[var(--color-loss)]"}`}
              style={{ width: `${healthPct}%` }}
            />
          </div>
          <div className="mt-2 flex gap-3 text-[10px] text-[var(--text-muted)]">
            <span className="flex items-center gap-1"><span className="status-dot status-dot-live" /> {operational} OK</span>
            {warnings > 0 && <span className="flex items-center gap-1"><span className="status-dot status-dot-stale" /> {warnings} Cảnh báo</span>}
            {errors > 0 && <span className="flex items-center gap-1"><span className="status-dot status-dot-offline" /> {errors} Lỗi</span>}
          </div>
        </div>

        {/* Runtime info */}
        <div className="border-b border-[var(--border-default)] px-5 py-3">
          <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Vận hành</span>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-3 py-2">
              <span className="text-[10px] text-[var(--text-muted)]">WebSocket</span>
              <span className={`mt-0.5 block text-xs font-bold ${wsState === "LIVE" ? "text-[var(--color-profit)]" : wsState === "STALE" ? "text-[var(--color-warning)]" : "text-[var(--color-loss)]"}`}>{viWsState(wsState)}</span>
            </div>
            <div className="rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-3 py-2">
              <span className="text-[10px] text-[var(--text-muted)]">Tổng vốn</span>
              <span className="mt-0.5 block text-xs font-bold text-[var(--text-primary)]">{perfData ? money(perfData.equity) : "-"}</span>
            </div>
            <div className="rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-3 py-2">
              <span className="text-[10px] text-[var(--text-muted)]">PnL ròng</span>
              <span className={`mt-0.5 block text-xs font-bold ${(perfData?.net_pnl ?? 0) >= 0 ? "text-[var(--color-profit)]" : "text-[var(--color-loss)]"}`}>{perfData ? money(perfData.net_pnl) : "-"}</span>
            </div>
            <div className="rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.02)] px-3 py-2">
              <span className="text-[10px] text-[var(--text-muted)]">Tỷ lệ thắng</span>
              <span className="mt-0.5 block text-xs font-bold text-[var(--text-primary)]">{perfData ? percent(perfData.win_rate * 100) : "-"}</span>
            </div>
          </div>
        </div>

        {/* Services list */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-5 pt-3 pb-1">
            <span className="text-[10px] font-bold uppercase text-[var(--text-muted)]">Dịch vụ</span>
          </div>
          {services.map((service) => (
            <div className="flex items-center justify-between border-b border-white/[0.03] px-5 py-3 last:border-b-0 transition hover:bg-[rgba(255,255,255,0.02)]" key={service.name}>
              <div className="flex items-center gap-3">
                <span className="text-[var(--text-muted)]">{service.icon}</span>
                <span className="text-sm font-semibold text-[var(--text-primary)]">{service.name}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold ${statusClass(service.status)}`}>{viServiceStatus(service.status)}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="border-t border-[var(--border-default)] px-5 py-3">
          <div className="flex items-center justify-between">
            <p className="text-[10px] text-[var(--text-muted)]">Cập nhật lần cuối: {new Date().toLocaleTimeString("vi-VN")}</p>
            <button className="text-[10px] font-bold text-[var(--color-info)] hover:opacity-80 transition" onClick={() => api.performance().then(setPerfData).catch(() => {})} type="button">Làm mới</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SystemStatusDrawer({
  open,
  onClose,
  services,
  wsState,
}: {
  open: boolean;
  onClose: () => void;
  services: ServiceEntry[];
  wsState: WsState;
}) {
  if (!open) return null;
  return <SystemStatusDrawerContent onClose={onClose} services={services} wsState={wsState} />;
}

/* ──────────────────────────── SETTINGS PAGE (REDESIGN PHASE 14) ──────────────────────────── */

function SettingsSection({
  title,
  icon,
  color,
  count,
  defaultOpen = true,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  color: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="glass-card overflow-hidden">
      <button
        className="flex w-full items-center justify-between px-4 py-3.5 text-left transition hover:bg-[rgba(255,255,255,0.02)]"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: `${color}15`, color }}>
            {icon}
          </div>
          <span className="text-sm font-bold text-[var(--text-primary)]">{title}</span>
          {count !== undefined && (
            <span className="rounded-md bg-[rgba(255,255,255,0.04)] px-1.5 py-0.5 text-[10px] font-bold text-[var(--text-muted)]">
              {count}
            </span>
          )}
        </div>
        <ChevronRight size={14} className={`text-[var(--text-muted)] transition-transform ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-[var(--border-default)] px-4 py-1">
          {children}
        </div>
      )}
    </div>
  );
}

function SettingsRow({
  title,
  desc,
  children,
}: {
  title: string;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 border-b border-white/[0.03] py-3 last:border-b-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0 flex-1">
        <span className="text-sm font-semibold text-[var(--text-primary)]">{title}</span>
        {desc && <span className="mt-0.5 block text-[11px] leading-4 text-[var(--text-muted)]">{desc}</span>}
      </div>
      <div className="w-full flex-shrink-0 sm:w-auto sm:min-w-[180px]">{children}</div>
    </div>
  );
}

function SettingsPage({
  aiConfig,
  onSaved,
  settings,
}: {
  aiConfig: AIShadowConfig | null;
  onSaved: () => Promise<void>;
  settings: BotSettings;
}) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [aiDraft, setAiDraft] = useState<AIShadowConfig | null>(aiConfig);
  const [aiSaving, setAiSaving] = useState(false);
  const [aiMsg, setAiMsg] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  async function save() {
    setSaving(true);
    await api.updateSettings(draft);
    await onSaved();
    setSaving(false);
  }

  async function saveAi() {
    if (!aiDraft) return;
    setAiSaving(true);
    setAiMsg(null);
    try {
      const updated = await api.updateAiConfig({
        model: aiDraft.model,
        outcome_horizon: aiDraft.outcome_horizon,
        minimum_training_samples: aiDraft.minimum_training_samples,
      });
      setAiDraft(updated);
      setAiMsg("Đã lưu cấu hình AI.");
      await onSaved();
    } catch (err) {
      setAiMsg(err instanceof Error ? err.message : "Lỗi khi lưu cấu hình AI.");
    } finally {
      setAiSaving(false);
    }
  }

  const q = searchQuery.toLowerCase();
  const matchSearch = (label: string, desc?: string) =>
    !q || label.toLowerCase().includes(q) || (desc ?? "").toLowerCase().includes(q);

  const tradingCount = 8;
  const riskCount = 9;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--text-muted)]">Cấu hình</p>
          <h2 className="mt-1 text-xl font-bold">Cài đặt</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Tham số giao dịch, giới hạn rủi ro và cấu hình hệ thống.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative flex-1 sm:w-56">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              className="terminal-input w-full pl-8 pr-3 text-xs"
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm cài đặt..."
              value={searchQuery}
            />
          </div>
          <button className="btn-primary" disabled={saving} onClick={() => void save()} type="button">
            {saving ? (
              <span className="flex items-center gap-2"><RefreshCw size={12} className="animate-spin" /> Đang lưu</span>
            ) : (
              <span className="flex items-center gap-2"><Settings size={13} /> Lưu</span>
            )}
          </button>
        </div>
      </div>

      {/* 2-column grid on large screens */}
      <div className="grid gap-4 2xl:grid-cols-2">
        {/* ── TRADING ── */}
        <SettingsSection title="Giao dịch" icon={<BarChart3 size={14} />} color="var(--color-info)" count={tradingCount}>
          {matchSearch("Universe Mode", "VALIDATION vs ALL_MARKET") && (
            <SettingsRow title="Phạm vi thị trường" desc="VALIDATION dùng danh sách cho phép. ALL_MARKET quét toàn bộ hợp đồng USD-M có áp dụng bộ lọc.">
              <select className="terminal-select" value={draft.universe_mode} onChange={(e) => setDraft({ ...draft, universe_mode: e.target.value as "VALIDATION" | "ALL_MARKET" })}>
                <option value="VALIDATION">Kiểm định (danh sách cho phép)</option>
                <option value="ALL_MARKET">Toàn thị trường (có kiểm soát)</option>
              </select>
            </SettingsRow>
          )}
          {matchSearch("Số mã quét tối đa", "Số mã tối đa") && (
            <SettingsRow title="Số mã quét tối đa" desc="Số mã tối đa được quét trong mỗi chu kỳ.">
              <NumberField label="" value={draft.max_scan_symbols} onChange={(v) => setDraft({ ...draft, max_scan_symbols: v })} />
            </SettingsRow>
          )}
          {matchSearch("Khối lượng tối thiểu", "khối lượng 24 giờ") && (
            <SettingsRow title="Khối lượng tối thiểu" desc="Bộ lọc khối lượng định giá tối thiểu trong 24 giờ.">
              <NumberField label="" value={draft.min_quote_volume} onChange={(v) => setDraft({ ...draft, min_quote_volume: v })} />
            </SettingsRow>
          )}
          {matchSearch("Chênh lệch tối đa", "chênh lệch mua bán") && (
            <SettingsRow title="Chênh lệch tối đa (bps)" desc="Chênh lệch giá mua-bán tối đa theo điểm cơ bản.">
              <NumberField label="" value={draft.max_spread_bps} onChange={(v) => setDraft({ ...draft, max_spread_bps: v })} />
            </SettingsRow>
          )}
          {matchSearch("Tuổi niêm yết tối thiểu", "số ngày niêm yết") && (
            <SettingsRow title="Tuổi niêm yết tối thiểu (ngày)" desc="Số ngày niêm yết tối thiểu để một mã được xem xét.">
              <NumberField label="" value={draft.min_listing_age_days} onChange={(v) => setDraft({ ...draft, min_listing_age_days: v })} />
            </SettingsRow>
          )}
          {matchSearch("Min Score to Trade", "AI score required") && (
            <SettingsRow title="Điểm tối thiểu để giao dịch" desc="Điểm AI tối thiểu cần có để vào giao dịch.">
              <NumberField label="" value={draft.min_score_to_trade} onChange={(v) => setDraft({ ...draft, min_score_to_trade: v })} />
            </SettingsRow>
          )}
          {matchSearch("Phí taker", "kiểm thử chiến lược") && (
            <SettingsRow title="Tỷ lệ phí taker" desc="Mức phí taker dự kiến dùng khi kiểm thử chiến lược.">
              <NumberField label="" step={0.0001} value={draft.taker_fee_rate} onChange={(v) => setDraft({ ...draft, taker_fee_rate: v })} />
            </SettingsRow>
          )}
          {matchSearch("Trượt giá", "điểm cơ bản") && (
            <SettingsRow title="Trượt giá (bps)" desc="Mức trượt giá dự kiến theo điểm cơ bản.">
              <NumberField label="" value={draft.slippage_bps} onChange={(v) => setDraft({ ...draft, slippage_bps: v })} />
            </SettingsRow>
          )}
        </SettingsSection>

        {/* ── RISK ── */}
        <SettingsSection title="Quản trị rủi ro" icon={<Shield size={14} />} color="var(--color-warning)" count={riskCount}>
          {matchSearch("Risk per Trade", "Fraction of equity") && (
            <SettingsRow title="Rủi ro mỗi giao dịch" desc="Tỷ lệ vốn chịu rủi ro cho mỗi giao dịch.">
              <NumberField label="" step={0.0005} value={draft.risk_per_trade} onChange={(v) => setDraft({ ...draft, risk_per_trade: v })} />
            </SettingsRow>
          )}
          {matchSearch("Max Risk per Trade", "Hard cap") && (
            <SettingsRow title="Rủi ro tối đa mỗi giao dịch" desc="Giới hạn cứng tỷ lệ rủi ro cho một giao dịch.">
              <NumberField label="" step={0.001} value={draft.max_risk_per_trade} onChange={(v) => setDraft({ ...draft, max_risk_per_trade: v })} />
            </SettingsRow>
          )}
          {matchSearch("Total Open Risk", "aggregate open risk") && (
            <SettingsRow title="Tổng rủi ro đang mở" desc="Tổng rủi ro tối đa trên mọi vị thế đang mở.">
              <NumberField label="" step={0.001} value={draft.max_total_open_risk} onChange={(v) => setDraft({ ...draft, max_total_open_risk: v })} />
            </SettingsRow>
          )}
          {matchSearch("Ký quỹ tối đa mỗi giao dịch", "ký quỹ phân bổ") && (
            <SettingsRow title="Ký quỹ tối đa mỗi giao dịch" desc="Mức ký quỹ tối đa phân bổ cho một giao dịch.">
              <NumberField label="" step={0.01} value={draft.max_margin_per_trade} onChange={(v) => setDraft({ ...draft, max_margin_per_trade: v })} />
            </SettingsRow>
          )}
          {matchSearch("Tổng ký quỹ", "tổng ký quỹ") && (
            <SettingsRow title="Tổng ký quỹ tối đa" desc="Tổng mức ký quỹ tối đa trên mọi vị thế.">
              <NumberField label="" step={0.01} value={draft.max_total_margin} onChange={(v) => setDraft({ ...draft, max_total_margin: v })} />
            </SettingsRow>
          )}
          {matchSearch("Daily Loss Limit", "daily loss") && (
            <SettingsRow title="Giới hạn lỗ trong ngày" desc="Mức lỗ tối đa trong ngày theo tỷ lệ vốn trước khi dừng.">
              <NumberField label="" step={0.001} value={draft.max_daily_loss} onChange={(v) => setDraft({ ...draft, max_daily_loss: v })} />
            </SettingsRow>
          )}
          {matchSearch("Sụt giảm tuần", "sụt giảm tuần") && (
            <SettingsRow title="Sụt giảm tối đa trong tuần" desc="Mức sụt giảm tối đa trong tuần theo tỷ lệ vốn.">
              <NumberField label="" step={0.001} value={draft.max_weekly_drawdown} onChange={(v) => setDraft({ ...draft, max_weekly_drawdown: v })} />
            </SettingsRow>
          )}
          {matchSearch("Đòn bẩy tối đa", "đòn bẩy được phép") && (
            <SettingsRow title="Đòn bẩy tối đa" desc="Mức đòn bẩy tối đa được phép cho mọi vị thế.">
              <NumberField label="" value={draft.max_leverage} onChange={(v) => setDraft({ ...draft, max_leverage: v })} />
            </SettingsRow>
          )}
          {matchSearch("Max Open Positions", "concurrent open") && (
            <SettingsRow title="Số vị thế mở tối đa" desc="Số vị thế được phép mở đồng thời.">
              <NumberField label="" value={draft.max_open_positions} onChange={(v) => setDraft({ ...draft, max_open_positions: v })} />
            </SettingsRow>
          )}
        </SettingsSection>

        {/* ── AI ── */}
        <SettingsSection title="AI quan sát" icon={<Brain size={14} />} color="var(--color-ai)">
          <div className="mx-1 mt-2">
            <span className="inline-flex items-center gap-1.5 rounded-md bg-[rgba(245,158,11,0.08)] px-2 py-1 text-[10px] font-bold text-[var(--color-warning)]">
              CHỈ QUAN SÁT · CHỈ ĐỌC
            </span>
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              AI chỉ thu thập và chấm điểm tín hiệu giả định. Không đặt hay thực thi lệnh.
            </p>
          </div>
          {aiDraft ? (
            <>
              {matchSearch("Model", "AI model identifier") && (
                <SettingsRow title="Mô hình" desc="Định danh mô hình AI dùng để chấm điểm.">
                  <input className="terminal-input" maxLength={120} onChange={(e) => setAiDraft({ ...aiDraft, model: e.target.value })} type="text" value={aiDraft.model} />
                </SettingsRow>
              )}
              {matchSearch("Outcome Horizon", "candles to evaluate") && (
                <SettingsRow title="Khoảng đánh giá kết quả" desc="Số nến dùng để đánh giá kết quả (4–96).">
                  <NumberField label="" value={aiDraft.outcome_horizon} onChange={(v) => setAiDraft({ ...aiDraft, outcome_horizon: Math.min(96, Math.max(4, v)) })} />
                </SettingsRow>
              )}
              {matchSearch("Min Training Samples", "minimum samples") && (
                <SettingsRow title="Mẫu huấn luyện tối thiểu" desc="Số mẫu tối thiểu trước khi báo cáo hiệu suất (50–10000).">
                  <NumberField label="" value={aiDraft.minimum_training_samples} onChange={(v) => setAiDraft({ ...aiDraft, minimum_training_samples: Math.min(10000, Math.max(50, v)) })} />
                </SettingsRow>
              )}
              <div className="flex items-center justify-between border-t border-[rgba(255,255,255,0.04)] py-3">
                <span className="text-xs text-[var(--text-secondary)]">{aiMsg}</span>
                <button className="btn-primary !bg-[var(--color-ai)] hover:!brightness-110" disabled={aiSaving} onClick={() => void saveAi()} type="button">
                  {aiSaving ? "Đang lưu..." : "Lưu cấu hình AI"}
                </button>
              </div>
            </>
          ) : (
            <div className="py-6 text-center text-sm text-[var(--text-muted)]">Đang tải cấu hình AI...</div>
          )}
        </SettingsSection>

        {/* ── NOTIFICATIONS ── */}
        <SettingsSection title="Thông báo" icon={<Bell size={14} />} color="var(--color-profit)" defaultOpen={false}>
          <div className="py-6 text-center text-sm text-[var(--text-muted)]">
            Cài đặt thông báo Telegram được quản lý bằng lệnh của bot.
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              Dùng /status để kiểm tra trạng thái thông báo. Mọi lần truy cập trái phép đều được ghi nhật ký.
            </p>
          </div>
        </SettingsSection>

        {/* ── SYSTEM ── */}
        <SettingsSection title="Hệ thống" icon={<Server size={14} />} color="var(--text-muted)" defaultOpen={false}>
          <div className="py-6 text-center text-sm text-[var(--text-muted)]">
            Kết nối sàn, bộ nhớ đệm và đối soát được quản lý bởi backend.
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              Giới hạn API và chu kỳ tự động được cấu hình phía máy chủ.
            </p>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}

/* ──────────────────────────── BOT CONTROLS ──────────────────────────── */

function BotControls({
  onDone,
  status,
}: {
  onDone: () => Promise<void>;
  status: StatusPayload | null;
}) {
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
  async function resetSafeMode() {
    if (
      !window.confirm(
        "Reset SAFE_MODE sau khi backend kiểm tra exchange và SL bảo vệ?",
      )
    )
      return;
    setBusy("reset-safe-mode");
    try {
      const response = await api.resetSafeMode();
      if (!response.accepted && response.reason) window.alert(response.reason);
      await onDone();
    } finally {
      setBusy(null);
    }
  }
  const disabled = busy !== null;
  const canResetSafeMode =
    status?.bot_state === "SAFE_MODE" || status?.safe_mode === true;
  return (
    <div className="flex flex-wrap gap-1">
      <div className="flex rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.03)] p-0.5">
        <ActionIcon
          busy={busy === "start"}
          disabled={disabled}
          label="Chạy bot"
          onClick={() => void act("start")}
          tone="safe"
        >
          <Play size={15} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "pause"}
          disabled={disabled}
          label="Tạm dừng bot"
          onClick={() => void act("pause")}
          tone="warning"
        >
          <Pause size={15} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "stop"}
          disabled={disabled}
          label="Dừng bot"
          onClick={() => void act("stop")}
          tone="danger"
        >
          <Square size={15} />
        </ActionIcon>
      </div>
      {canResetSafeMode && (
        <div className="flex rounded-lg border border-[rgba(245,158,11,0.2)] bg-[rgba(245,158,11,0.06)] p-0.5">
          <ActionIcon
            busy={busy === "reset-safe-mode"}
            disabled={disabled}
            label="Reset SAFE_MODE"
            onClick={() => void resetSafeMode()}
            tone="warning"
          >
            <RefreshCw size={15} />
          </ActionIcon>
        </div>
      )}
      <div className="flex rounded-lg border border-[rgba(239,68,68,0.15)] bg-[rgba(255,255,255,0.03)] p-0.5">
        <ActionIcon
          busy={busy === "pause-new-trades"}
          disabled={disabled}
          label="Tạm dừng lệnh mới"
          onClick={() => void control("pause-new-trades")}
          tone="warning"
        >
          <ShieldX size={15} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "cancel-orders"}
          disabled={disabled}
          label="Hủy order"
          onClick={() => void control("cancel-orders")}
          tone="orange"
        >
          <XCircle size={15} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "close-all"}
          disabled={disabled}
          label="Đóng toàn bộ vị thế"
          onClick={() => void control("close-all")}
          tone="danger"
        >
          <Trash2 size={15} />
        </ActionIcon>
        <ActionIcon
          busy={busy === "emergency"}
          disabled={disabled}
          label="Emergency Stop"
          onClick={() => void emergency()}
          tone="solidDanger"
        >
          <ShieldAlert size={15} />
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
    safe: "text-[var(--color-profit)] hover:bg-[rgba(34,197,94,0.08)]",
    warning: "text-[var(--color-warning)] hover:bg-[rgba(245,158,11,0.08)]",
    orange: "text-[var(--color-warning)] hover:bg-[rgba(245,158,11,0.1)]",
    danger: "text-[var(--color-loss)] hover:bg-[rgba(239,68,68,0.08)]",
    solidDanger: "bg-[var(--color-loss)] text-[var(--text-primary)] hover:bg-[var(--color-loss)]",
  };
  return (
    <button
      aria-label={label}
      className={`grid h-8 w-8 place-items-center rounded-md transition disabled:cursor-not-allowed disabled:opacity-40 ${toneClass[tone]}`}
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {busy ? <RefreshCw className="animate-spin" size={14} /> : children}
    </button>
  );
}

/* ──────────────────────────── LIVE QUICK ACTIONS ──────────────────────────── */

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
    return <StatusChip label="LIVE" value="Đang chạy tiền thật" danger />;
  }
  return (
    <div className="flex rounded-lg border border-[rgba(245,158,11,0.2)] bg-[rgba(245,158,11,0.06)] p-0.5">
      <button
        className="min-h-8 rounded-md px-3 text-xs font-bold text-[var(--color-warning)] transition hover:bg-[rgba(245,158,11,0.08)] disabled:opacity-50"
        disabled={busy}
        onClick={() => void prepare()}
        type="button"
      >
        {busy ? "Đang kiểm tra" : "Chuẩn bị LIVE"}
      </button>
      <button
        className="min-h-8 rounded-md bg-[var(--color-loss)] px-3 text-xs font-bold text-[var(--text-primary)] transition hover:bg-[var(--color-loss)] disabled:opacity-50"
        disabled={busy || !status?.live_readiness?.allowed}
        onClick={() => void goLive()}
        title={
          !status?.live_readiness?.allowed
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

/* ──────────────────────────── STATUS LINE ──────────────────────────── */

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
    status ? `Chế độ ${status.mode}` : "Đang tải trạng thái",
    `Thời gian thực ${viWsState(wsState)}`,
    exchange
      ? `Sàn ${viExchangeFreshness(exchange.freshness)} · ${viExchangeConnection(exchange.connection)}`
      : "Sàn giao dịch -",
    lastLiveAt > 0
      ? `Cập nhật ${new Date(lastLiveAt).toLocaleTimeString("vi-VN")}`
      : null,
  ].filter(Boolean);
  return (
    <p
      className="max-w-3xl text-xs font-semibold text-[var(--text-muted)] truncate"
      title={parts.join(" • ")}
    >
      {isRefreshing ? "Đang đồng bộ dữ liệu..." : parts.join(" • ")}
    </p>
  );
}

/* ──────────────────────────── LOADING GRID ──────────────────────────── */

function LoadingGrid() {
  return (
    <div
      className="mb-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4"
      aria-label="Đang tải dữ liệu"
    >
      {Array.from({ length: 8 }).map((_, index) => (
        <div
          className="h-24 skeleton p-4"
          key={index}
        >
          <div className="h-3 w-24 skeleton" />
          <div className="mt-4 h-7 w-32 skeleton" />
        </div>
      ))}
    </div>
  );
}

/* ──────────────────────────── DATA PANEL ──────────────────────────── */

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
    <section className="glass-card overflow-hidden">
      <div className="panel-header flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <h3>{title}</h3>
        {controls}
      </div>
      <div className="overflow-x-auto p-3 md:p-4">{children}</div>
    </section>
  );
}

/* ──────────────────────────── TABLE ──────────────────────────── */

function Table({ columns, rows }: { columns: string[]; rows: (React.ReactNode | string)[][] }) {
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
            className="glass-card p-3"
            key={`${row[0]}-${rowIndex}`}
          >
            <div className="mb-2 flex items-center justify-between gap-3">
              <strong className="truncate text-base text-[var(--text-primary)] num-display">
                {row[0]}
              </strong>
              {row[1] ? (
                <span className="shrink-0 badge bg-[rgba(255,255,255,0.04)] text-[var(--text-secondary)]">
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
                  <span className="font-bold text-[var(--text-muted)]">
                    {columns[index + 2]}
                  </span>
                  <span className="max-w-[58%] break-words text-right font-semibold text-[var(--text-primary)]">
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
          <tr className="border-b border-[var(--border-default)] text-left text-xs uppercase text-[var(--text-muted)]">
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
              className={`border-b border-white/[0.04] transition hover:bg-white/[0.025] last:border-0 ${rowIndex % 2 === 0 ? "" : "table-row-even"}`}
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

/* ──────────────────────────── TABLE CONTROLS ──────────────────────────── */

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
      <label className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm">
        <ListFilter size={14} className="text-[var(--text-muted)]" />
        <span className="text-[var(--text-muted)]">Sắp xếp</span>
        <select
          className="bg-transparent text-[var(--text-primary)] outline-none"
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

/* ──────────────────────────── SEARCH BOX ──────────────────────────── */

function SearchBox({
  query,
  setQuery,
}: {
  query: string;
  setQuery: (value: string) => void;
}) {
  return (
    <label className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm">
      <Search size={14} className="text-[var(--text-muted)]" />
      <input
        className="w-36 bg-transparent text-[var(--text-primary)] outline-none placeholder:text-[var(--text-muted)]"
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Tìm mã"
        value={query}
      />
    </label>
  );
}

/* ──────────────────────────── METRIC ──────────────────────────── */

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
      ? "text-[var(--color-profit)]"
      : tone === "bad"
        ? "text-[var(--color-loss)]"
        : "text-[var(--text-primary)]";
  return (
    <section className="glass-card p-3 transition-all hover:border-[var(--border-strong)]">
      <p className="text-[11px] font-bold uppercase text-[var(--text-muted)] tracking-wider">{label}</p>
      <strong
        className={`mt-2 block break-words text-xl leading-tight num-display ${color}`}
      >
        {value}
      </strong>
    </section>
  );
}

/* ──────────────────────────── NUMBER FIELD ──────────────────────────── */

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
    <label className="grid gap-2 text-sm font-bold text-[var(--text-secondary)]">
      {label}
      <input
        className="terminal-input"
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

/* ──────────────────────────── STATUS CHIP ──────────────────────────── */

function StatusChip({
  label,
  value,
  danger = false,
  safe = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
  safe?: boolean;
}) {
  const dotClass = danger
    ? "status-dot-offline"
    : safe
      ? "status-dot-live"
      : "status-dot-stale";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-default)] bg-[rgba(255,255,255,0.03)] px-2.5 py-1.5 text-xs font-semibold">
      <div className={`status-dot ${dotClass}`} />
      <span className="text-[var(--text-muted)]">{label}</span>
      <span className={danger ? "text-[var(--color-loss)]" : safe ? "text-[var(--color-profit)]" : "text-[var(--text-secondary)]"}>{value}</span>
    </span>
  );
}

/* ──────────────────────────── EQUITY CHART ──────────────────────────── */

function EquityChart({ values }: { values: number[] }) {
  if (!values.length) {
    return (
      <div className="grid h-64 place-items-center rounded-lg bg-[rgba(255,255,255,0.03)] text-sm text-[var(--text-muted)]">
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
      className="h-64 w-full rounded-lg bg-[rgba(255,255,255,0.03)]"
      preserveAspectRatio="none"
      viewBox="0 0 100 100"
    >
      <polyline
        fill="none"
        points={points}
        stroke="#06b6d4"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
      {values.length === 1 && (
        <line
          stroke="#06b6d4"
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

/* ──────────────────────────── EMPTY STATE ──────────────────────────── */

function EmptyState({ message, title }: { title: string; message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-white/[0.1] bg-[rgba(255,255,255,0.02)] p-8 text-center">
      <h3 className="font-bold text-[var(--text-secondary)]">{title}</h3>
      <p className="mt-2 text-sm text-[var(--text-muted)]">{message}</p>
    </div>
  );
}

/* ──────────────────────────── UTILITY FUNCTIONS ──────────────────────────── */

function buildEquitySeries(performance: Performance | null) {
  if (!performance) return [];
  const realizedBalance = performance.initial_capital + performance.net_pnl;
  return [
    performance.initial_capital,
    realizedBalance,
    performance.equity,
  ].filter((value) => Number.isFinite(value));
}

function viAction(value: ScannerResult["action"]) {
  if (value === "NO_TRADE") return "Không vào lệnh";
  return value;
}

function normalizeMode(
  value: StatusPayload["mode"] | undefined,
): "DEMO" | "LIVE" {
  return value === "LIVE" ? "LIVE" : "DEMO";
}

/* ── ModeBadge (Phase 15) ── */
function ModeBadge({
  current,
  liveAllowed,
  onDone,
}: {
  current: "DEMO" | "LIVE";
  liveAllowed: boolean;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const badgeClass =
    current === "LIVE"
      ? "mode-badge-live"
      : liveAllowed
        ? "mode-badge-live-not-ready"
        : "mode-badge-demo";
  async function toggle() {
    if (busy) return;
    const next = current === "DEMO" ? "LIVE" : "DEMO";
    if (next === "LIVE" && !liveAllowed) return;
    setBusy(true);
    try {
      const result = await api.mode(next);
      if (result.accepted) onDone();
    } catch {
      /* ignore */
    } finally {
      setBusy(false);
    }
  }
  const canToggle = current === "DEMO" || liveAllowed;
  return (
    <button
      className={`mode-badge ${badgeClass} ${canToggle ? "cursor-pointer hover:opacity-80" : ""}`}
      disabled={busy || !canToggle}
      onClick={toggle}
      title={current === "LIVE" ? "Chuyển sang DEMO" : liveAllowed ? "Chuyển sang LIVE" : "Chế độ LIVE chưa sẵn sàng"}
      type="button"
    >
      <span className="flex items-center gap-1.5">
        <span className={`status-dot ${current === "LIVE" ? "status-dot-live" : "status-dot-stale"}`} />
        {current}
      </span>
    </button>
  );
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

function viExchangeFreshness(value: ExchangeSnapshot["freshness"] | undefined) {
  if (value === "LIVE") return "Dữ liệu mới";
  if (value === "STALE") return "Dữ liệu cũ";
  return "Mất kết nối";
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
    NO_SIGNAL: "Chưa có tín hiệu",
    NO_ACCEPTED_SIGNAL: "Tín hiệu bị chặn",
    WAITING_POSITION: "Đang giữ lệnh",
    SUBMITTING: "Đang vào lệnh",
    ORDER_SUBMITTED: "Đã vào lệnh",
    ORDER_ERROR: "Lỗi lệnh",
    ERROR: "Lỗi worker",
  };
  return labels[value ?? ""] ?? "Đang chờ";
}

function viWsState(value: WsState) {
  if (value === "LIVE") return "Trực tiếp";
  if (value === "STALE") return "Chậm";
  return "Mất kết nối";
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
