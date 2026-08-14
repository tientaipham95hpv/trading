import SwiftUI
import UIKit

public struct TradingControlApp: App {
    public init() {}

    public var body: some Scene {
        WindowGroup {
            TradingControlView()
        }
    }
}

public struct TradingControlView: View {
    @StateObject private var model = TradingViewModel()

    public init() {}

    public var body: some View {
        TabView {
            HomeView(model: model)
                .tabItem { Label("Trang chủ", systemImage: "gauge.with.dots.needle.67percent") }
            MarketsView(model: model)
                .tabItem { Label("Thị trường", systemImage: "chart.line.uptrend.xyaxis") }
            ScannerView(model: model)
                .tabItem { Label("Bộ quét", systemImage: "dot.radiowaves.left.and.right") }
            PositionsView(model: model)
                .tabItem { Label("Vị thế", systemImage: "arrow.up.arrow.down") }
            TradesView(model: model)
                .tabItem { Label("Lịch sử", systemImage: "clock.arrow.circlepath") }
            MoreView(model: model)
                .tabItem { Label("Thêm", systemImage: "ellipsis.circle") }
        }
        .task {
            model.start()
        }
        .preferredColorScheme(.dark)
        .tint(.cyan)
        .alert("Thông báo", isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button("Đóng", role: .cancel) {}
        } message: {
            Text(model.errorMessage ?? "")
        }
    }
}

private struct HomeView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        NavigationStack {
            ZStack {
                LiquidBackground()
                ScrollView {
                    VStack(spacing: 14) {
                        SystemStateBanner(model: model)
                        AccountHero(model: model)
                        ModeControlPanel(model: model)
                        RiskRoomPanel(model: model)
                        OpenExchangePositionsPanel(model: model)
                        SignalHighlights(model: model)
                        SystemHealthPanel(model: model)
                        LatestBacktestPanel(model: model)
                    }
                    .padding()
                }
            }
            .navigationTitle("Trang chủ")
            .toolbarBackground(.hidden, for: .navigationBar)
            .preferredColorScheme(.dark)
            .toolbar { RefreshToolbarItem(model: model) }
        }
    }
}

private struct AccountHero: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        GlassPanel {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("DEMO realtime")
                            .font(.caption.bold())
                            .foregroundStyle(.cyan)
                        Text(money(model.performance?.equity ?? model.exchange?.balance.marginBalance))
                            .font(.system(size: 34, weight: .black, design: .rounded))
                            .minimumScaleFactor(0.65)
                            .lineLimit(1)
                        Text("Available \(money(model.exchange?.balance.available)) / Balance \(money(model.exchange?.balance.balance ?? model.performance?.balance))")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    StatusChip(text: displayMode(model.status?.mode), color: model.status?.mode == "LIVE" ? .red : .cyan)
                }
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                    HeroMetric(title: "Vốn ban đầu", value: money(model.performance?.initialCapital), color: .white)
                    HeroMetric(title: "Vốn hiện tại", value: money(model.performance?.balance), color: .cyan)
                    HeroMetric(title: "Lãi/lỗ ròng", value: money(model.performance?.netPnl), color: (model.performance?.netPnl ?? 0) >= 0 ? .green : .red)
                    HeroMetric(title: "Tăng/giảm", value: signedPercent(model.performance?.returnPercent), color: (model.performance?.returnPercent ?? 0) >= 0 ? .green : .red)
                    HeroMetric(title: "Thắng / Thua", value: "\(model.performance?.winningTrades ?? 0) / \(model.performance?.losingTrades ?? 0)", color: .cyan)
                    HeroMetric(title: "Tỷ lệ thắng", value: percent((model.performance?.winRate ?? 0) * 100), color: .cyan)
                    HeroMetric(title: "Lãi/lỗ đang mở", value: money(model.exchange?.balance.unrealizedPnl ?? model.performance?.unrealizedPnl), color: (model.exchange?.balance.unrealizedPnl ?? model.performance?.unrealizedPnl ?? 0) >= 0 ? .green : .red)
                    HeroMetric(title: "Tổng lệnh", value: "\(model.performance?.totalTrades ?? 0)", color: .white)
                }
            }
        }
    }
}

private struct LatestBacktestPanel: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        if let report = model.latestBacktest {
            GlassPanel {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Backtest gần nhất").font(.headline)
                    Text("\(report.symbol) · \(report.interval) · \(report.candleCount) nến")
                        .font(.caption).foregroundStyle(.secondary)
                    HStack {
                        result(report.baseline)
                        if let candidate = report.candidate { result(candidate) }
                    }
                    Text("Candidate chỉ để so sánh, không tự áp dụng vào DEMO/LIVE.")
                        .font(.caption2).foregroundStyle(.orange)
                }
            }
        }
    }

    private func result(_ value: BacktestStrategyReport) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(value.config.name).font(.subheadline.bold())
            Text("PNL \(money(value.metrics.pnl))")
            Text("PF \(String(format: "%.2f", value.metrics.profitFactor)) · DD \(String(format: "%.2f%%", value.maxDrawdownPercent))")
            Text("Avg R \(String(format: "%.2f", value.averageR)) · OOS \(value.metrics.outOfSampleTrades)")
        }.font(.caption).frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct HeroMetric: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            Text(value)
                .font(.headline.weight(.black))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.62)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct RiskRoomPanel: View {
    @ObservedObject var model: TradingViewModel

    private var openPositions: Int { model.exchange?.positions.count ?? model.performance?.openPositions ?? model.positions.count }
    private var maxPositions: Int { max(model.status?.risk.maxOpenPositions ?? 1, 1) }
    private var marginUsage: Double {
        guard let balance = model.exchange?.balance.marginBalance, balance > 0 else { return 0 }
        return max(0, (balance - (model.exchange?.balance.available ?? 0)) / balance)
    }

    var body: some View {
        GlassPanel {
            VStack(alignment: .leading, spacing: 12) {
                Text("Room rủi ro")
                    .font(.headline)
                RiskProgressRow(title: "Vị thế mở", value: Double(openPositions) / Double(maxPositions), trailing: "\(openPositions)/\(maxPositions)")
                RiskProgressRow(title: "Margin đang dùng", value: marginUsage, trailing: percent(marginUsage * 100))
                RiskProgressRow(title: "Tổng risk cho phép", value: model.status?.risk.maxTotalOpenRisk ?? 0, trailing: percent((model.status?.risk.maxTotalOpenRisk ?? 0) * 100))
                HStack {
                    InfoPill("Risk/lệnh \(percent((model.status?.risk.riskPerTrade ?? 0) * 100))")
                    InfoPill("RR \(number(model.status?.risk.minimumRiskReward))")
                }
            }
        }
    }
}

