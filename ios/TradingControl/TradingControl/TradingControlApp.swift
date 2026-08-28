import SwiftUI
import UIKit
import Charts

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
        Group {
            if model.isAuthenticated {
                TabView {
                    HomeView(model: model)
                        .tabItem { Label("Tổng quan", systemImage: "square.grid.2x2.fill") }
                    MarketsView(model: model)
                        .tabItem { Label("Thị trường", systemImage: "chart.xyaxis.line") }
                    ScannerView(model: model)
                        .tabItem { Label("Tín hiệu", systemImage: "waveform.path.ecg") }
                    PositionsView(model: model)
                        .tabItem { Label("Vị thế", systemImage: "arrow.up.arrow.down") }
                    AccountView(model: model)
                        .tabItem { Label("Thêm", systemImage: "ellipsis.circle.fill") }
                }
            } else {
                LoginView(model: model)
            }
        }
        .task {
            await model.restoreSession()
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

private struct AccountView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        MoreView(model: model)
    }
}

private struct LoginView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        ZStack {
            Color(red: 0.035, green: 0.045, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 28) {
                Spacer()
                Image(systemName: "chart.line.uptrend.xyaxis.circle.fill")
                    .font(.system(size: 68))
                    .symbolRenderingMode(.palette)
                    .foregroundStyle(.cyan, .blue.opacity(0.35))
                VStack(spacing: 8) {
                    Text("Trading Bot")
                        .font(.largeTitle.bold())
                    Text("Terminal giao dịch thuật toán")
                        .foregroundStyle(.secondary)
                }
                VStack(spacing: 14) {
                    SecureField("Mật khẩu vận hành", text: $model.passwordDraft)
                        .textContentType(.password)
                        .submitLabel(.go)
                        .onSubmit { Task { await model.login() } }
                        .padding(16)
                        .background(.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 14))
                    Button {
                        Task { await model.login() }
                    } label: {
                        HStack {
                            if model.isAuthenticating { ProgressView().tint(.black) }
                            Text(model.isAuthenticating ? "Đang đăng nhập…" : "Đăng nhập an toàn")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.cyan)
                    .foregroundStyle(.black)
                    .controlSize(.large)
                    .disabled(model.isAuthenticating || model.passwordDraft.isEmpty)
                }
                .frame(maxWidth: 430)
                Text("Thiết bị được ghi nhớ an toàn trong Keychain và mở khóa bằng Face ID. Mật khẩu không được lưu trên thiết bị.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 360)
                Spacer()
            }
            .padding(24)
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
                    if model.isRefreshing && model.performance == nil {
                        SkeletonLoadingView()
                            .padding()
                    } else {
                    VStack(spacing: 14) {
                        SystemStateBanner(model: model)
                        AccountHero(model: model)
                        ModeControlPanel(model: model)
                        RiskRoomPanel(model: model)
                        OpenExchangePositionsPanel(model: model)
                        SignalHighlights(model: model)
                    }
                    .padding()
                    }
                }
            }
            .navigationTitle("Tổng quan")
            .toolbarBackground(.hidden, for: .navigationBar)
            .preferredColorScheme(.dark)
            .toolbar { RefreshToolbarItem(model: model) }
        }
    }
}

private struct SkeletonLoadingView: View {
    var body: some View {
        VStack(spacing: 14) {
            ForEach(0..<4, id: \.self) { index in
                VStack(alignment: .leading, spacing: 12) {
                    RoundedRectangle(cornerRadius: 5).fill(.white.opacity(0.10)).frame(width: index == 0 ? 170 : 120, height: 15)
                    RoundedRectangle(cornerRadius: 8).fill(.white.opacity(0.07)).frame(height: index == 0 ? 92 : 56)
                    HStack {
                        RoundedRectangle(cornerRadius: 6).fill(.white.opacity(0.06)).frame(height: 42)
                        RoundedRectangle(cornerRadius: 6).fill(.white.opacity(0.06)).frame(height: 42)
                    }
                }
                .padding().background(.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 16))
            }
        }
        .redacted(reason: .placeholder)
        .accessibilityLabel("Đang tải dữ liệu giao dịch")
    }
}

