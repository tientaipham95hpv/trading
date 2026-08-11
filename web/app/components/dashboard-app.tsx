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
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, wsUrl } from "./api";
import type { BotSettings, ExchangeSnapshot, LogItem, Market, Performance, Position, ScannerResult, StatusPayload, Trade, WsState } from "./types";

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
      const [nextStatus, nextMarkets, nextScanner, nextPositions, nextTrades, nextPerformance, nextExchange, nextSettings, nextLogs] =
        await Promise.all([
          api.status(),
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
      setError(reason instanceof Error ? reason.message : "Không tải được dữ liệu");
    } finally {
      setHasLoaded(true);
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    const firstLoad = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => {
      window.clearTimeout(firstLoad);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnect: number | undefined;
    let staleTimer: number | undefined;

    function connect() {
      socket = new WebSocket(wsUrl("system"));
      socket.onopen = () => {
        setWsState("LIVE");
        lastLiveAtRef.current = Date.now();
        setLastLiveAt(lastLiveAtRef.current);
      };
      socket.onmessage = (event) => {
        setWsState("LIVE");
        lastLiveAtRef.current = Date.now();
        setLastLiveAt(lastLiveAtRef.current);
        const payload = JSON.parse(event.data) as { data?: StatusPayload };
        if (payload.data) {
          setStatus(payload.data);
        }
      };
      socket.onerror = () => setWsState("STALE");
      socket.onclose = () => {
        setWsState("OFFLINE");
        reconnect = window.setTimeout(connect, 2500);
      };
      staleTimer = window.setInterval(() => {
        setWsState(Date.now() - lastLiveAtRef.current > 7000 ? "STALE" : "LIVE");
      }, 3000);
    }

    connect();
    return () => {
      if (reconnect) window.clearTimeout(reconnect);
      if (staleTimer) window.clearInterval(staleTimer);
      socket?.close();
    };
  }, []);

  const currentPage = nav.find((item) => item.key === page) ?? nav[0];

  return (
    <main className="grid min-h-screen grid-cols-1 bg-[#eef3f6] text-slate-900 lg:grid-cols-[264px_1fr]">
      <aside className="border-r border-slate-200 bg-[#0f1720] text-white lg:sticky lg:top-0 lg:h-screen">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4 lg:block lg:py-5">
          <div>
            <p className="text-xs font-bold uppercase text-cyan-300">USD-M Futures</p>
            <h1 className="mt-1 text-xl font-bold">Trading Cockpit</h1>
          </div>
          <StatusBadge value={wsState} />
        </div>
        <nav className="grid max-h-[42vh] grid-cols-2 gap-1 overflow-y-auto p-3 lg:max-h-none lg:grid-cols-1">
          {nav.map((item) => {
            const Icon = item.icon;
            const active = item.href === pathname || (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link
                className={`flex min-h-10 items-center gap-3 rounded-md px-3 text-sm font-semibold transition ${
                  active ? "bg-cyan-400 text-slate-950 shadow-sm" : "text-slate-300 hover:bg-white/10 hover:text-white"
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
        <header className="sticky top-0 z-10 flex flex-col gap-4 border-b border-slate-200 bg-white/95 px-4 py-4 shadow-sm backdrop-blur md:px-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase text-slate-500">Control Surface</p>
            <h2 className="text-2xl font-bold">{currentPage.label}</h2>
            <StatusLine exchange={exchange ?? status?.exchange ?? null} isRefreshing={isRefreshing} lastLiveAt={lastLiveAt} status={status} wsState={wsState} />
          </div>
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <ModeSelector current={status?.mode ?? "PAPER"} liveAllowed={status?.live_readiness.allowed ?? false} onDone={refresh} />
            <BotControls onDone={refresh} />
            <Pill label="Chế độ" value={status?.mode ?? "PAPER"} tone="neutral" />
            <Pill label="LIVE" value={status?.live_enabled ? "ON" : "OFF"} tone={status?.live_enabled ? "danger" : "safe"} />
            <Pill label="Bot" value={viBotState(status?.bot_state)} tone={status?.safe_mode ? "danger" : "neutral"} />
            <Pill label="Exchange" value={viExchangeConnection(exchange?.connection ?? status?.exchange.connection)} tone={(exchange?.connection ?? status?.exchange.connection) === "CONNECTED" ? "safe" : "danger"} />
            <button className="inline-flex min-h-9 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-bold text-slate-800 transition hover:bg-slate-50 disabled:opacity-60" disabled={isRefreshing} onClick={() => void refresh()} type="button">
              <RefreshCw className={isRefreshing ? "animate-spin" : ""} size={16} />
              {isRefreshing ? "Đang tải" : "Làm mới"}
            </button>
          </div>
        </header>

        <div className="p-4 md:p-5">
          {error && <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
          {!hasLoaded && <LoadingGrid />}
          {page === "dashboard" && <Dashboard exchange={exchange ?? status?.exchange ?? null} onDone={refresh} performance={performance} positions={positions} status={status} />}
          {page === "markets" && <Markets markets={markets} />}
          {page === "scanner" && <Scanner scanner={scanner} />}
          {page === "positions" && <Positions markets={markets} positions={positions} />}
          {page === "trades" && <Trades trades={trades} />}
          {page === "strategies" && <Strategies scanner={scanner} />}
          {page === "analytics" && <Analytics performance={performance} trades={trades} />}
          {page === "risk" && <Risk onDone={refresh} status={status} />}
          {page === "logs" && <Logs logs={logs} />}
          {page === "settings" && settings && <SettingsPage onSaved={refresh} settings={settings} />}
        </div>
      </section>
    </main>
  );
}

function Dashboard({ exchange, onDone, performance, positions, status }: { exchange: ExchangeSnapshot | null; onDone: () => Promise<void>; performance: Performance | null; positions: Position[]; status: StatusPayload | null }) {
  const equitySeries = useMemo(() => buildEquitySeries(performance), [performance]);
  return (
    <div className="grid gap-4">
      <ActivitySummary exchange={exchange} status={status} />
      <CommandCenter exchange={exchange} onDone={onDone} status={status} />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Vốn hiện tại" value={money(performance?.equity)} />
        <Metric label="PNL hôm nay" value={money(performance?.realized_pnl)} tone={(performance?.realized_pnl ?? 0) >= 0 ? "good" : "bad"} />
        <Metric label="Tổng PNL" value={money(performance?.realized_pnl)} tone={(performance?.realized_pnl ?? 0) >= 0 ? "good" : "bad"} />
        <Metric label="Tỷ lệ thắng" value={percent((performance?.win_rate ?? 0) * 100)} />
        <Metric label="Sụt giảm vốn" value={percent(drawdown(performance))} tone="bad" />
        <Metric label="Hệ số lợi nhuận" value={profitFactor(performance)} />
        <Metric label="Sharpe" value={number(performance?.sharpe)} />
        <Metric label="Sortino" value={number(performance?.sortino)} />
        <Metric label="Expectancy" value={money(performance?.expectancy)} />
        <Metric label="Vị thế mở" value={String(performance?.open_positions ?? positions.length)} />
        <Metric label="Rủi ro đã dùng" value={percent(((performance?.open_positions ?? 0) / (status?.risk.max_open_positions ?? 4)) * 100)} />
        <Metric label="Balance DEMO" value={money(exchange?.balance.balance)} />
        <Metric label="Available DEMO" value={money(exchange?.balance.available)} />
        <Metric label="Margin DEMO" value={money(exchange?.balance.margin_balance)} />
        <Metric label="Kết nối exchange" value={viExchangeConnection(exchange?.connection)} tone={exchange?.connection === "CONNECTED" ? "good" : "bad"} />
      </div>
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-bold">Biểu đồ vốn</h3>
          <span className="text-sm text-slate-500">Số dư {money(performance?.balance)}</span>
        </div>
        <EquityChart values={equitySeries} />
      </section>
      <div className="grid gap-4 xl:grid-cols-2">
        <ExchangeOrders orders={exchange?.orders ?? []} />
        <ExchangePositions positions={exchange?.positions ?? []} />
      </div>
      <LiveReadinessPanel onDone={onDone} status={status} />
    </div>
  );
}

function CommandCenter({ exchange, onDone, status }: { exchange: ExchangeSnapshot | null; onDone: () => Promise<void>; status: StatusPayload | null }) {
  return (
    <section className="grid gap-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm xl:grid-cols-[1.2fr_1fr]">
      <div className="grid gap-3 sm:grid-cols-3">
        <ModeCard label="Trading mode" value={status?.mode ?? "PAPER"} tone={status?.mode === "LIVE" ? "danger" : status?.mode === "DEMO" ? "warning" : "safe"} />
        <ModeCard label="Exchange" value={viExchangeConnection(exchange?.connection)} tone={exchange?.connection === "CONNECTED" ? "safe" : "danger"} />
        <ModeCard label="LIVE gate" value={status?.live_readiness.allowed ? "READY" : "LOCKED"} tone={status?.live_readiness.allowed ? "warning" : "safe"} />
      </div>
      <div className="flex flex-col justify-center gap-3 xl:items-end">
        <p className="max-w-xl text-sm font-semibold text-slate-600 xl:text-right">
          {status?.mode === "LIVE" ? "LIVE đang dùng tiền thật. Kiểm tra lệnh và rủi ro trước mọi thao tác." : "Đang ở môi trường an toàn. Có thể kiểm tra kết nối, signal và lệnh demo tại đây."}
        </p>
        <div className="flex flex-wrap items-center justify-start gap-2 xl:justify-end">
        <ModeSelector current={status?.mode ?? "PAPER"} liveAllowed={status?.live_readiness.allowed ?? false} onDone={onDone} />
        <BotControls onDone={onDone} />
        </div>
      </div>
    </section>
  );
}

function ModeCard({ label, tone, value }: { label: string; value: string; tone: "safe" | "warning" | "danger" }) {
  const iconColor = tone === "safe" ? "text-emerald-700" : tone === "warning" ? "text-amber-700" : "text-red-700";
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4 transition hover:border-slate-300">
      <div className={`mb-3 flex h-9 w-9 items-center justify-center rounded-md bg-white ${iconColor}`}>
        {tone === "danger" ? <ShieldAlert size={18} /> : tone === "warning" ? <Radio size={18} /> : <LockKeyhole size={18} />}
      </div>
      <p className="text-xs font-bold uppercase text-slate-500">{label}</p>
      <strong className="mt-1 block break-words text-2xl leading-tight">{value}</strong>
    </div>
  );
}

function ActivitySummary({ exchange, status }: { exchange: ExchangeSnapshot | null; status: StatusPayload | null }) {
  const isRunning = status?.bot_state === "RUNNING";
  const connected = exchange?.connection === "CONNECTED";
  const hasOrders = Boolean(exchange?.orders.length);
  const hasPositions = Boolean(exchange?.positions.length);
  const title = isRunning && connected ? "Bot đang online" : status?.safe_mode ? "Bot đang SAFE_MODE" : "Bot chưa sẵn sàng";
  const detail = hasOrders || hasPositions
    ? `Đang có ${exchange?.orders.length ?? 0} order và ${exchange?.positions.length ?? 0} vị thế trên ${exchange?.mode ?? status?.mode ?? "mode hiện tại"}.`
    : "Backend đang chạy và kết nối exchange, nhưng hiện chưa có lệnh/vị thế mở.";
  const tone = status?.safe_mode || status?.emergency_stop ? "border-red-200 bg-red-50 text-red-800" : isRunning && connected ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800";

  return (
    <section className={`rounded-lg border px-4 py-3 shadow-sm ${tone}`}>
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="font-bold">{title}</h3>
          <p className="mt-1 text-sm font-semibold opacity-80">{detail}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill label="Mode" value={status?.mode ?? "-"} tone={status?.mode === "LIVE" ? "danger" : "safe"} />
          <Pill label="Bot" value={viBotState(status?.bot_state)} tone={isRunning ? "safe" : "neutral"} />
          <Pill label="Exchange" value={viExchangeConnection(exchange?.connection)} tone={connected ? "safe" : "danger"} />
        </div>
      </div>
    </section>
  );
}

function LiveReadinessPanel({ onDone, status }: { onDone: () => Promise<void>; status: StatusPayload | null }) {
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
        <Pill label="Runtime LIVE" value={readiness?.live_enabled ? "ON" : "OFF"} tone={readiness?.live_enabled ? "danger" : "safe"} />
        <button
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-bold text-slate-800 hover:bg-slate-50 disabled:opacity-50"
          disabled={readiness?.allowed !== true && readiness?.live_enabled !== true}
          onClick={() => void toggleLive(!(readiness?.live_enabled ?? false))}
          type="button"
        >
          <Zap size={16} />
          {readiness?.live_enabled ? "Tắt LIVE gate" : "Bật LIVE gate"}
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {checks.map(([label, ok]) => (
          <Pill key={String(label)} label={String(label)} value={ok ? "PASS" : "BLOCK"} tone={ok ? "safe" : "danger"} />
        ))}
      </div>
      {readiness?.blockers.length ? <p className="mt-3 text-sm font-semibold text-red-700">{readiness.blockers.join(" / ")}</p> : null}
    </DataPanel>
  );
}

function ExchangeOrders({ orders }: { orders: ExchangeSnapshot["orders"] }) {
  return (
    <DataPanel title="Order DEMO trên Binance">
      <Table
        columns={["Mã", "Hướng", "Loại", "Trạng thái", "Giá", "SL/TP", "Khối lượng", "Reduce-only"]}
        rows={orders.map((order) => [
          order.symbol,
          viSide(order.side),
          viOrderType(order.order_type),
          order.status,
          money(order.price),
          money(order.stop_price),
          number(order.quantity),
          order.reduce_only ? "Có" : "Không",
        ])}
      />
    </DataPanel>
  );
}

function ExchangePositions({ positions }: { positions: ExchangeSnapshot["positions"] }) {
  return (
    <DataPanel title="Vị thế DEMO trên Binance">
      <Table
        columns={["Mã", "Hướng", "Khối lượng", "Giá vào", "Mark", "PNL", "Giá thanh lý", "Đòn bẩy"]}
        rows={positions.map((position) => [
          position.symbol,
          viSide(position.side),
          number(position.quantity),
          money(position.entry_price),
          money(position.mark_price),
          money(position.unrealized_pnl),
          money(position.liquidation_price),
          position.leverage ? `${position.leverage}x` : "-",
        ])}
      />
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
      controls={<TableControls query={query} setQuery={setQuery} sort={sort} setSort={setSort} sortOptions={["quote_volume", "price_change_percent", "spread_bps", "funding_rate"]} />}
      title="Thị trường"
    >
      <Table
        columns={["Mã", "Giá", "24h%", "Khối lượng", "Chênh lệch", "Phí funding", "Tuổi niêm yết"]}
        rows={rows.map((item) => [
          item.symbol,
          money(item.last_price),
          signedPercent(item.price_change_percent),
          compact(item.quote_volume),
          `${item.spread_bps.toFixed(2)} bps`,
          percent(item.funding_rate * 100),
          item.listing_age_days ? `${Math.floor(item.listing_age_days)} ngày` : "-",
        ])}
      />
    </DataPanel>
  );
}

function Scanner({ scanner }: { scanner: ScannerResult[] }) {
  const [query, setQuery] = useState("");
  const [signal, setSignal] = useState("ALL");
  const rows = scanner.filter((item) => item.symbol.includes(query.toUpperCase()) && (signal === "ALL" || item.action === signal));
  return (
    <DataPanel
      controls={
        <div className="flex flex-wrap gap-2">
          <SearchBox query={query} setQuery={setQuery} />
          <select className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm" onChange={(event) => setSignal(event.target.value)} value={signal}>
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
        columns={["Mã", "Giá", "24h%", "Khối lượng", "Trạng thái thị trường", "Điểm Long", "Điểm Short", "Tín hiệu", "ATR", "Phí funding"]}
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

function Positions({ markets, positions }: { markets: Market[]; positions: Position[] }) {
  const marks = new Map(markets.map((item) => [item.symbol, item.last_price]));
  return (
    <DataPanel title="Vị thế">
      <Table
        columns={["Mã", "Hướng", "Giá vào", "Giá hiện tại", "Khối lượng", "SL", "TP", "PNL", "ROE"]}
        rows={positions.map((item) => {
          const current = marks.get(item.symbol) ?? item.entry_price;
          const pnl = item.side === "LONG" ? (current - item.entry_price) * item.remaining_quantity : (item.entry_price - current) * item.remaining_quantity;
          const cost = item.entry_price * item.remaining_quantity;
          return [item.symbol, viSide(item.side), money(item.entry_price), money(current), number(item.remaining_quantity), money(item.stop_loss), item.take_profits.map(money).join(" / "), money(pnl), percent((pnl / cost) * 100)];
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
    const okResult = result === "ALL" || (result === "WIN" ? trade.net_pnl > 0 : trade.net_pnl <= 0);
    return okQuery && okSide && okResult;
  });
  return (
    <DataPanel
      controls={
        <div className="flex flex-wrap gap-2">
          <SearchBox query={query} setQuery={setQuery} />
          <select className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm" onChange={(event) => setSide(event.target.value)} value={side}>
            <option value="ALL">Tất cả</option>
            <option>LONG</option>
            <option>SHORT</option>
          </select>
          <select className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm" onChange={(event) => setResult(event.target.value)} value={result}>
            <option value="ALL">Tất cả</option>
            <option value="WIN">Thắng</option>
            <option value="LOSS">Thua</option>
          </select>
        </div>
      }
      title="Lệnh đã chốt"
    >
      <Table columns={["Mã", "Hướng", "Giá vào", "Giá thoát", "Khối lượng", "PNL gộp", "Phí", "Trượt giá", "PNL ròng", "Kết quả"]} rows={rows.map((trade) => [trade.symbol, viSide(trade.side), money(trade.entry_price), money(trade.exit_price), number(trade.quantity), money(trade.gross_pnl), money(trade.fee), money(trade.slippage), money(trade.net_pnl), trade.net_pnl > 0 ? "Thắng" : "Thua"])} />
    </DataPanel>
  );
}

function Strategies({ scanner }: { scanner: ScannerResult[] }) {
  const strategies = ["Trend Pullback", "Breakout"];
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {strategies.map((strategy) => {
        const active = scanner.filter((item) => item.strategy === strategy);
        return (
          <section className="rounded-lg border border-slate-200 bg-white p-4" key={strategy}>
            <h3 className="font-bold">{strategy}</h3>
            <p className="mt-2 text-sm text-slate-500">{active.length ? `${active.length} tín hiệu đang đủ điều kiện.` : "Chưa có tín hiệu đủ điểm từ bộ quét."}</p>
          </section>
        );
      })}
    </div>
  );
}

function Analytics({ performance, trades }: { performance: Performance | null; trades: Trade[] }) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Metric label="PNL ròng" value={money(performance?.realized_pnl)} />
      <Metric label="Phí" value={money(performance?.fees_paid)} />
      <Metric label="Phí funding" value={money(performance?.funding_paid)} />
      <Metric label="Profit Factor" value={profitFactor(performance)} />
      <Metric label="DD" value={money(performance?.max_drawdown)} />
      <Metric label="Sharpe" value={number(performance?.sharpe)} />
      <Metric label="Sortino" value={number(performance?.sortino)} />
      <Metric label="Expectancy" value={money(performance?.expectancy)} />
      <Metric label="Winrate" value={percent((performance?.win_rate ?? 0) * 100)} />
      <section className="rounded-lg border border-slate-200 bg-white p-4 md:col-span-3">
        <h3 className="mb-3 font-bold">Phân bổ kết quả lệnh</h3>
        <Table columns={["Kết quả", "Số lượng"]} rows={[["Thắng", String(trades.filter((item) => item.net_pnl > 0).length)], ["Thua", String(trades.filter((item) => item.net_pnl <= 0).length)]]} />
      </section>
    </div>
  );
}

function Risk({ onDone, status }: { onDone: () => Promise<void>; status: StatusPayload | null }) {
  const risk = status?.risk;
  const readiness = status?.live_readiness;
  async function setCheck(key: keyof StatusPayload["live_readiness"], value: boolean) {
    await api.liveConfig({ [key]: value });
    await onDone();
  }
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 md:grid-cols-3">
        <Metric label="Rủi ro mỗi lệnh" value={percent((risk?.risk_per_trade ?? 0) * 100)} />
        <Metric label="Rủi ro tối đa mỗi lệnh" value={percent((risk?.max_risk_per_trade ?? 0) * 100)} />
        <Metric label="Lỗ tối đa mỗi ngày" value={percent((risk?.max_daily_loss ?? 0) * 100)} />
        <Metric label="Weekly DD" value={percent((risk?.max_weekly_drawdown ?? 0) * 100)} />
        <Metric label="Vị thế tối đa" value={String(risk?.max_open_positions ?? "-")} />
        <Metric label="Đòn bẩy tối đa" value={`${risk?.max_leverage ?? "-"}x`} />
        <Metric label="Exposure tối đa" value={percent((risk?.max_portfolio_exposure ?? 0) * 100)} />
        <Metric label="Correlation tối đa" value={String(risk?.max_correlated_positions ?? "-")} />
        <Metric label="Loss streak" value={String(risk?.max_loss_streak ?? "-")} />
        <Metric label="RR tối thiểu" value={number(risk?.minimum_risk_reward)} />
      </div>
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
            <label className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-bold" key={key}>
              <span>{label}</span>
              <input checked={Boolean(readiness?.[key])} onChange={(event) => void setCheck(key, event.target.checked)} type="checkbox" />
            </label>
          ))}
        </div>
        {readiness?.blockers.length ? <p className="mt-3 text-sm font-semibold text-red-700">{readiness.blockers.join(" / ")}</p> : null}
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

function SettingsPage({ settings, onSaved }: { settings: BotSettings; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  async function save() {
    setSaving(true);
    await api.updateSettings(draft);
    await onSaved();
    setSaving(false);
  }
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <NumberField label="Khối lượng tối thiểu" value={draft.min_quote_volume} onChange={(value) => setDraft({ ...draft, min_quote_volume: value })} />
        <NumberField label="Spread tối đa bps" value={draft.max_spread_bps} onChange={(value) => setDraft({ ...draft, max_spread_bps: value })} />
        <NumberField label="Tuổi niêm yết tối thiểu" value={draft.min_listing_age_days} onChange={(value) => setDraft({ ...draft, min_listing_age_days: value })} />
        <NumberField label="Điểm vào lệnh tối thiểu" value={draft.min_score_to_trade} onChange={(value) => setDraft({ ...draft, min_score_to_trade: value })} />
        <NumberField label="Phí taker" value={draft.taker_fee_rate} step={0.0001} onChange={(value) => setDraft({ ...draft, taker_fee_rate: value })} />
        <NumberField label="Trượt giá bps" value={draft.slippage_bps} onChange={(value) => setDraft({ ...draft, slippage_bps: value })} />
        <NumberField label="Rủi ro mỗi lệnh" value={draft.risk_per_trade} step={0.0005} onChange={(value) => setDraft({ ...draft, risk_per_trade: value })} />
        <NumberField label="Rủi ro tối đa mỗi lệnh" value={draft.max_risk_per_trade} step={0.001} onChange={(value) => setDraft({ ...draft, max_risk_per_trade: value })} />
        <NumberField label="Daily loss" value={draft.max_daily_loss} step={0.001} onChange={(value) => setDraft({ ...draft, max_daily_loss: value })} />
        <NumberField label="Weekly DD" value={draft.max_weekly_drawdown} step={0.001} onChange={(value) => setDraft({ ...draft, max_weekly_drawdown: value })} />
        <NumberField label="Đòn bẩy tối đa" value={draft.max_leverage} onChange={(value) => setDraft({ ...draft, max_leverage: value })} />
        <NumberField label="Vị thế tối đa" value={draft.max_open_positions} onChange={(value) => setDraft({ ...draft, max_open_positions: value })} />
      </div>
      <div className="mt-4 flex justify-end">
        <button className="rounded-md bg-slate-950 px-4 py-2 text-sm font-bold text-white disabled:opacity-60" disabled={saving} onClick={() => void save()} type="button">
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
  async function control(action: "pause-new-trades" | "cancel-orders" | "close-all") {
    if (action !== "pause-new-trades" && !window.confirm(action === "close-all" ? "Đóng toàn bộ vị thế đang mở?" : "Hủy toàn bộ order đang chờ?")) return;
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
      <div className="flex rounded-md border border-slate-300 bg-white p-1 shadow-sm">
        <ActionIcon busy={busy === "start"} disabled={disabled} label="Chạy bot" onClick={() => void act("start")} tone="safe">
          <Play size={16} />
        </ActionIcon>
        <ActionIcon busy={busy === "pause"} disabled={disabled} label="Tạm dừng bot" onClick={() => void act("pause")} tone="warning">
          <Pause size={16} />
        </ActionIcon>
        <ActionIcon busy={busy === "stop"} disabled={disabled} label="Dừng bot" onClick={() => void act("stop")} tone="danger">
          <Square size={16} />
        </ActionIcon>
      </div>
      <div className="flex rounded-md border border-red-200 bg-white p-1 shadow-sm">
        <ActionIcon busy={busy === "pause-new-trades"} disabled={disabled} label="Tạm dừng lệnh mới" onClick={() => void control("pause-new-trades")} tone="warning">
          <ShieldX size={16} />
        </ActionIcon>
        <ActionIcon busy={busy === "cancel-orders"} disabled={disabled} label="Hủy order" onClick={() => void control("cancel-orders")} tone="orange">
          <XCircle size={16} />
        </ActionIcon>
        <ActionIcon busy={busy === "close-all"} disabled={disabled} label="Đóng toàn bộ vị thế" onClick={() => void control("close-all")} tone="danger">
          <Trash2 size={16} />
        </ActionIcon>
        <ActionIcon busy={busy === "emergency"} disabled={disabled} label="Emergency Stop" onClick={() => void emergency()} tone="solidDanger">
          <ShieldAlert size={16} />
        </ActionIcon>
      </div>
    </div>
  );
}

function ActionIcon({ busy, children, disabled, label, onClick, tone }: { busy: boolean; children: React.ReactNode; disabled: boolean; label: string; onClick: () => void; tone: "safe" | "warning" | "orange" | "danger" | "solidDanger" }) {
  const toneClass: Record<"safe" | "warning" | "orange" | "danger" | "solidDanger", string> = {
    safe: "text-emerald-700 hover:bg-emerald-50",
    warning: "text-amber-700 hover:bg-amber-50",
    orange: "text-orange-700 hover:bg-orange-50",
    danger: "text-red-700 hover:bg-red-50",
    solidDanger: "bg-red-700 text-white hover:bg-red-800",
  };
  return (
    <button aria-label={label} className={`grid h-9 w-9 place-items-center rounded transition disabled:cursor-not-allowed disabled:opacity-50 ${toneClass[tone]}`} disabled={disabled} onClick={onClick} title={label} type="button">
      {busy ? <RefreshCw className="animate-spin" size={16} /> : children}
    </button>
  );
}

function StatusLine({ exchange, isRefreshing, lastLiveAt, status, wsState }: { exchange: ExchangeSnapshot | null; isRefreshing: boolean; lastLiveAt: number; status: StatusPayload | null; wsState: WsState }) {
  const parts = [
    status ? `Mode ${status.mode}` : "Đang tải trạng thái",
    `Realtime ${wsState}`,
    exchange ? `Exchange ${viExchangeConnection(exchange.connection)}` : "Exchange -",
    lastLiveAt > 0 ? `Cập nhật ${new Date(lastLiveAt).toLocaleTimeString("vi-VN")}` : null,
  ].filter(Boolean);
  return (
    <p className="mt-1 max-w-3xl truncate text-sm font-semibold text-slate-500" title={parts.join(" • ")}>
      {isRefreshing ? "Đang đồng bộ dữ liệu..." : parts.join(" • ")}
    </p>
  );
}

function LoadingGrid() {
  return (
    <div className="mb-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4" aria-label="Đang tải dữ liệu">
      {Array.from({ length: 4 }).map((_, index) => (
        <div className="h-24 animate-pulse rounded-lg border border-slate-200 bg-white p-4 shadow-sm" key={index}>
          <div className="h-3 w-24 rounded bg-slate-200" />
          <div className="mt-4 h-7 w-32 rounded bg-slate-200" />
        </div>
      ))}
    </div>
  );
}

function ModeSelector({ current, liveAllowed, onDone }: { current: "PAPER" | "DEMO" | "LIVE"; liveAllowed: boolean; onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  async function change(mode: "PAPER" | "DEMO" | "LIVE") {
    if (mode === current) return;
    setBusy(true);
    try {
      await api.mode(mode);
      await onDone();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="flex rounded-md border border-slate-300 bg-white p-1 shadow-sm">
      {(["PAPER", "DEMO", "LIVE"] as const).map((mode) => (
        <button
          className={`min-h-8 rounded px-3 py-1 text-xs font-black transition ${current === mode ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-100 disabled:text-slate-300 disabled:hover:bg-transparent"}`}
          disabled={busy || (mode === "LIVE" && !liveAllowed)}
          key={mode}
          onClick={() => void change(mode)}
          title={mode === "LIVE" && !liveAllowed ? "LIVE đang bị khóa bởi preflight" : `Đổi sang ${mode}`}
          type="button"
        >
          {mode}
        </button>
      ))}
    </div>
  );
}

function DataPanel({ children, controls, title }: { children: React.ReactNode; controls?: React.ReactNode; title: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-3 border-b border-slate-200 p-4 xl:flex-row xl:items-center xl:justify-between">
        <h3 className="text-base font-bold">{title}</h3>
        {controls}
      </div>
      <div className="overflow-x-auto p-4">{children}</div>
    </section>
  );
}

function Table({ columns, rows }: { columns: string[]; rows: string[][] }) {
  if (!rows.length) {
    return <EmptyState message="Không có dòng nào ở trạng thái hiện tại." title="Trống" />;
  }
  return (
    <table className="w-full min-w-[880px] border-collapse text-sm">
      <thead>
        <tr className="border-b border-slate-200 bg-white text-left text-xs uppercase text-slate-500">
          {columns.map((column) => (
            <th className="px-3 py-3 font-bold" key={column}>{column}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr className="border-b border-slate-100 transition hover:bg-slate-50 last:border-0" key={`${row[0]}-${rowIndex}`}>
            {row.map((cell, cellIndex) => (
              <td className="whitespace-nowrap px-3 py-3" key={`${cell}-${cellIndex}`}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TableControls<T extends string>({ query, setQuery, sort, setSort, sortOptions }: { query: string; setQuery: (value: string) => void; sort: T; setSort: (value: T) => void; sortOptions: readonly T[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      <SearchBox query={query} setQuery={setQuery} />
      <label className="inline-flex min-h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus-within:border-cyan-500">
        <ListFilter size={16} />
        <span className="text-slate-500">Sắp xếp</span>
        <select className="bg-transparent outline-none" onChange={(event) => setSort(event.target.value as T)} value={sort}>
          {sortOptions.map((item) => <option key={item} value={item}>{viSortLabel(item)}</option>)}
        </select>
      </label>
    </div>
  );
}

function SearchBox({ query, setQuery }: { query: string; setQuery: (value: string) => void }) {
  return (
    <label className="inline-flex min-h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus-within:border-cyan-500">
      <Search size={16} />
      <input className="w-36 bg-transparent outline-none" onChange={(event) => setQuery(event.target.value)} placeholder="Tìm mã" value={query} />
    </label>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  const color = tone === "good" ? "text-emerald-700" : tone === "bad" ? "text-red-700" : "text-slate-950";
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-300">
      <p className="text-xs font-bold uppercase text-slate-500">{label}</p>
      <strong className={`mt-2 block break-words text-2xl leading-tight ${color}`}>{value}</strong>
    </section>
  );
}

function NumberField({ label, onChange, step = 1, value }: { label: string; onChange: (value: number) => void; step?: number; value: number }) {
  return (
    <label className="grid gap-2 text-sm font-bold text-slate-600">
      {label}
      <input className="rounded-md border border-slate-300 px-3 py-2 font-normal text-slate-950 shadow-sm outline-none focus:border-cyan-500" onChange={(event) => onChange(Number(event.target.value))} step={step} type="number" value={value} />
    </label>
  );
}

function StatusBadge({ value }: { value: WsState }) {
  const className = value === "LIVE" ? "bg-emerald-100 text-emerald-800" : value === "STALE" ? "bg-amber-100 text-amber-800" : "bg-red-100 text-red-800";
  return <span className={`rounded-full px-3 py-1 text-xs font-black ${className}`}>{value}</span>;
}

function Pill({ label, tone, value }: { label: string; value: string; tone: "neutral" | "safe" | "danger" }) {
  const color = tone === "safe" ? "text-emerald-700" : tone === "danger" ? "text-red-700" : "text-slate-700";
  return <span className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-bold"><span className="text-slate-400">{label}</span> <span className={color}>{value}</span></span>;
}

function EquityChart({ values }: { values: number[] }) {
  if (!values.length) {
    return <div className="grid h-64 place-items-center rounded-md bg-slate-50 text-sm text-slate-500">Chưa có lịch sử vốn từ backend.</div>;
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
    <svg className="h-64 w-full rounded-md bg-slate-50" preserveAspectRatio="none" viewBox="0 0 100 100">
      <polyline fill="none" points={points} stroke="#0f766e" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      {values.length === 1 && <line stroke="#0f766e" strokeWidth="2" vectorEffect="non-scaling-stroke" x1="0" x2="100" y1="50" y2="50" />}
    </svg>
  );
}

function EmptyState({ message, title }: { title: string; message: string }) {
  return <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center"><h3 className="font-bold">{title}</h3><p className="mt-2 text-sm text-slate-500">{message}</p></div>;
}

function buildEquitySeries(performance: Performance | null) {
  return performance ? [performance.equity] : [];
}

function drawdown(performance: Performance | null) {
  if (!performance || performance.balance <= 0) return 0;
  return Math.max(0, ((performance.balance - performance.equity) / performance.balance) * 100);
}

function profitFactor(performance: Performance | null) {
  if (!performance || performance.realized_pnl <= 0 || performance.fees_paid <= 0) return "-";
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
  return value === "LONG" ? "Long" : "Short";
}

function viExchangeConnection(value: ExchangeSnapshot["connection"] | undefined) {
  if (value === "CONNECTED") return "Đã kết nối";
  if (value === "STALE") return "Chậm";
  if (value === "SAFE_MODE") return "SAFE_MODE";
  return "Chưa kết nối";
}

function viOrderType(value: string) {
  const labels: Record<string, string> = {
    MARKET: "Market",
    LIMIT: "Limit",
    STOP_MARKET: "Stop market",
    TAKE_PROFIT_MARKET: "Take profit",
    TRAILING_STOP_MARKET: "Trailing stop",
  };
  return labels[value] ?? value;
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
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
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