private struct RiskProgressRow: View {
    let title: String
    let value: Double
    let trailing: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title).font(.footnote.weight(.semibold)).foregroundStyle(.secondary)
                Spacer()
                Text(trailing).font(.footnote.bold())
            }
            ProgressView(value: min(max(value, 0), 1))
                .tint(value >= 0.9 ? .red : .cyan)
        }
    }
}

private struct OpenExchangePositionsPanel: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        GlassPanel {
            VStack(alignment: .leading, spacing: 12) {
                Text("Vị thế đang mở")
                    .font(.headline)
                if model.exchange?.positions.isEmpty != false {
                    Text("Chưa có vị thế DEMO từ Binance.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(model.exchange?.positions ?? []) { position in
                        ExchangePositionRow(position: position)
                    }
                }
            }
        }
    }
}

private struct ExchangePositionRow: View {
    let position: ExchangePosition

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(position.symbol).font(.headline)
                StatusChip(text: viSide(position.side), color: position.side == "LONG" ? .green : .red)
                Spacer()
                Text(money(position.unrealizedPnl))
                    .font(.headline.weight(.black))
                    .foregroundStyle(position.unrealizedPnl >= 0 ? .green : .red)
            }
            Text("Entry \(money(position.entryPrice)) / Mark \(money(position.markPrice)) / Thanh lý \(money(position.liquidationPrice)) / \(position.leverage ?? 0)x")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(10)
        .background(.white.opacity(0.05), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct SignalHighlights: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        GlassPanel {
            VStack(alignment: .leading, spacing: 12) {
                Text("Tín hiệu nổi bật")
                    .font(.headline)
                let opportunities = model.scanner.filter { $0.action != "NO_TRADE" }.prefix(5)
                if opportunities.isEmpty {
                    Text("Chưa có tín hiệu đủ điểm ở bộ lọc hiện tại.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(Array(opportunities)) { item in
                        ScannerRow(item: item)
                    }
                }
            }
        }
    }
}

private struct SystemHealthPanel: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        GlassPanel {
            VStack(alignment: .leading, spacing: 10) {
                Text("Sức khỏe hệ thống")
                    .font(.headline)
                InfoRow(label: "Realtime", value: model.realtimeState.rawValue)
                InfoRow(label: "Exchange", value: viExchangeConnection(model.exchange?.connection))
                InfoRow(label: "Lần cập nhật", value: model.lastRealtimeAt.map(shortTime) ?? "-")
                InfoRow(label: "Auto loop", value: viAutoStatus(model.status?.autoTrader?.lastStatus))
                InfoRow(label: "Lý do gần nhất", value: model.status?.autoTrader?.lastReason ?? "-")
                InfoRow(label: "SAFE_MODE", value: model.status?.safeMode == true ? "Đang bật" : "Không")
                InfoRow(label: "LIVE readiness", value: model.status?.liveReadiness.allowed == true ? "PASS" : "BLOCK")
            }
        }
    }
}

private struct ModeControlPanel: View {
    @ObservedObject var model: TradingViewModel
    private var liveAllowed: Bool { model.status?.liveReadiness.allowed == true }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Trading Cockpit", systemImage: "bolt.shield")
                    .font(.headline)
                Spacer()
                Text(model.status?.liveReadiness.allowed == true ? "LIVE READY" : "LIVE LOCKED")
                    .font(.caption.bold())
                    .foregroundStyle(model.status?.liveReadiness.allowed == true ? .orange : .green)
            }
            Picker("Chế độ", selection: Binding(
                get: { displayMode(model.status?.mode) },
                set: { mode in
                    guard mode != "LIVE" || liveAllowed else { return }
                    Task { await model.setMode(mode) }
                }
            )) {
                Text("DEMO").tag("DEMO")
                Text("LIVE").tag("LIVE")
            }
            .pickerStyle(.segmented)
            if !liveAllowed {
                Label("LIVE đang khóa bởi preflight", systemImage: "lock.shield")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 10) {
                Button {
                    Task { await model.prepareLive() }
                } label: {
                    Label("Chuẩn bị LIVE", systemImage: "checkmark.shield")
                }
                .buttonStyle(.bordered)
                .tint(.orange)
                .disabled(model.isRefreshing)

                Button(role: .destructive) {
                    Task { await model.setMode("LIVE") }
                } label: {
                    Label("LIVE", systemImage: "bolt.fill")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!liveAllowed || model.isRefreshing)
            }
            HStack(spacing: 10) {
                Button {
                    Task { await model.controlBot(.start) }
                } label: {
                    Label("Chạy", systemImage: "play.fill")
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
                .disabled(model.isRefreshing)

                Button {
                    Task { await model.controlBot(.pause) }
                } label: {
                    Label("Pause", systemImage: "pause.fill")
                }
                .buttonStyle(.bordered)
                .disabled(model.isRefreshing)

                Button(role: .destructive) {
                    Task { await model.emergencyStop() }
                } label: {
                    Label("Emergency", systemImage: "hand.raised.fill")
                }
                .buttonStyle(.bordered)
                .disabled(model.isRefreshing)
            }
            .font(.subheadline.bold())

            if model.status?.botState == "SAFE_MODE" || model.status?.safeMode == true {
                Button {
                    Task { await model.resetSafeMode() }
                } label: {
                    Label("Reset SAFE_MODE", systemImage: "arrow.clockwise.shield")
                }
                .buttonStyle(.borderedProminent)
                .tint(.orange)
                .disabled(model.isRefreshing)
            }
        }
        .padding()
        .liquidGlass()
    }
}