private struct OperationsMonitorPanel: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        let activeGateway = model.operations?.mode == "LIVE" ? model.operations?.gateway.live : model.operations?.gateway.demo
        let marketGateway = model.operations?.gateway.market
        let cacheHits = Double((activeGateway?.cache.hits ?? 0) + (marketGateway?.cache.hits ?? 0))
        let cacheMisses = Double((activeGateway?.cache.misses ?? 0) + (marketGateway?.cache.misses ?? 0))
        let cacheHitRate = cacheHits + cacheMisses > 0 ? cacheHits / (cacheHits + cacheMisses) * 100 : 0
        let circuitOpen = activeGateway?.circuitBreaker.state == "open" || marketGateway?.circuitBreaker.state == "open"

        GlassPanel {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Monitoring")
                        .font(.headline)
                    Spacer()
                    StatusChip(text: model.operations?.aiAnalytics.shadowOnly == true ? "AI SHADOW" : "AI LOCK", color: .orange)
                }
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                    HeroMetric(title: "Binance circuit", value: circuitOpen ? "OPEN" : "CLOSED", color: circuitOpen ? .red : .green)
                    HeroMetric(title: "Cache hit", value: cacheHits + cacheMisses > 0 ? percent(cacheHitRate) : "Chưa có", color: .cyan)
                    HeroMetric(title: "Telegram", value: model.operations?.notifications.commandsEnabled == true ? "\(model.operations?.notifications.sent ?? 0) alert" : "Chưa cấu hình", color: model.operations?.notifications.commandsEnabled == true ? .green : .red)
                    HeroMetric(title: "Equity DD", value: percent(model.operations?.equity.maxDrawdownPercent), color: .orange)
                    HeroMetric(title: "AI samples", value: "\(model.operations?.aiAnalytics.training?.sampleSize ?? 0)", color: model.operations?.aiAnalytics.training?.readyForTraining == true ? .green : .orange)
                    HeroMetric(title: "Reconcile", value: model.operations?.reconciliation.safeMode == true ? "SAFE_MODE" : "OK", color: model.operations?.reconciliation.safeMode == true ? .red : .green)
                }
                Text(model.operations?.aiAnalytics.training?.nextStep ?? "AI đang ở shadow mode, chưa được quyền vào lệnh.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
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
                        Text(model.status?.mode == "LIVE" ? "LIVE — Tiền thật" : "DEMO — Giao dịch mô phỏng")
                            .font(.caption.bold())
                            .foregroundStyle(.cyan)
                        Text(money(model.performance?.equity ?? model.exchange?.balance.marginBalance))
                            .font(.system(size: 34, weight: .black, design: .rounded))
                            .minimumScaleFactor(0.65)
                            .lineLimit(1)
                        Text("Khả dụng \(money(model.exchange?.balance.available)) · Số dư \(money(model.exchange?.balance.balance ?? model.performance?.balance))")
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
            Text("PnL \(money(value.metrics.pnl))")
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
                Text("Hạn mức rủi ro")
                    .font(.headline)
                RiskProgressRow(title: "Vị thế mở", value: Double(openPositions) / Double(maxPositions), trailing: "\(openPositions)/\(maxPositions)")
                RiskProgressRow(title: "Margin đang dùng", value: marginUsage, trailing: percent(marginUsage * 100))
                RiskProgressRow(title: "Tổng rủi ro cho phép", value: model.status?.risk.maxTotalOpenRisk ?? 0, trailing: percent((model.status?.risk.maxTotalOpenRisk ?? 0) * 100))
                HStack {
                    InfoPill("Rủi ro/lệnh \(percent((model.status?.risk.riskPerTrade ?? 0) * 100))")
                    InfoPill("R:R \(number(model.status?.risk.minimumRiskReward))")
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
            Text("Vào \(money(position.entryPrice)) · Hiện tại \(money(position.markPrice)) · Thanh lý \(money(position.liquidationPrice)) · \(position.leverage ?? 0)x")
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
                let opportunities = MultiTimeframeSetup.build(from: model.scanner).filter(\.isTradable).prefix(5)
                if opportunities.isEmpty {
                    Text("Chưa có tín hiệu 15m được 4h + 1h xác nhận.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(Array(opportunities)) { setup in
                        ScannerRow(setup: setup)
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
    @State private var confirmLive = false
    @State private var confirmStartLive = false
    @State private var confirmEmergency = false
    private var liveAllowed: Bool { model.status?.liveReadiness.allowed == true }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Điều khiển bot", systemImage: "bolt.shield")
                    .font(.headline)
                Spacer()
                Text(model.status?.liveReadiness.allowed == true ? "LIVE — Sẵn sàng" : "LIVE — Chưa sẵn sàng")
                    .font(.caption.bold())
                    .foregroundStyle(model.status?.liveReadiness.allowed == true ? .orange : .green)
            }
            Picker("Chế độ", selection: Binding(
                get: { displayMode(model.status?.mode) },
                set: { mode in
                    if mode == "LIVE" { if liveAllowed { confirmLive = true } }
                    else { Task { await model.setMode("DEMO") } }
                }
            )) {
                Text("DEMO").tag("DEMO")
                Text("LIVE").tag("LIVE")
            }
            .pickerStyle(.segmented)
            if !liveAllowed {
                Label("LIVE chưa đạt đủ điều kiện an toàn", systemImage: "lock.shield")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 10) {
                Button {
                    haptic(.warning); Task { await model.prepareLive() }
                } label: {
                    Label("Kiểm tra LIVE", systemImage: "checkmark.shield")
                }
                .buttonStyle(.bordered)
                .tint(.orange)
                .disabled(model.isRefreshing)

                Button(role: .destructive) {
                    haptic(.warning); confirmLive = true
                } label: {
                    Label("LIVE", systemImage: "bolt.fill")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!liveAllowed || model.isRefreshing)
            }
            HStack(spacing: 10) {
                Button {
                    haptic(.success)
                    if model.status?.mode == "LIVE" { confirmStartLive = true }
                    else { Task { await model.controlBot(.start) } }
                } label: {
                    Label("Chạy", systemImage: "play.fill")
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
                .disabled(model.isRefreshing)

                Button {
                    Task { await model.controlBot(.pause) }
                } label: {
                    Label("Tạm dừng", systemImage: "pause.fill")
                }
                .buttonStyle(.bordered)
                .disabled(model.isRefreshing)

                Button(role: .destructive) {
                    haptic(.error); confirmEmergency = true
                } label: {
                    Label("Khẩn cấp", systemImage: "hand.raised.fill")
                }
                .buttonStyle(.bordered)
                .disabled(model.isRefreshing)
            }
            .font(.subheadline.bold())

            if model.status?.botState == "SAFE_MODE" || model.status?.safeMode == true {
                Button {
                    Task { await model.resetSafeMode() }
                } label: {
                    Label("Khôi phục chế độ an toàn", systemImage: "arrow.clockwise.shield")
                }
                .buttonStyle(.borderedProminent)
                .tint(.orange)
                .disabled(model.isRefreshing)
            }
        }
        .padding()
        .liquidGlass()
        .confirmationDialog("Chuyển sang giao dịch tiền thật?", isPresented: $confirmLive, titleVisibility: .visible) {
            Button("Xác nhận chuyển LIVE", role: .destructive) { Task { await model.setMode("LIVE") } }
            Button("Giữ chế độ DEMO", role: .cancel) {}
        } message: {
            Text("Hãy chắc chắn đã kiểm tra kết nối Binance, bảo vệ Stop Loss, đối soát và giới hạn rủi ro.")
        }
        .confirmationDialog("Chạy bot ở chế độ LIVE?", isPresented: $confirmStartLive, titleVisibility: .visible) {
            Button("Chạy bot LIVE", role: .destructive) { Task { await model.controlBot(.start) } }
            Button("Hủy", role: .cancel) {}
        } message: { Text("Bot có thể đặt lệnh bằng tiền thật.") }
        .confirmationDialog("Kích hoạt dừng khẩn cấp?", isPresented: $confirmEmergency, titleVisibility: .visible) {
            Button("Dừng khẩn cấp", role: .destructive) { Task { await model.emergencyStop() } }
            Button("Hủy", role: .cancel) {}
        } message: { Text("Thao tác này khóa giao dịch mới và bảo vệ tài khoản ngay lập tức.") }
    }
}

private struct SystemStateBanner: View {
    @ObservedObject var model: TradingViewModel

    private var exchange: ExchangeSnapshot? {
        model.status?.exchange ?? model.exchange
    }

    private var isHealthy: Bool {
        model.status?.botState == "RUNNING"
            && exchange?.connection == "CONNECTED"
            && model.status?.safeMode != true
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
        let orders = exchange?.orders.count ?? 0
        let positions = exchange?.positions.count ?? 0
        if orders > 0 || positions > 0 {
            return "Có \(orders) order và \(positions) vị thế trên \(model.status?.mode ?? "mode hiện tại")."
        }
        return model.status?.autoTrader?.lastReason ?? "Backend chạy, exchange \(viExchangeConnection(exchange?.connection)), hiện chưa có lệnh/vị thế mở."
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
                Text("Phí vốn \(percent(item.fundingRate * 100))")
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
    @State private var realtimeState: KetNoiRealtime = .offline
    @State private var error: String?
    @State private var realtimeClient: RealtimeClient?

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
                        VStack(alignment: .leading, spacing: 12) {
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
                                HStack(spacing: 6) {
                                    Circle()
                                        .fill(realtimeState == .live ? Color.green : Color.orange)
                                        .frame(width: 7, height: 7)
                                    Text("\(realtimeState.rawValue) • \(interval)")
                                }
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(money(candles.last?.close))
                                .font(.title3.bold())
                        }
                            Picker("Khung", selection: $interval) {
                                Text("1m").tag("1m")
                                Text("5m").tag("5m")
                                Text("15m").tag("15m")
                                Text("1h").tag("1h")
                                Text("4h").tag("4h")
                                Text("1D").tag("1d")
                            }
                            .pickerStyle(.segmented)
                        }
                    }
                    GlassPanel {
                        InteractivePriceChart(candles: candles)
                            .frame(height: 430)
                        HStack {
                            InfoPill("Nến \(candles.count)")
                            InfoPill("Cập nhật \(lastUpdated.map(shortTime) ?? "-")")
                            if let last = candles.last {
                                InfoPill("Đóng cửa \(money(last.close))")
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
        .task(id: "\(selectedSymbol)-\(interval)") { await loadAndStream() }
        .onDisappear {
            realtimeClient?.close()
            realtimeClient = nil
        }
    }

    @MainActor
    private func loadAndStream() async {
        realtimeClient?.close()
        let client = RealtimeClient()
        realtimeClient = client
        realtimeState = .stale
        do {
            let response = try await TradingAPI.shared.klines(symbol: selectedSymbol, interval: interval, limit: 220)
            guard !Task.isCancelled else { return }
            candles = response.items
            lastUpdated = Date()
            error = nil
        } catch {
            guard !Task.isCancelled else { return }
            self.error = error.localizedDescription
        }
        guard !Task.isCancelled else { return }
        client.connectKline(symbol: selectedSymbol, interval: interval) { envelope in
            await MainActor.run {
                guard envelope.symbol == selectedSymbol, envelope.interval == interval else { return }
                if let index = candles.firstIndex(where: { $0.openTime == envelope.candle.openTime }) {
                    candles[index] = envelope.candle
                } else {
                    candles = Array((candles + [envelope.candle]).suffix(220))
                }
                lastUpdated = Date()
                error = nil
            }
        } onState: { state in
            await MainActor.run { realtimeState = state }
        }
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 60_000_000_000)
        }
        client.close()
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
        let usableHeight = max(size.height - verticalPadding * 2 - timeScaleHeight, 1)
        let priceHeight = usableHeight * 0.66
        let volumeTop = verticalPadding + priceHeight + 8
        let volumeHeight = usableHeight * 0.12
        let rsiTop = volumeTop + volumeHeight + 10
        let rsiHeight = usableHeight * 0.17
        let range = max(maxHigh - minLow, max(abs(maxHigh) * 0.0001, 0.000_000_01))
        let slot = plotWidth / CGFloat(items.count)
        let bodyWidth = max(min(slot * 0.68, 9), 1)
        let maxVolume = max(items.map(\.volume).max() ?? 1, 1)
        let ema20 = exponentialAverage(items.map(\.close), period: 20)
        let ema50 = exponentialAverage(items.map(\.close), period: 50)
        let rsi14 = relativeStrength(items.map(\.close), period: 14)
        func y(_ price: Double) -> CGFloat { verticalPadding + CGFloat((maxHigh - price) / range) * priceHeight }
        func rsiY(_ value: Double) -> CGFloat { rsiTop + CGFloat((100 - value) / 100) * rsiHeight }

        for line in 0...4 {
            let fraction = Double(line) / 4
            let lineY = verticalPadding + priceHeight * CGFloat(fraction)
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
            let volumeBarHeight = CGFloat(candle.volume / maxVolume) * volumeHeight
            context.fill(Path(CGRect(x: x - bodyWidth / 2, y: volumeTop + volumeHeight - volumeBarHeight, width: bodyWidth, height: volumeBarHeight)), with: .color(color.opacity(0.45)))
        }

        drawIndicator(context: context, values: ema20, color: .orange, slot: slot, transform: y)
        drawIndicator(context: context, values: ema50, color: .cyan, slot: slot, transform: y)
        for level in [30.0, 70.0] {
            var guide = Path(); guide.move(to: CGPoint(x: 0, y: rsiY(level))); guide.addLine(to: CGPoint(x: plotWidth, y: rsiY(level)))
            context.stroke(guide, with: .color((level == 30 ? Color.green : Color.red).opacity(0.4)), style: StrokeStyle(lineWidth: 0.75, dash: [3, 3]))
        }
        drawIndicator(context: context, values: rsi14, color: .purple, slot: slot, transform: rsiY)
        context.draw(Text("VOL").font(.system(size: 9, weight: .bold)).foregroundStyle(.secondary), at: CGPoint(x: 3, y: volumeTop), anchor: .topLeading)
        context.draw(Text("RSI 14").font(.system(size: 9, weight: .bold)).foregroundStyle(.secondary), at: CGPoint(x: 3, y: rsiTop), anchor: .topLeading)

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
            var crosshair = Path(); crosshair.move(to: CGPoint(x: x, y: 0)); crosshair.addLine(to: CGPoint(x: x, y: rsiTop + rsiHeight))
            context.stroke(crosshair, with: .color(.cyan.opacity(0.8)), style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
        }
    }

    private func drawIndicator(context: GraphicsContext, values: [Double?], color: Color, slot: CGFloat, transform: (Double) -> CGFloat) {
        var path = Path()
        var started = false
        for (index, value) in values.enumerated() {
            guard let value else { continue }
            let point = CGPoint(x: slot * (CGFloat(index) + 0.5), y: transform(value))
            if started { path.addLine(to: point) } else { path.move(to: point); started = true }
        }
        context.stroke(path, with: .color(color), lineWidth: 1.25)
    }

    private func exponentialAverage(_ values: [Double], period: Int) -> [Double?] {
        guard values.count >= period else { return Array(repeating: nil, count: values.count) }
        let multiplier = 2.0 / Double(period + 1)
        var result = Array<Double?>(repeating: nil, count: values.count)
        var current = values.prefix(period).reduce(0, +) / Double(period)
        result[period - 1] = current
        for index in period..<values.count {
            current = values[index] * multiplier + current * (1 - multiplier)
            result[index] = current
        }
        return result
    }

    private func relativeStrength(_ values: [Double], period: Int) -> [Double?] {
        guard values.count > period else { return Array(repeating: nil, count: values.count) }
        var result = Array<Double?>(repeating: nil, count: values.count)
        for index in period..<values.count {
            var gains = 0.0, losses = 0.0
            for cursor in (index - period + 1)...index {
                let delta = values[cursor] - values[cursor - 1]
                if delta >= 0 { gains += delta } else { losses -= delta }
            }
            result[index] = losses == 0 ? 100 : 100 - 100 / (1 + gains / losses)
        }
        return result
    }
}