private struct SystemStateBanner: View {
    @ObservedObject var model: TradingViewModel

    private var isHealthy: Bool {
        model.status?.botState == "RUNNING" && model.exchange?.connection == "CONNECTED" && model.status?.safeMode != true
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: isHealthy ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(isHealthy ? .green : .orange)
                .font(.title3)
            VStack(alignment: .leading, spacing: 4) {
                Text(isHealthy ? "Bot đang online" : "Cần kiểm tra trạng thái")
                    .font(.headline)
                Text(summary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
            Spacer()
            if model.isRefreshing {
                ProgressView()
            }
        }
        .padding()
        .liquidGlass()
    }

    private var summary: String {
        let orders = model.exchange?.orders.count ?? 0
        let positions = model.exchange?.positions.count ?? 0
        if orders > 0 || positions > 0 {
            return "Có \(orders) order và \(positions) vị thế trên \(model.status?.mode ?? "mode hiện tại")."
        }
        return model.status?.autoTrader?.lastReason ?? "Backend chạy, exchange \(viExchangeConnection(model.exchange?.connection)), hiện chưa có lệnh/vị thế mở."
    }
}

private struct LiquidBackground: View {
    var body: some View {
        LinearGradient(
            colors: [
                Color(red: 0.03, green: 0.06, blue: 0.10),
                Color(red: 0.04, green: 0.11, blue: 0.17),
                Color(red: 0.02, green: 0.04, blue: 0.08)
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
        .ignoresSafeArea()
    }
}

private struct GlassPanel<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            content
        }
        .padding()
        .liquidGlass()
    }
}

private struct LiquidGlassModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(.white.opacity(0.16), lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.24), radius: 18, x: 0, y: 10)
    }
}

private extension View {
    func liquidGlass() -> some View {
        modifier(LiquidGlassModifier())
    }

    func tradingGlassList() -> some View {
        scrollContentBackground(.hidden)
            .background(LiquidBackground())
            .toolbarBackground(.hidden, for: .navigationBar)
            .preferredColorScheme(.dark)
    }

    func glassListRow() -> some View {
        listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
    }
}

private struct StatusChip: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.caption.bold())
            .foregroundStyle(color)
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .background(color.opacity(0.14), in: Capsule())
    }
}

private struct InfoPill: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.caption.bold())
            .foregroundStyle(.secondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.white.opacity(0.06), in: Capsule())
    }
}

private struct MarketsView: View {
    @ObservedObject var model: TradingViewModel
    @State private var query = ""
    @State private var sort: MarketSort = .volume

    private var rows: [ThiTruong] {
        model.markets
            .filter { query.isEmpty || $0.symbol.localizedCaseInsensitiveContains(query) }
            .sorted { sort.value($0) > sort.value($1) }
    }

    var body: some View {
        NavigationStack {
            List(rows) { item in
                NavigationLink {
                    CoinChartView(symbol: item.symbol, symbols: rows.map(\.symbol))
                } label: {
                    MarketRowCard(item: item)
                }
                .glassListRow()
            }
            .navigationTitle("Thị trường")
            .tradingGlassList()
            .searchable(text: $query, prompt: "Tìm mã")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Picker("Sắp xếp", selection: $sort) {
                        ForEach(MarketSort.allCases) { item in
                            Text(item.title).tag(item)
                        }
                    }
                }
                ToolbarItem(placement: .topBarTrailing) { RefreshButtonView(model: model) }
            }
            .overlay { if rows.isEmpty { EmptyContent("Chưa có dữ liệu thị trường thật từ backend.") } }
        }
    }
}

private struct MarketRowCard: View {
    let item: ThiTruong

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(item.symbol).font(.headline)
                Spacer()
                Text(money(item.lastPrice)).font(.headline)
            }
            HStack {
                Text("24h \(signedPercent(item.priceChangePercent))")
                Spacer()
                Text("Khối lượng \(compact(item.quoteVolume))")
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
            HStack {
                Text("Chênh lệch \(number(item.spreadBps)) bps")
                Spacer()
                Text("Funding \(percent(item.fundingRate * 100))")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding()
        .liquidGlass()
    }
}

private struct CoinChartView: View {
    let symbol: String
    let symbols: [String]
    @State private var candles: [NenGia] = []
    @State private var interval = "15m"
    @State private var selectedSymbol: String
    @State private var lastUpdated: Date?
    @State private var error: String?

    init(symbol: String, symbols: [String] = []) {
        self.symbol = symbol
        self.symbols = symbols.isEmpty ? [symbol] : symbols
        _selectedSymbol = State(initialValue: symbol)
    }