private struct ScannerView: View {
    @ObservedObject var model: TradingViewModel
    @State private var query = ""
    @State private var signal = "ALL"

    private var setups: [MultiTimeframeSetup] {
        MultiTimeframeSetup.build(from: model.scanner).filter { setup in
            (query.isEmpty || setup.trigger.symbol.localizedCaseInsensitiveContains(query)) &&
            (signal == "ALL" || setup.trigger.action == signal)
        }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Label("Hướng lệnh: 4h + 1h. 15m chỉ là điểm bấm cò; không đồng thuận thì không vào lệnh.", systemImage: "shield.lefthalf.filled")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .listRowBackground(Color.clear)

                ForEach(setups) { setup in
                    NavigationLink {
                        SignalDetailView(setup: setup)
                    } label: {
                        ScannerRow(setup: setup)
                            .padding()
                            .liquidGlass()
                    }
                    .glassListRow()
                }
            }
            .navigationTitle("Tín hiệu")
            .tradingGlassList()
            .searchable(text: $query, prompt: "Tìm mã")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Picker("Tín hiệu 15m", selection: $signal) {
                        Text("Tất cả").tag("ALL")
                        Text("BUY").tag("LONG")
                        Text("SELL").tag("SHORT")
                        Text("Không vào lệnh").tag("NO_TRADE")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) { RefreshButtonView(model: model) }
            }
            .overlay { if setups.isEmpty { EmptyContent("Chưa có tín hiệu 15m realtime từ backend.") } }
        }
    }
}

private struct SignalDetailView: View {
    let setup: MultiTimeframeSetup
    private var signal: TinHieuQuet { setup.trigger }
    private var confidence: Int { max(signal.longScore, signal.shortScore) }
    var body: some View {
        List {
            Section("Tín hiệu AI") {
                HStack {
                    StatusChip(text: signal.action == "LONG" ? "BUY" : signal.action == "SHORT" ? "SELL" : "HOLD", color: scannerActionColor(signal.action))
                    Spacer(); Text("Độ tin cậy \(confidence)%").font(.headline).foregroundStyle(.purple)
                }
                InfoRow(label: "Xu hướng", value: viRegime(signal.regime))
                InfoRow(label: "Momentum", value: signal.indicators.macdHistogram.map { $0 >= 0 ? "Tích cực" : "Tiêu cực" } ?? "Chưa có")
                InfoRow(label: "RSI", value: number(signal.indicators.rsi))
                InfoRow(label: "Chiến lược", value: signal.strategy ?? "Mặc định")
            }
            Section("Thiết lập giao dịch") {
                InfoRow(label: "Entry", value: money(signal.price))
                InfoRow(label: "Stop Loss", value: money(signal.stopLoss))
                InfoRow(label: "Take Profit", value: signal.takeProfits.map(money).joined(separator: " / "))
                InfoRow(label: "R:R", value: number(signal.riskReward))
                InfoRow(label: "Xác nhận", value: setup.confirmation)
            }
            Section {
                NavigationLink { CoinChartView(symbol: signal.symbol) } label: {
                    Label("Xem biểu đồ và setup", systemImage: "chart.xyaxis.line")
                }
            }
        }
        .navigationTitle(signal.symbol)
        .tradingGlassList()
    }
}

private struct MultiTimeframeSetup: Identifiable {
    let trigger: TinHieuQuet
    let h1: TinHieuQuet?
    let h4: TinHieuQuet?
    let confirmation: String
    let isTradable: Bool

    var id: String { trigger.id }

    static func build(from results: [TinHieuQuet]) -> [MultiTimeframeSetup] {
        let frames = Dictionary(uniqueKeysWithValues: results.map { ("\($0.symbol)|\($0.timeframe)", $0) })
        return results.filter { $0.timeframe == "15m" }.map { trigger in
            let h1 = frames["\(trigger.symbol)|1h"]
            let h4 = frames["\(trigger.symbol)|4h"]
            let expectedAction = h4?.regime == "TRENDING_UP" ? "LONG" : h4?.regime == "TRENDING_DOWN" ? "SHORT" : "NO_TRADE"
            let tradable = trigger.action != "NO_TRADE" && h1 != nil && h4 != nil &&
                (h4?.regime == "TRENDING_UP" || h4?.regime == "TRENDING_DOWN") &&
                h1?.regime == h4?.regime && h1?.action == trigger.action && trigger.action == expectedAction
            let confirmation: String
            if h1 == nil || h4 == nil { confirmation = "Chờ dữ liệu 1h/4h" }
            else if h4?.regime != "TRENDING_UP" && h4?.regime != "TRENDING_DOWN" { confirmation = "CHƯA ĐẠT · 4h chưa có xu hướng rõ" }
            else if h1?.regime != h4?.regime { confirmation = "CHƯA ĐẠT · 1h chưa xác nhận 4h" }
            else if h1?.action != trigger.action || trigger.action != expectedAction { confirmation = "CHƯA ĐẠT · 15m không cùng chiều khung lớn" }
            else if trigger.action == "NO_TRADE" { confirmation = "Chờ bấm cò 15m" }
            else { confirmation = "ĐỦ ĐIỀU KIỆN · 4h + 1h đồng thuận" }
            return MultiTimeframeSetup(trigger: trigger, h1: h1, h4: h4, confirmation: confirmation, isTradable: tradable)
        }
        .sorted { $0.isTradable != $1.isTradable ? $0.isTradable : max($0.trigger.longScore, $0.trigger.shortScore) > max($1.trigger.longScore, $1.trigger.shortScore) }
    }
}

private struct PositionsView: View {
    @ObservedObject var model: TradingViewModel
    @State private var confirmCloseAll = false