    var body: some View {
        ZStack {
            LiquidBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    GlassPanel {
                        HStack {
                            VStack(alignment: .leading, spacing: 5) {
                                Menu {
                                    ForEach(symbols, id: \.self) { item in
                                        Button(item) { selectedSymbol = item }
                                    }
                                } label: {
                                    Label(selectedSymbol, systemImage: "chevron.down.circle.fill")
                                        .font(.title.bold())
                                }
                                Text("Realtime 5 giây • \(interval)")
                                    .font(.caption.bold())
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Picker("Khung", selection: $interval) {
                                Text("1m").tag("1m")
                                Text("5m").tag("5m")
                                Text("15m").tag("15m")
                                Text("1h").tag("1h")
                                Text("4h").tag("4h")
                            }
                            .pickerStyle(.segmented)
                            .frame(maxWidth: 280)
                        }
                    }
                    GlassPanel {
                        InteractivePriceChart(candles: candles)
                            .frame(height: 300)
                        HStack {
                            InfoPill("Nến \(candles.count)")
                            InfoPill("Cập nhật \(lastUpdated.map(shortTime) ?? "-")")
                            if let last = candles.last {
                                InfoPill("Close \(money(last.close))")
                            }
                        }
                    }
                    if let error {
                        GlassPanel {
                            Label(error, systemImage: "exclamationmark.triangle.fill")
                                .foregroundStyle(.orange)
                        }
                    }
                }
                .padding()
            }
        }
        .navigationTitle(selectedSymbol)
        .toolbarBackground(.hidden, for: .navigationBar)
        .task(id: "\(selectedSymbol)-\(interval)") { await realtimeLoad() }
    }

    private func realtimeLoad() async {
        while !Task.isCancelled {
            await load()
            try? await Task.sleep(nanoseconds: 5_000_000_000)
        }
    }

    private func load() async {
        do {
            let response = try await TradingAPI.shared.klines(symbol: selectedSymbol, interval: interval, limit: 220)
            candles = response.items
            lastUpdated = Date()
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

private struct InteractivePriceChart: View {
    let candles: [NenGia]

    @State private var visibleCount = 80
    @State private var endOffset = 0
    @State private var selectedIndex: Int?
    @State private var dragStartOffset: Int?
    @State private var magnificationStartCount: Int?

    private let verticalPadding: CGFloat = 12
    private let timeScaleHeight: CGFloat = 24
    private let priceScaleWidth: CGFloat = 72

    private var window: ArraySlice<NenGia> {
        let end = max(candles.count - endOffset, 0)
        let start = max(end - min(visibleCount, end), 0)
        return candles[start..<end]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let candle = selectedCandle {
                HStack(spacing: 10) {
                    Text(chartDate(candle.openTime)).foregroundStyle(.secondary)
                    Text("O \(chartPrice(candle.open))")
                    Text("H \(chartPrice(candle.high))").foregroundStyle(.green)
                    Text("L \(chartPrice(candle.low))").foregroundStyle(.red)
                    Text("C \(chartPrice(candle.close))")
                }
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .lineLimit(1)
                .minimumScaleFactor(0.65)
            } else if let first = window.first, let last = window.last {
                HStack {
                    Text("\(window.count) nến")
                    Spacer()
                    Text(signedPercent((last.close - first.open) / first.open * 100))
                        .foregroundStyle(last.close >= first.open ? .green : .red)
                }
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            }

            Canvas { context, size in
                drawChart(context: context, size: size)
            }
            .contentShape(Rectangle())
            .gesture(dragGesture.simultaneously(with: magnificationGesture))
            .onTapGesture { selectedIndex = nil }
            .accessibilityLabel("Biểu đồ nến tương tác, kéo để xem giá hoặc dịch thời gian, chụm để thu phóng")
        }
        .padding(6)
        .background(.white.opacity(0.04), in: RoundedRectangle(cornerRadius: 8))
        .onChange(of: candles.count) { _, _ in clampState() }
    }

    private var selectedCandle: NenGia? {
        let items = Array(window)
        guard let selectedIndex, items.indices.contains(selectedIndex) else { return nil }
        return items[selectedIndex]
    }

    private var dragGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                let plotWidth = max(value.startLocation.x > 0 ? UIScreen.main.bounds.width - 120 : 1, 1)
                if dragStartOffset == nil { dragStartOffset = endOffset }
                if abs(value.translation.width) > 14 {
                    let candleWidth = max(plotWidth / CGFloat(max(visibleCount, 1)), 1)
                    let shift = Int((value.translation.width / candleWidth).rounded())
                    endOffset = min(max((dragStartOffset ?? 0) + shift, 0), max(candles.count - 10, 0))
                    selectedIndex = nil
                } else {
                    let count = max(Array(window).count, 1)
                    let width = max(UIScreen.main.bounds.width - priceScaleWidth - 44, 1)
                    selectedIndex = min(max(Int(value.location.x / width * CGFloat(count)), 0), count - 1)
                }
            }
            .onEnded { _ in dragStartOffset = nil }
    }

    private var magnificationGesture: some Gesture {
        MagnifyGesture()
            .onChanged { value in
                if magnificationStartCount == nil { magnificationStartCount = visibleCount }
                visibleCount = min(max(Int(CGFloat(magnificationStartCount ?? 80) / value.magnification), 20), min(max(candles.count, 20), 180))
                clampState()
            }
            .onEnded { _ in magnificationStartCount = nil }
    }

    private func clampState() {
        visibleCount = min(max(visibleCount, 20), min(max(candles.count, 20), 180))
        endOffset = min(max(endOffset, 0), max(candles.count - 10, 0))
        selectedIndex = nil
    }

    private func drawChart(context: GraphicsContext, size: CGSize) {
        let items = Array(window)
        guard !items.isEmpty, let minLow = items.map(\.low).min(), let maxHigh = items.map(\.high).max() else { return }
        let plotWidth = max(size.width - priceScaleWidth, 1)
        let drawingHeight = max(size.height - verticalPadding * 2 - timeScaleHeight, 1)
        let range = max(maxHigh - minLow, max(abs(maxHigh) * 0.0001, 0.000_000_01))
        let slot = plotWidth / CGFloat(items.count)
        let bodyWidth = max(min(slot * 0.68, 9), 1)
        func y(_ price: Double) -> CGFloat { verticalPadding + CGFloat((maxHigh - price) / range) * drawingHeight }

        for line in 0...4 {
            let fraction = Double(line) / 4
            let lineY = verticalPadding + drawingHeight * CGFloat(fraction)
            var path = Path(); path.move(to: CGPoint(x: 0, y: lineY)); path.addLine(to: CGPoint(x: plotWidth, y: lineY))
            context.stroke(path, with: .color(.white.opacity(0.08)), lineWidth: 0.5)
            context.draw(Text(chartPrice(maxHigh - range * fraction)).font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary), at: CGPoint(x: plotWidth + 5, y: lineY), anchor: .leading)
        }

        for (index, candle) in items.enumerated() {
            let x = slot * (CGFloat(index) + 0.5)
            let color: Color = candle.close >= candle.open ? .green : .red
            var wick = Path(); wick.move(to: CGPoint(x: x, y: y(candle.high))); wick.addLine(to: CGPoint(x: x, y: y(candle.low)))
            context.stroke(wick, with: .color(color), lineWidth: 1)
            let openY = y(candle.open), closeY = y(candle.close)
            context.fill(Path(CGRect(x: x - bodyWidth / 2, y: min(openY, closeY), width: bodyWidth, height: max(abs(closeY - openY), 1))), with: .color(color))
        }

        for index in Set([0, items.count / 2, items.count - 1]) {
            let x = slot * (CGFloat(index) + 0.5)
            context.draw(Text(chartTime(items[index].openTime)).font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary), at: CGPoint(x: x, y: size.height - 4), anchor: index == 0 ? .bottomLeading : index == items.count - 1 ? .bottomTrailing : .bottom)
        }

        if let last = items.last {
            let lineY = y(last.close), color: Color = last.close >= last.open ? .green : .red
            var path = Path(); path.move(to: CGPoint(x: 0, y: lineY)); path.addLine(to: CGPoint(x: plotWidth, y: lineY))
            context.stroke(path, with: .color(color.opacity(0.75)), style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
            context.fill(Path(roundedRect: CGRect(x: plotWidth + 2, y: lineY - 10, width: priceScaleWidth - 4, height: 20), cornerRadius: 4), with: .color(color))
            context.draw(Text(chartPrice(last.close)).font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundStyle(.white), at: CGPoint(x: plotWidth + priceScaleWidth / 2, y: lineY))
        }

        if let selectedIndex, items.indices.contains(selectedIndex) {
            let x = slot * (CGFloat(selectedIndex) + 0.5)
            var crosshair = Path(); crosshair.move(to: CGPoint(x: x, y: 0)); crosshair.addLine(to: CGPoint(x: x, y: drawingHeight + verticalPadding))
            context.stroke(crosshair, with: .color(.cyan.opacity(0.8)), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
        }
    }
}