    private var exposure: Double {
        guard let balance = model.exchange?.balance.marginBalance, balance > 0 else { return 0 }
        return max(0, 1 - (model.exchange?.balance.available ?? 0) / balance)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        MetricTile(title: "Exposure", value: percent(exposure * 100), tint: exposure > 0.7 ? .red : .cyan)
                        MetricTile(title: "PnL chưa chốt", value: money(model.exchange?.balance.unrealizedPnl), tint: (model.exchange?.balance.unrealizedPnl ?? 0) >= 0 ? .green : .red)
                    }.listRowInsets(.init()).listRowBackground(Color.clear)
                }
                ForEach(model.positions) { item in
                    NavigationLink {
                        PositionDetailView(position: item, currentPrice: model.markets.first(where: { $0.symbol == item.symbol })?.lastPrice)
                    } label: { PositionRowCard(position: item) }
                    .glassListRow()
                }
            }
            .navigationTitle("Vị thế")
            .tradingGlassList()
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if !model.positions.isEmpty { Button("Đóng tất cả", role: .destructive) { confirmCloseAll = true } }
                }
                RefreshToolbarItem(model: model)
            }
            .overlay { if model.positions.isEmpty { EmptyContent("Chưa có vị thế đang mở.") } }
            .confirmationDialog("Đóng toàn bộ vị thế?", isPresented: $confirmCloseAll, titleVisibility: .visible) {
                Button("Xác nhận đóng toàn bộ", role: .destructive) { Task { await model.tradingControl(.closeAll) } }
                Button("Hủy", role: .cancel) {}
            } message: { Text("Lệnh này ảnh hưởng tất cả vị thế đang mở và không thể hoàn tác.") }
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
                Text("Giá vào \(money(position.entryPrice))")
                Spacer()
                Text("Giá hiện tại \(money(mark))")
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
                InfoRow(label: "Take Profit", value: position.takeProfits.map(money).joined(separator: " / "))
                InfoRow(label: "Break-even", value: position.breakEvenActive ? "Đang bật" : "Tắt")
                InfoRow(label: "Dời Stop Loss", value: position.trailingStopActive ? "Đang bật" : "Tắt")
            }
            Section("PNL") {
                InfoRow(label: "PNL đang mở", value: money(position.unrealizedPnl))
                InfoRow(label: "PNL đã chốt", value: money(position.realizedPnl))
                InfoRow(label: "Phí đã trả", value: money(position.feesPaid))
                InfoRow(label: "Phí vốn đã trả", value: money(position.fundingPaid))
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
    @State private var period = 7

    private var rows: [LenhDaChot] {
        model.trades.filter { trade in
            let okQuery = query.isEmpty || trade.symbol.localizedCaseInsensitiveContains(query)
            let okSide = side == "ALL" || trade.side == side
            let okResult = result == "ALL" || (result == "WIN" ? trade.netPnl > 0 : trade.netPnl <= 0)
            let date = ISO8601DateFormatter().date(from: trade.createdAt)
            let okPeriod = period == 0 || date.map { $0 >= Calendar.current.date(byAdding: .day, value: -period, to: Date())! } == true
            return okQuery && okSide && okResult && okPeriod
        }
    }

    var body: some View {
            List {
                Section {
                    Picker("Thời gian", selection: $period) {
                        Text("7 ngày").tag(7); Text("30 ngày").tag(30); Text("Tất cả").tag(0)
                    }.pickerStyle(.segmented)
                    HStack {
                        InfoRow(label: "Tổng giao dịch", value: "\(rows.count)")
                        Divider()
                        InfoRow(label: "PnL", value: money(rows.reduce(0) { $0 + $1.netPnl }))
                    }
                }
                ForEach(rows) { trade in
                NavigationLink {
                    TradeDetailView(trade: trade)
                } label: {
                    TradeRowCard(trade: trade)
                }
                .glassListRow()
                }
            }
            .navigationTitle("Lịch sử")
            .tradingGlassList()
            .searchable(text: $query, prompt: "Tìm mã")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Picker("Hướng", selection: $side) {
                        Text("Tất cả").tag("ALL")
                        Text("Mua").tag("LONG")
                        Text("Bán").tag("SHORT")
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

private struct OrdersView: View {
    @ObservedObject var model: TradingViewModel
    @State private var query = ""
    @State private var side = "TẤT CẢ"
    @State private var kind = "TẤT CẢ"

    private var rows: [ExchangeOrder] {
        (model.exchange?.orders ?? []).filter {
            (query.isEmpty || $0.symbol.localizedCaseInsensitiveContains(query)) &&
            (side == "TẤT CẢ" || $0.side == side) &&
            (kind == "TẤT CẢ" || (kind == "BẢO VỆ" ? $0.reduceOnly : !$0.reduceOnly))
        }
    }

    var body: some View {
        List {
            Section {
                Picker("Hướng", selection: $side) {
                    Text("Tất cả").tag("TẤT CẢ"); Text("Mua").tag("BUY"); Text("Bán").tag("SELL")
                }.pickerStyle(.segmented)
                Picker("Loại lệnh", selection: $kind) {
                    Text("Tất cả").tag("TẤT CẢ"); Text("Bảo vệ").tag("BẢO VỆ"); Text("Vào lệnh").tag("VÀO LỆNH")
                }.pickerStyle(.segmented)
            }
            Section("Lệnh đang hoạt động trên Binance") {
                if rows.isEmpty { EmptyContent("Không có lệnh đang hoạt động phù hợp bộ lọc.") }
                ForEach(rows) { order in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(order.symbol).font(.headline)
                            Text(viSide(order.side)).foregroundStyle(order.side == "BUY" ? .green : .red)
                            Spacer()
                            Text(viOrderStatus(order.status)).font(.caption.bold()).foregroundStyle(.secondary)
                        }
                        InfoRow(label: viOrderType(order.orderType), value: "\(number(order.quantity)) · \(money(order.price))")
                        if let stop = order.stopPrice { InfoRow(label: "Giá kích hoạt", value: money(stop)) }
                    }.padding(.vertical, 5)
                }
            }
        }
        .navigationTitle("Lệnh")
        .tradingGlassList()
        .searchable(text: $query, prompt: "Lọc theo cặp giao dịch")
        .refreshable { await model.refreshAll() }
        .overlay { if model.isRefreshing && rows.isEmpty { ProgressView("Đang tải lệnh…") } }
    }
}

private struct StrategiesView: View {
    @ObservedObject var model: TradingViewModel
    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                SectionBlock(title: "Chiến lược đang chạy") {
                    HStack {
                        StatusChip(text: model.status?.botState == "RUNNING" ? "Đang hoạt động" : "Chưa chạy", color: model.status?.botState == "RUNNING" ? .green : .secondary)
                        Spacer()
                        Text(displayMode(model.status?.mode)).font(.caption.bold()).foregroundStyle(.cyan)
                    }
                    InfoRow(label: "Khung thời gian", value: model.settings?.scanTimeframes.joined(separator: " · ") ?? "15m · 1h · 4h")
                    InfoRow(label: "Điểm tối thiểu", value: "\(model.settings?.minScoreToTrade ?? 0)")
                    InfoRow(label: "R:R tối thiểu", value: number(model.status?.risk.minimumRiskReward))
                    InfoRow(label: "Vị thế tối đa", value: "\(model.status?.risk.maxOpenPositions ?? 0)")
                    InfoRow(label: "Danh sách theo dõi", value: "\(model.settings?.whitelist.count ?? 0) cặp")
                }
                if let report = model.latestBacktest {
                    StrategyCard(report.baseline, active: true)
                    if let candidate = report.candidate { StrategyCard(candidate, active: report.candidateApplied) }
                } else {
                    SectionBlock(title: "Backtest") {
                        EmptyContent("Chưa có báo cáo backtest. Chiến lược phía trên vẫn lấy trực tiếp từ cấu hình production.")
                    }
                }
                Text("Cấu hình chiến lược chỉ được thay đổi sau khi backtest và kiểm định trên website.")
                    .font(.footnote).foregroundStyle(.secondary).padding(.horizontal)
            }.padding()
        }
        .navigationTitle("Chiến lược")
        .background(Color(.systemGroupedBackground))
        .refreshable { await model.refreshAll() }
    }
}

private struct StrategyCard: View {
    let value: BacktestStrategyReport
    let active: Bool
    init(_ value: BacktestStrategyReport, active: Bool) { self.value = value; self.active = active }
    var body: some View {
        SectionBlock(title: value.config.name) {
            HStack { StatusChip(text: active ? "Đang sử dụng" : "Chỉ theo dõi", color: active ? .green : .secondary); Spacer() }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                MetricTile(title: "Tỷ lệ thắng", value: percent(value.metrics.winrate * 100), tint: .cyan)
                MetricTile(title: "Profit factor", value: number(value.metrics.profitFactor), tint: .green)
                MetricTile(title: "Số giao dịch", value: "\(value.metrics.trades)", tint: .primary)
                MetricTile(title: "Drawdown", value: percent(value.maxDrawdownPercent), tint: .red)
            }
        }
    }
}