private struct ScannerView: View {
    @ObservedObject var model: TradingViewModel
    @State private var query = ""
    @State private var signal = "ALL"

    private var rows: [TinHieuQuet] {
        model.scanner.filter { item in
            (query.isEmpty || item.symbol.localizedCaseInsensitiveContains(query)) &&
            (signal == "ALL" || item.action == signal)
        }
    }

    var body: some View {
        NavigationStack {
            List(rows) { item in
                NavigationLink {
                    CoinChartView(symbol: item.symbol)
                } label: {
                    ScannerRow(item: item)
                        .padding()
                        .liquidGlass()
                }
                .glassListRow()
            }
            .navigationTitle("Bộ quét")
            .tradingGlassList()
            .searchable(text: $query, prompt: "Tìm mã")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Picker("Tín hiệu", selection: $signal) {
                        Text("Tất cả").tag("ALL")
                        Text("Long").tag("LONG")
                        Text("Short").tag("SHORT")
                        Text("Không vào lệnh").tag("NO_TRADE")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) { RefreshButtonView(model: model) }
            }
            .overlay { if rows.isEmpty { EmptyContent("Chưa có tín hiệu realtime từ backend.") } }
        }
    }
}

private struct PositionsView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        NavigationStack {
            List(model.positions) { item in
                NavigationLink {
                    PositionDetailView(position: item, currentPrice: model.markets.first(where: { $0.symbol == item.symbol })?.lastPrice)
                } label: {
                    PositionRowCard(position: item)
                }
                .glassListRow()
            }
            .navigationTitle("Vị thế")
            .tradingGlassList()
            .toolbar { RefreshToolbarItem(model: model) }
            .overlay { if model.positions.isEmpty { EmptyContent("Chưa có vị thế đang mở.") } }
        }
    }
}

private struct PositionRowCard: View {
    let position: ViThe

    private var mark: Double? { position.markPrice }
    private var pnl: Double { position.unrealizedPnl ?? 0 }
    private var pnlPercent: Double? {
        guard position.entryPrice > 0, position.remainingQuantity > 0 else { return nil }
        let notional = position.entryPrice * position.remainingQuantity
        return notional > 0 ? pnl / notional * 100 : nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(position.symbol).font(.headline)
                StatusChip(text: viSide(position.side), color: position.side == "LONG" ? .green : .red)
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text(money(pnl))
                        .font(.headline.weight(.black))
                        .foregroundStyle(pnl >= 0 ? .green : .red)
                    Text(percent(pnlPercent))
                        .font(.caption.bold())
                        .foregroundStyle(.secondary)
                }
            }
            HStack {
                Text("Entry \(money(position.entryPrice))")
                Spacer()
                Text("Mark \(money(mark))")
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
            HStack {
                Text("SL \(money(position.stopLoss))")
                Spacer()
                Text("\(position.leverage ?? 0)x \(position.marginType ?? "")")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding()
        .liquidGlass()
    }
}

private struct PositionDetailView: View {
    let position: ViThe
    let currentPrice: Double?