private struct AnalyticsView: View {
    @ObservedObject var model: TradingViewModel
    private var curve: [EquityPoint] { model.equityHistory }
    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                SectionBlock(title: "Đường cong vốn") {
                    if curve.isEmpty { EmptyContent("Chưa đủ giao dịch để vẽ đường cong vốn.") }
                    else {
                        Chart(curve) { point in
                            AreaMark(x: .value("Thời gian", point.takenAt), y: .value("Vốn", point.equity))
                                .foregroundStyle(.linearGradient(colors: [.cyan.opacity(0.35), .clear], startPoint: .top, endPoint: .bottom))
                            LineMark(x: .value("Thời gian", point.takenAt), y: .value("Vốn", point.equity)).foregroundStyle(.cyan).lineStyle(.init(lineWidth: 2))
                        }.frame(height: 230)
                    }
                }
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    MetricTile(title: "PnL", value: money(model.performance?.netPnl), tint: (model.performance?.netPnl ?? 0) >= 0 ? .green : .red)
                    MetricTile(title: "Tỷ lệ thắng", value: percent((model.performance?.winRate ?? 0) * 100), tint: .cyan)
                    MetricTile(title: "Profit factor", value: number(model.performance?.profitFactor), tint: .green)
                    MetricTile(title: "Drawdown", value: percent(model.performance?.maxDrawdown), tint: .red)
                    MetricTile(title: "Sharpe", value: number(model.performance?.sharpe), tint: .purple)
                    MetricTile(title: "Kỳ vọng", value: money(model.performance?.expectancy), tint: .blue)
                }
                SectionBlock(title: "Dữ liệu equity thực") {
                    InfoRow(label: "Số mẫu", value: "\(model.equityAnalytics?.samples ?? curve.count)")
                    InfoRow(label: "Đỉnh vốn", value: money(model.equityAnalytics?.peakEquity))
                    InfoRow(label: "Drawdown hiện tại", value: percent(model.equityAnalytics?.currentDrawdownPercent))
                    InfoRow(label: "Lợi nhuận theo equity", value: percent(model.equityAnalytics?.returnPercent))
                }
            }.padding()
        }
        .navigationTitle("Phân tích")
        .background(Color(.systemGroupedBackground))
        .refreshable { await model.refreshAll() }
    }
}

private struct RiskView: View {
    @ObservedObject var model: TradingViewModel
    private var exposure: Double {
        model.riskDashboard?.portfolio.grossExposureFraction ?? 0
    }
    private var level: (String, Color) {
        if model.status?.safeMode == true || exposure >= 0.8 { return ("CAO", .red) }
        if exposure >= 0.5 { return ("TRUNG BÌNH", .yellow) }
        return ("THẤP", .green)
    }
    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                SectionBlock(title: "Trạng thái rủi ro") {
                    HStack {
                        VStack(alignment: .leading) { Text("Mức rủi ro").foregroundStyle(.secondary); Text(level.0).font(.title.bold()).foregroundStyle(level.1) }
                        Spacer(); Image(systemName: "shield.checkered").font(.system(size: 42)).foregroundStyle(level.1)
                    }
                    ProgressView(value: exposure).tint(level.1)
                }
                SectionBlock(title: "Giới hạn bảo vệ") {
                    InfoRow(label: "Exposure gộp", value: percent(exposure * 100))
                    InfoRow(label: "Exposure ròng", value: percent((model.riskDashboard?.portfolio.netExposureFraction ?? 0) * 100))
                    InfoRow(label: "Rủi ro đang mở", value: money(model.riskDashboard?.portfolio.openRisk))
                    InfoRow(label: "Room rủi ro còn lại", value: money(model.riskDashboard?.portfolio.openRiskRemaining))
                    InfoRow(label: "Lỗ tối đa mỗi ngày", value: percent((model.status?.risk.maxDailyLoss ?? 0) * 100))
                    InfoRow(label: "Drawdown tuần tối đa", value: percent((model.status?.risk.maxWeeklyDrawdown ?? 0) * 100))
                    InfoRow(label: "Rủi ro mỗi lệnh", value: percent((model.status?.risk.riskPerTrade ?? 0) * 100))
                    InfoRow(label: "Số vị thế tối đa", value: "\(model.status?.risk.maxOpenPositions ?? 0)")
                    InfoRow(label: "R:R tối thiểu", value: number(model.status?.risk.minimumRiskReward))
                }
                SectionBlock(title: "Kiểm soát danh mục") {
                    InfoRow(label: "Chế độ", value: model.riskDashboard?.portfolio.enforcementEnabled == true ? "Đang thực thi" : "Chỉ theo dõi")
                    InfoRow(label: "Lần kiểm tra", value: "\(model.riskDashboard?.auditSummary.total ?? 0)")
                    InfoRow(label: "Có thể nhận lệnh mới", value: model.riskDashboard?.portfolio.wouldRejectNewEntries == true ? "Không" : "Có")
                    ForEach(model.riskDashboard?.portfolio.reasons ?? [], id: \.self) { reason in
                        Label(reason, systemImage: "exclamationmark.triangle.fill").font(.footnote).foregroundStyle(.yellow)
                    }
                }
                if model.status?.safeMode == true {
                    Label(model.status?.safeModeReason ?? "Hệ thống đang ở chế độ an toàn.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red).padding().frame(maxWidth: .infinity, alignment: .leading).background(.red.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
                }
            }.padding()
        }
        .navigationTitle("Rủi ro")
        .background(Color(.systemGroupedBackground))
        .refreshable { await model.refreshAll() }
    }
}

private struct JournalView: View {
    @ObservedObject var model: TradingViewModel
    @State private var category = "ALL"
    private var rows: [NhatKy] { model.journal.filter { category == "ALL" || journalCategory($0) == category } }
    var body: some View {
        List {
            Section {
                Picker("Loại sự kiện", selection: $category) {
                    Text("Tất cả").tag("ALL"); Text("Giao dịch").tag("TRADING"); Text("AI").tag("AI"); Text("Rủi ro").tag("RISK"); Text("Hệ thống").tag("SYSTEM"); Text("Lỗi").tag("ERRORS")
                }.pickerStyle(.menu)
            }
            if rows.isEmpty { EmptyContent("Chưa có sự kiện phù hợp bộ lọc.") }
            ForEach(rows) { item in
                HStack(alignment: .top, spacing: 12) {
                    Circle().fill(journalColor(item)).frame(width: 9, height: 9).padding(.top, 6)
                    VStack(alignment: .leading, spacing: 5) {
                        Text(item.message).font(.subheadline)
                        Text(item.createdAt).font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(.vertical, 4)
            }
        }
        .navigationTitle("Nhật ký")
        .tradingGlassList()
        .refreshable { await model.refreshAll() }
    }
}

private struct SystemStatusView: View {
    @ObservedObject var model: TradingViewModel
    var body: some View {
        List {
            Section("Kết nối") {
                InfoRow(label: "API", value: model.isAuthenticated ? "Hoạt động" : "Mất kết nối")
                InfoRow(label: "Exchange", value: viExchangeConnection(model.exchange?.connection))
                InfoRow(label: "Dữ liệu thị trường", value: model.realtimeState == .live ? "Realtime" : "Đang kết nối lại")
                InfoRow(label: "Telegram", value: model.operations?.notifications.configured == true ? "Đã cấu hình" : "Chưa cấu hình")
            }
            Section("Dịch vụ") {
                InfoRow(label: "AI Engine", value: model.operations?.aiAnalytics.shadowOnly == true ? "Chế độ theo dõi" : "Hoạt động")
                InfoRow(label: "Cache", value: "\((model.operations?.gateway.market.cache.hits ?? 0)) lượt trúng")
                InfoRow(label: "Reconcile", value: model.operations?.reconciliation.safeMode == true ? "Cần kiểm tra" : "Bình thường")
                InfoRow(label: "Auto Loop", value: viAutoStatus(model.status?.autoTrader?.lastStatus))
                InfoRow(label: "Cập nhật gần nhất", value: model.lastRealtimeAt.map(shortTime) ?? "Chưa có")
            }
        }
        .navigationTitle("Trạng thái hệ thống")
        .tradingGlassList()
        .refreshable { await model.refreshAll() }
    }
}

private struct MoreView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        NavigationStack {
            List {
                Section("Giao dịch") {
                    NavigationLink { OrdersView(model: model) } label: { MenuRow("Lệnh", "list.bullet.rectangle.portrait", .cyan) }
                    NavigationLink { TradesView(model: model) } label: { MenuRow("Lịch sử", "clock.arrow.circlepath", .green) }
                    NavigationLink { StrategiesView(model: model) } label: { MenuRow("Chiến lược", "point.3.connected.trianglepath.dotted", .purple) }
                }
                Section("Hiệu suất và an toàn") {
                    NavigationLink { AnalyticsView(model: model) } label: { MenuRow("Phân tích", "chart.bar.xaxis", .blue) }
                    NavigationLink { RiskView(model: model) } label: { MenuRow("Rủi ro", "shield.lefthalf.filled", .yellow) }
                    NavigationLink { JournalView(model: model) } label: { MenuRow("Nhật ký", "text.justify.left", .orange) }
                }
                Section("Hệ thống") {
                    NavigationLink { SystemStatusView(model: model) } label: { MenuRow("Trạng thái hệ thống", "server.rack", .mint) }
                    NavigationLink { SettingsView(model: model) } label: { MenuRow("Cài đặt", "gearshape.fill", .secondary) }
                }
                Section {
                    Button(role: .destructive) { Task { await model.logout() } } label: {
                        Label("Đăng xuất", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .navigationTitle("Thêm")
            .tradingGlassList()
            .refreshable { await model.refreshAll() }
        }
    }
}

private struct MenuRow: View {
    let title: String
    let icon: String
    let color: Color
    init(_ title: String, _ icon: String, _ color: Color) { self.title = title; self.icon = icon; self.color = color }
    var body: some View {
        Label { Text(title).fontWeight(.semibold) } icon: {
            Image(systemName: icon).foregroundStyle(color).frame(width: 24)
        }
        .padding(.vertical, 5)
    }
}

private struct SettingsView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        List {
                Section("Chế độ giao dịch") {
                    InfoRow(label: "Chế độ hiện tại", value: displayMode(model.status?.mode))
                    Text("Chuyển DEMO/LIVE tại màn hình Tổng quan để luôn thấy checklist an toàn và cảnh báo tiền thật.")
                        .font(.caption).foregroundStyle(.secondary)
                    if let reason = model.status?.safeModeReason {
                        Text(reason).foregroundStyle(.red)
                    }
                }
                Section("Điều kiện LIVE") {
                    Button("Kiểm tra điều kiện LIVE") {
                        Task { await model.prepareLive() }
                    }
                    InfoRow(label: "Toàn bộ kiểm thử", value: model.status?.liveReadiness.allTestsPass == true ? "Đạt" : "Chưa đạt")
                    InfoRow(label: "DEMO ổn định", value: model.status?.liveReadiness.demoStable == true ? "Đạt" : "Chưa đạt")
                    InfoRow(label: "Bảo vệ Stop Loss", value: model.status?.liveReadiness.slProtectionPass == true ? "Đạt" : "Chưa đạt")
                    InfoRow(label: "Tự kết nối lại", value: model.status?.liveReadiness.reconnectPass == true ? "Đạt" : "Chưa đạt")
                    InfoRow(label: "Đối soát", value: model.status?.liveReadiness.reconciliationPass == true ? "Đạt" : "Chưa đạt")
                    InfoRow(label: "Chống trùng lệnh", value: model.status?.liveReadiness.duplicateOrderTestsPass == true ? "Đạt" : "Chưa đạt")
                }
                Section("Bảo mật") {
                    Label("Phiên thiết bị được bảo vệ bằng Keychain và Face ID", systemImage: "checkmark.shield.fill")
                        .foregroundStyle(.green)
                    NavigationLink("Thiết bị đã đăng nhập") {
                        DeviceSessionsView(model: model)
                    }
                    Button("Đăng xuất", role: .destructive) { Task { await model.logout() } }
                }
                Section("Cấu hình bộ quét") {
                    InfoRow(label: "Khối lượng tối thiểu", value: compact(model.settings?.minQuoteVolume))
                    InfoRow(label: "Chênh lệch tối đa", value: "\(number(model.settings?.maxSpreadBps)) bps")
                    InfoRow(label: "Tuổi niêm yết tối thiểu", value: "\(model.settings?.minListingAgeDays ?? 0) ngày")
                    InfoRow(label: "Điểm vào lệnh tối thiểu", value: "\(model.settings?.minScoreToTrade ?? 0)")
                    Text("Các giá trị này lấy trực tiếp từ máy chủ production. Chỉ thay đổi bộ quét và rủi ro sau khi đã kiểm thử trên website.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("AI") {
                    InfoRow(label: "Chế độ", value: model.operations?.aiAnalytics.shadowOnly == true ? "Theo dõi, không đặt lệnh" : "Đang hoạt động")
                    InfoRow(label: "Mẫu huấn luyện", value: "\(model.operations?.aiAnalytics.training?.sampleSize ?? 0)")
                    InfoRow(label: "Sẵn sàng thực thi", value: model.operations?.aiAnalytics.training?.readyForExecution == true ? "Có" : "Chưa")
                }
                Section("Thông báo và Telegram") {
                    InfoRow(label: "Telegram", value: model.operations?.notifications.configured == true ? "Đã cấu hình" : "Chưa cấu hình")
                    InfoRow(label: "Lệnh điều khiển", value: model.operations?.notifications.commandsEnabled == true ? "Đang bật" : "Đang tắt")
                    InfoRow(label: "Đã gửi", value: "\(model.operations?.notifications.sent ?? 0)")
                }
                Section("Hệ thống và Exchange") {
                    InfoRow(label: "Binance", value: viExchangeConnection(model.exchange?.connection))
                    InfoRow(label: "Dữ liệu realtime", value: model.realtimeState == .live ? "Hoạt động" : "Đang kết nối lại")
                    NavigationLink { SystemStatusView(model: model) } label: { Label("Xem trạng thái hệ thống", systemImage: "server.rack") }
                }
                Section("Lệnh DEMO trên Binance") {
                    if model.exchange?.orders.isEmpty != false {
                        EmptyContent("Chưa có lệnh DEMO từ Binance.")
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
                                Text("SL/TP \(money(order.stopPrice)) - Chỉ giảm vị thế: \(order.reduceOnly ? "Có" : "Không")")
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
                                Text("Giá vào \(money(position.entryPrice)) · Hiện tại \(money(position.markPrice))")
                                    .font(.subheadline)
                                Text("PnL \(money(position.unrealizedPnl)) · Thanh lý \(money(position.liquidationPrice)) · \(position.leverage ?? 0)x")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Cài đặt")
            .tradingGlassList()
            .toolbar { RefreshToolbarItem(model: model) }
    }
}

private struct DeviceSessionsView: View {
    @ObservedObject var model: TradingViewModel

    var body: some View {
        List {
            if model.deviceSessions.isEmpty {
                ContentUnavailableView(
                    "Chưa có thiết bị",
                    systemImage: "iphone.slash",
                    description: Text("Danh sách phiên thiết bị đang hoạt động sẽ xuất hiện tại đây.")
                )
            } else {
                ForEach(model.deviceSessions) { session in
                    VStack(alignment: .leading, spacing: 6) {
                        Label(session.deviceName, systemImage: "iphone")
                            .font(.headline)
                        Text("Hoạt động gần nhất: \(session.lastUsedAt)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Button("Đăng xuất thiết bị", role: .destructive) {
                            Task { await model.revokeDeviceSession(id: session.id) }
                        }
                        .font(.subheadline.weight(.semibold))
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .navigationTitle("Thiết bị đã đăng nhập")
        .task { await model.loadDeviceSessions() }
        .refreshable { await model.loadDeviceSessions() }
    }
}

private struct ScannerRow: View {
    let setup: MultiTimeframeSetup

    var body: some View {
        let item = setup.trigger
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(item.symbol).font(.headline)
                Spacer()
                Text(setup.isTradable ? viAction(item.action) : "KHÔNG VÀO")
                    .fontWeight(.semibold)
                    .foregroundStyle(setup.isTradable ? scannerActionColor(item.action) : .orange)
            }
            HStack {
                Text("Giá \(money(item.price))")
                Spacer()
                Text("24h \(signedPercent(item.priceChangePercent))")
            }
            .font(.subheadline)
            HStack(spacing: 6) {
                timeframeChip("4h", setup.h4)
                timeframeChip("1h", setup.h1)
                timeframeChip("15m", item)
            }
            Text(setup.confirmation)
                .font(.caption.weight(.semibold))
                .foregroundStyle(setup.isTradable ? .green : .orange)
            HStack {
                Text("15m BUY \(item.longScore) · SELL \(item.shortScore)")
                Spacer()
                Text(viRegime(item.regime))
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }

    private func timeframeChip(_ label: String, _ value: TinHieuQuet?) -> some View {
        let direction = value.map { viAction($0.action) } ?? "—"
        let color = value?.action == "LONG" ? Color.green : value?.action == "SHORT" ? Color.red : Color.secondary
        return Text("\(label) \(direction)")
            .font(.caption2.bold())
            .foregroundStyle(color)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(color.opacity(0.14), in: Capsule())
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
        ContentUnavailableView("Chưa có dữ liệu", systemImage: "tray", description: Text(message))
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
    vietnamDateString(
        Date(timeIntervalSince1970: TimeInterval(milliseconds) / 1_000),
        dateStyle: .none,
        timeStyle: .short
    )
}

private func chartDate(_ milliseconds: Int) -> String {
    vietnamDateString(
        Date(timeIntervalSince1970: TimeInterval(milliseconds) / 1_000),
        dateStyle: .short,
        timeStyle: .short
    )
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
    vietnamDateString(date, dateStyle: .none, timeStyle: .medium)
}

private func vietnamDateString(
    _ date: Date,
    dateStyle: DateFormatter.Style,
    timeStyle: DateFormatter.Style
) -> String {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "vi_VN")
    formatter.timeZone = TimeZone(identifier: "Asia/Ho_Chi_Minh")
    formatter.dateStyle = dateStyle
    formatter.timeStyle = timeStyle
    return formatter.string(from: date)
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
    case "LONG": return "BUY"
    case "SHORT": return "SELL"
    case "NO_TRADE": return "HOLD"
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
    case "LONG", "BUY": return "Mua"
    case "SHORT", "SELL": return "Bán"
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
    case "MARKET": return "Lệnh thị trường"
    case "LIMIT": return "Lệnh giới hạn"
    case "STOP_MARKET": return "Dừng theo thị trường"
    case "TAKE_PROFIT_MARKET": return "Chốt lời theo thị trường"
    case "TRAILING_STOP_MARKET": return "Dời Stop Loss"
    default: return value
    }
}

private func viOrderStatus(_ value: String) -> String {
    switch value {
    case "NEW": return "Đang chờ"
    case "PARTIALLY_FILLED": return "Khớp một phần"
    case "FILLED": return "Đã khớp"
    case "CANCELED", "CANCELLED": return "Đã hủy"
    case "REJECTED": return "Bị từ chối"
    case "EXPIRED": return "Đã hết hạn"
    default: return value
    }
}

private func journalCategory(_ item: NhatKy) -> String {
    let backendCategory = item.category.uppercased()
    if ["TRADING", "AI", "RISK", "SYSTEM"].contains(backendCategory) { return backendCategory }
    if ["ERROR", "ERRORS"].contains(backendCategory) { return "ERRORS" }
    let text = item.message.lowercased()
    if ["error", "failed", "exception", "lỗi"].contains(where: text.contains) || item.level.uppercased() == "ERROR" { return "ERRORS" }
    if ["ai", "model", "training", "shadow"].contains(where: text.contains) { return "AI" }
    if ["risk", "exposure", "drawdown", "limit"].contains(where: text.contains) { return "RISK" }
    if ["signal", "order", "trade", "position", "entry", "exit"].contains(where: text.contains) { return "TRADING" }
    return "SYSTEM"
}

private func journalColor(_ item: NhatKy) -> Color {
    switch journalCategory(item) {
    case "ERRORS": return .red
    case "AI": return .purple
    case "RISK": return .yellow
    case "TRADING": return .green
    default: return .blue
    }
}

private func haptic(_ type: UINotificationFeedbackGenerator.FeedbackType) {
    UINotificationFeedbackGenerator().notificationOccurred(type)
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