    var body: some View {
        List {
            Section("Tổng quan") {
                NavigationLink {
                    CoinChartView(symbol: position.symbol)
                } label: {
                    Label("Mở biểu đồ realtime", systemImage: "chart.line.uptrend.xyaxis")
                }
                InfoRow(label: "Mã", value: position.symbol)
                InfoRow(label: "Hướng", value: viSide(position.side))
                InfoRow(label: "Trạng thái", value: position.status)
                InfoRow(label: "Giá vào", value: money(position.entryPrice))
                InfoRow(label: "Giá hiện tại", value: money(position.markPrice ?? currentPrice))
                InfoRow(label: "Khối lượng còn lại", value: number(position.remainingQuantity))
                InfoRow(label: "Đòn bẩy", value: "\(position.leverage ?? 0)x")
                InfoRow(label: "Thanh lý", value: money(position.liquidationPrice))
            }
            Section("Quản trị rủi ro") {
                InfoRow(label: "Stop loss", value: money(position.stopLoss))
                InfoRow(label: "Take profit", value: position.takeProfits.map(money).joined(separator: " / "))
                InfoRow(label: "Break-even", value: position.breakEvenActive ? "Đang bật" : "Tắt")
                InfoRow(label: "Trailing stop", value: position.trailingStopActive ? "Đang bật" : "Tắt")
            }
            Section("PNL") {
                InfoRow(label: "PNL đang mở", value: money(position.unrealizedPnl))
                InfoRow(label: "PNL đã chốt", value: money(position.realizedPnl))
                InfoRow(label: "Phí đã trả", value: money(position.feesPaid))
                InfoRow(label: "Funding đã trả", value: money(position.fundingPaid))
            }
        }
        .navigationTitle(position.symbol)
        .tradingGlassList()
    }
}

private struct TradesView: View {
    @ObservedObject var model: TradingViewModel
    @State private var query = ""
    @State private var side = "ALL"
    @State private var result = "ALL"

    private var rows: [LenhDaChot] {
        model.trades.filter { trade in
            let okQuery = query.isEmpty || trade.symbol.localizedCaseInsensitiveContains(query)
            let okSide = side == "ALL" || trade.side == side
            let okResult = result == "ALL" || (result == "WIN" ? trade.netPnl > 0 : trade.netPnl <= 0)
            return okQuery && okSide && okResult
        }
    }

    var body: some View {
        NavigationStack {
            List(rows) { trade in
                NavigationLink {
                    TradeDetailView(trade: trade)
                } label: {
                    TradeRowCard(trade: trade)
                }
                .glassListRow()
            }
            .navigationTitle("Lịch sử lệnh")
            .tradingGlassList()
            .searchable(text: $query, prompt: "Tìm mã")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Picker("Hướng", selection: $side) {
                        Text("Tất cả").tag("ALL")
                        Text("Long").tag("LONG")
                        Text("Short").tag("SHORT")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Picker("Kết quả", selection: $result) {
                        Text("Tất cả").tag("ALL")
                        Text("Thắng").tag("WIN")
                        Text("Thua").tag("LOSS")
                    }
                }
            }
            .overlay { if rows.isEmpty { EmptyContent("Chưa có lịch sử lệnh.") } }
        }
    }
}

private struct TradeRowCard: View {
    let trade: LenhDaChot

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(trade.symbol).font(.headline)
                Spacer()
                Text(trade.netPnl > 0 ? "Thắng" : "Thua")
                    .font(.subheadline.bold())
                    .foregroundStyle(trade.netPnl > 0 ? .green : .red)
            }
            HStack {
                Text("\(viSide(trade.side)) \(number(trade.quantity))")
                Spacer()
                Text("Ròng \(money(trade.netPnl))")
                    .foregroundStyle(trade.netPnl >= 0 ? .green : .red)
            }
            .font(.subheadline)
            HStack {
                Text("Vào \(money(trade.entryPrice))")
                Spacer()
                Text("Thoát \(money(trade.exitPrice))")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding()
        .liquidGlass()
    }
}

private func viCloseReason(_ reason: String) -> String {
    let value = reason.uppercased()
    if value == "TP" || value.contains("TAKE_PROFIT") { return "Chốt lời theo mục tiêu" }
    if value == "SL" || value.contains("STOP") { return "Chạm Stop Loss" }
    if value == "LIQUIDATION" { return "Thanh lý vị thế" }
    if value == "REALIZED_PNL" { return "Đóng vị thế đã khớp" }
    return reason.isEmpty ? "Đóng vị thế thủ công hoặc theo thị trường" : reason
}

private struct TradeDetailView: View {
    let trade: LenhDaChot

    var body: some View {
        List {
            Section("Tổng quan") {
                InfoRow(label: "Mã", value: trade.symbol)
                InfoRow(label: "Hướng", value: viSide(trade.side))
                InfoRow(label: "Lý do đóng", value: viCloseReason(trade.reason))
                InfoRow(label: "Thời gian", value: trade.createdAt)
            }
            Section("Giá và khối lượng") {
                InfoRow(label: "Giá vào", value: money(trade.entryPrice))
                InfoRow(label: "Giá thoát", value: money(trade.exitPrice))
                InfoRow(label: "Khối lượng", value: number(trade.quantity))
            }
            Section("PNL") {
                InfoRow(label: "Lãi/lỗ gộp", value: money(trade.grossPnl))
                InfoRow(label: "Phí", value: money(trade.fee))
                InfoRow(label: "Trượt giá", value: money(trade.slippage))
                InfoRow(label: "Phí vốn", value: money(trade.funding))
                InfoRow(label: "Lãi/lỗ ròng", value: money(trade.netPnl))
            }
        }
        .navigationTitle(trade.symbol)
        .tradingGlassList()
    }
}

private struct MoreView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        NavigationStack {
            List {
                Section("Chế độ giao dịch") {
                    Picker("Chế độ", selection: Binding(
                        get: { displayMode(model.status?.mode) },
                        set: { mode in Task { await model.setMode(mode) } }
                    )) {
                        Text("DEMO").tag("DEMO")
                        Text("LIVE").tag("LIVE")
                    }
                    .pickerStyle(.segmented)
                    InfoRow(label: "LIVE", value: model.status?.liveEnabled == true ? "Bật" : "Tắt")
                    if let reason = model.status?.safeModeReason {
                        Text(reason).foregroundStyle(.red)
                    }
                }
                Section("Điều khiển bot") {
                    HStack {
                        ForEach(BotAction.allCases) { action in
                            Button(action.title) {
                                Task { await model.controlBot(action) }
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(tint(for: action))
                        }
                    }
                }
                Section("LIVE Controls") {
                    ForEach(TradingControlAction.allCases) { action in
                        Button(action.title) {
                            Task { await model.tradingControl(action) }
                        }
                        .buttonStyle(.bordered)
                    }
                    Button("Emergency Stop", role: .destructive) {
                        Task { await model.emergencyStop() }
                    }
                }
                Section("LIVE readiness") {
                    Button("Chuẩn bị LIVE nhanh") {
                        Task { await model.prepareLive() }
                    }
                    InfoRow(label: "All tests", value: model.status?.liveReadiness.allTestsPass == true ? "PASS" : "BLOCK")
                    InfoRow(label: "Demo stable", value: model.status?.liveReadiness.demoStable == true ? "PASS" : "BLOCK")
                    InfoRow(label: "SL protection", value: model.status?.liveReadiness.slProtectionPass == true ? "PASS" : "BLOCK")
                    InfoRow(label: "Reconnect", value: model.status?.liveReadiness.reconnectPass == true ? "PASS" : "BLOCK")
                    InfoRow(label: "Reconciliation", value: model.status?.liveReadiness.reconciliationPass == true ? "PASS" : "BLOCK")
                    InfoRow(label: "Duplicate order", value: model.status?.liveReadiness.duplicateOrderTestsPass == true ? "PASS" : "BLOCK")
                }
                Section("Xác thực backend") {
                    SecureField("Auth token", text: $model.tokenDraft)
                    Text("Điền Bearer token backend nếu server bật bảo vệ API. Để trống nếu backend hiện cho phép dashboard nội bộ không cần token.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Lưu token vào Keychain") {
                        model.saveToken()
                    }
                    Button("Xóa token") {
                        model.tokenDraft = ""
                        model.saveToken()
                    }
                }
                Section("Cấu hình scanner") {
                    InfoRow(label: "Khối lượng tối thiểu", value: compact(model.settings?.minQuoteVolume))
                    InfoRow(label: "Spread tối đa", value: "\(number(model.settings?.maxSpreadBps)) bps")
                    InfoRow(label: "Tuổi niêm yết tối thiểu", value: "\(model.settings?.minListingAgeDays ?? 0) ngày")
                    InfoRow(label: "Điểm vào lệnh tối thiểu", value: "\(model.settings?.minScoreToTrade ?? 0)")
                    Text("Các giá trị này lấy trực tiếp từ backend production. Thay đổi scanner/risk nên làm trên web hoặc backend để có test trước khi chạy.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("Order DEMO trên Binance") {
                    if model.exchange?.orders.isEmpty != false {
                        EmptyContent("Chưa có order DEMO từ Binance.")
                    } else {
                        ForEach(model.exchange?.orders ?? []) { order in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(order.symbol).font(.headline)
                                    Spacer()
                                    Text(order.status)
                                }
                                Text("\(viSide(order.side)) \(viOrderType(order.orderType)) - \(number(order.quantity))")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                Text("SL/TP \(money(order.stopPrice)) - reduce-only \(order.reduceOnly ? "Có" : "Không")")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Section("Vị thế DEMO trên Binance") {
                    if model.exchange?.positions.isEmpty != false {
                        EmptyContent("Chưa có vị thế DEMO từ Binance.")
                    } else {
                        ForEach(model.exchange?.positions ?? []) { position in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(position.symbol).font(.headline)
                                    Spacer()
                                    Text(viSide(position.side))
                                }
                                Text("Entry \(money(position.entryPrice)) - Mark \(money(position.markPrice))")
                                    .font(.subheadline)
                                Text("PNL \(money(position.unrealizedPnl)) - Thanh lý \(money(position.liquidationPrice)) - \(position.leverage ?? 0)x")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Thêm")
            .tradingGlassList()
            .toolbar { RefreshToolbarItem(model: model) }
        }
    }

    private func tint(for action: BotAction) -> Color {
        switch action {
        case .start: return .green
        case .pause: return .orange
        case .stop: return .red
        }
    }
}

private struct ScannerRow: View {
    let item: TinHieuQuet

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(item.symbol).font(.headline)
                Spacer()
                Text(viAction(item.action))
                    .fontWeight(.semibold)
                    .foregroundStyle(scannerActionColor(item.action))
            }
            HStack {
                Text("Giá \(money(item.price))")
                Spacer()
                Text("24h \(signedPercent(item.priceChangePercent))")
            }
            .font(.subheadline)
            HStack {
                Text("Long \(item.longScore)")
                Text("Short \(item.shortScore)")
                Spacer()
                Text(viRegime(item.regime))
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

private struct MetricTile: View {
    let title: String
    let value: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption)
                .fontWeight(.semibold)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3)
                .fontWeight(.bold)
                .foregroundStyle(tint)
                .lineLimit(2)
                .minimumScaleFactor(0.72)
        }
        .frame(maxWidth: .infinity, minHeight: 86, alignment: .leading)
        .padding()
        .liquidGlass()
    }
}

private struct SectionBlock<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.headline)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .liquidGlass()
    }
}

private struct InfoRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .top) {
            Text(label)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .fontWeight(.semibold)
                .foregroundStyle(.primary)
                .multilineTextAlignment(.trailing)
        }
    }
}

private struct EmptyContent: View {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var body: some View {
        ContentUnavailableView("Trống", systemImage: "tray", description: Text(message))
    }
}

private struct RefreshToolbarItem: ToolbarContent {
    @ObservedObject var model: TradingViewModel

    var body: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            RefreshButtonView(model: model)
        }
    }
}

private struct RefreshButtonView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        Button {
            Task { await model.refreshAll() }
        } label: {
            Label("Làm mới", systemImage: "arrow.clockwise")
        }
    }
}

private enum MarketSort: CaseIterable, Identifiable {
    case volume
    case change
    case spread
    case funding

    var id: String { title }

    var title: String {
        switch self {
        case .volume: return "Khối lượng"
        case .change: return "Biến động 24h"
        case .spread: return "Chênh lệch"
        case .funding: return "Funding"
        }
    }

    func value(_ market: ThiTruong) -> Double {
        switch self {
        case .volume: return market.quoteVolume
        case .change: return market.priceChangePercent
        case .spread: return market.spreadBps
        case .funding: return market.fundingRate
        }
    }
}

private func money(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "-" }
    let magnitude = abs(value)
    if magnitude < 0.000001 {
        return 0.0.formatted(.currency(code: "USD").precision(.fractionLength(2)))
    }
    if magnitude >= 1 {
        return value.formatted(.currency(code: "USD").precision(.fractionLength(2)))
    }
    if magnitude >= 0.01 {
        return value.formatted(.currency(code: "USD").precision(.fractionLength(4)))
    }
    return value.formatted(.currency(code: "USD").precision(.fractionLength(6)))
}

private func chartPrice(_ value: Double) -> String {
    let magnitude = abs(value)
    let digits = magnitude >= 1_000 ? 0 : magnitude >= 1 ? 2 : magnitude >= 0.01 ? 4 : 6
    return value.formatted(
        .number
            .grouping(.automatic)
            .precision(.fractionLength(digits))
    )
}

private func chartTime(_ milliseconds: Int) -> String {
    Date(timeIntervalSince1970: TimeInterval(milliseconds) / 1_000)
        .formatted(date: .omitted, time: .shortened)
}

private func chartDate(_ milliseconds: Int) -> String {
    Date(timeIntervalSince1970: TimeInterval(milliseconds) / 1_000)
        .formatted(.dateTime.day().month().hour().minute())
}

private func compact(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "-" }
    return value.formatted(.number.notation(.compactName).precision(.fractionLength(2)))
}

private func percent(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "-" }
    return "\(number(value))%"
}

private func signedPercent(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "-" }
    return "\(value > 0 ? "+" : "")\(number(value))%"
}

private func number(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "-" }
    return value.formatted(.number.precision(.fractionLength(0...6)))
}

private func shortTime(_ date: Date) -> String {
    date.formatted(date: .omitted, time: .standard)
}

private func drawdown(_ performance: HieuSuat?) -> Double {
    guard let performance, performance.balance > 0 else { return 0 }
    return max(0, (performance.balance - performance.equity) / performance.balance * 100)
}

public func viBotState(_ value: String?) -> String {
    switch value {
    case "RUNNING": return "Đang chạy"
    case "PAUSED": return "Tạm dừng"
    case "STOPPED": return "Đã dừng"
    default: return "Đã dừng"
    }
}

private func displayMode(_ value: String?) -> String {
    value == "LIVE" ? "LIVE" : "DEMO"
}

private func viAutoStatus(_ value: String?) -> String {
    switch value {
    case "SCANNING": return "Đang quét"
    case "ORDER_SUBMITTED": return "Đã vào lệnh"
    case "WAITING_POSITION": return "Đang giữ lệnh"
    case "CLEANED_ORPHAN_ORDERS": return "Đã dọn order"
    case "NO_SIGNAL": return "Chưa có tín hiệu"
    case "BLOCKED": return "Bị chặn"
    case "ORDER_ERROR", "ERROR": return "Lỗi"
    default: return "Đang chờ"
    }
}

private func viAction(_ value: String) -> String {
    switch value {
    case "LONG": return "Long"
    case "SHORT": return "Short"
    case "NO_TRADE": return "Không vào lệnh"
    default: return value
    }
}

private func viRegime(_ value: String) -> String {
    switch value {
    case "TRENDING_UP": return "Xu hướng tăng"
    case "TRENDING_DOWN": return "Xu hướng giảm"
    case "RANGING": return "Đi ngang"
    case "HIGH_VOL": return "Biến động cao"
    case "LOW_VOL": return "Biến động thấp"
    case "PANIC": return "Hoảng loạn"
    default: return value
    }
}

private func viSide(_ value: String) -> String {
    switch value {
    case "LONG": return "Long"
    case "SHORT": return "Short"
    default: return value
    }
}

private func viExchangeConnection(_ value: String?) -> String {
    switch value {
    case "CONNECTED": return "Đã kết nối"
    case "STALE": return "Chậm"
    case "SAFE_MODE": return "SAFE_MODE"
    default: return "Chưa kết nối"
    }
}

private func viOrderType(_ value: String) -> String {
    switch value {
    case "MARKET": return "Market"
    case "LIMIT": return "Limit"
    case "STOP_MARKET": return "Stop market"
    case "TAKE_PROFIT_MARKET": return "Take profit"
    case "TRAILING_STOP_MARKET": return "Trailing stop"
    default: return value
    }
}

private func scannerActionColor(_ value: String) -> Color {
    switch value {
    case "LONG": return .green
    case "SHORT": return .red
    default: return .secondary
    }
}

#Preview {
    TradingControlView()
}
