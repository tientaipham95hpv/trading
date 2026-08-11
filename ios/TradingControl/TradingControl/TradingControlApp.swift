import SwiftUI
import UserNotifications

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
    @StateObject private var push = PushNotificationCoordinator()

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
            MoreView(model: model, push: push)
                .tabItem { Label("Thêm", systemImage: "ellipsis.circle") }
        }
        .task {
            model.start()
            await push.refreshAuthorizationStatus()
        }
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
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 156), spacing: 12)], spacing: 12) {
                    MetricTile(title: "Trạng thái bot", value: viBotState(model.status?.botState), tint: .blue)
                    MetricTile(title: "Chế độ", value: model.status?.mode ?? "PAPER", tint: .green)
                    MetricTile(title: "LIVE", value: model.status?.liveEnabled == true ? "Bật" : "Tắt", tint: model.status?.liveEnabled == true ? .red : .green)
                    MetricTile(title: "Vốn hiện tại", value: money(model.performance?.equity), tint: .primary)
                    MetricTile(title: "PNL hôm nay", value: money(model.performance?.realizedPnl), tint: (model.performance?.realizedPnl ?? 0) >= 0 ? .green : .red)
                    MetricTile(title: "Sụt giảm vốn", value: percent(drawdown(model.performance)), tint: .red)
                    MetricTile(title: "Rủi ro mỗi lệnh", value: percent((model.status?.risk.riskPerTrade ?? 0) * 100), tint: .orange)
                    MetricTile(title: "Vị thế mở", value: "\(model.performance?.openPositions ?? model.positions.count)", tint: .purple)
                }
                .padding()

                SectionBlock(title: "Cơ hội nổi bật") {
                    let opportunities = model.scanner.filter { $0.action != "NO_TRADE" }.prefix(5)
                    if opportunities.isEmpty {
                        EmptyContent("Chưa có tín hiệu đủ điểm từ backend.")
                    } else {
                        ForEach(Array(opportunities)) { item in
                            ScannerRow(item: item)
                        }
                    }
                }
                .padding(.horizontal)

                SectionBlock(title: "Sức khỏe hệ thống") {
                    InfoRow(label: "Realtime", value: model.realtimeState.rawValue)
                    InfoRow(label: "Lần cập nhật", value: model.lastRealtimeAt.map(shortTime) ?? "-")
                    InfoRow(label: "Dừng khẩn cấp", value: model.status?.emergencyStop == true ? "Đang bật" : "Không")
                    InfoRow(label: "Vị thế tối đa", value: "\(model.status?.risk.maxOpenPositions ?? 0)")
                }
                .padding()
            }
            .navigationTitle("Trang chủ")
            .toolbar { RefreshToolbarItem(model: model) }
        }
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
                .padding(.vertical, 4)
            }
            .navigationTitle("Thị trường")
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
                ScannerRow(item: item)
            }
            .navigationTitle("Bộ quét")
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
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(item.symbol).font(.headline)
                            Spacer()
                            Text(viSide(item.side)).fontWeight(.semibold)
                        }
                        HStack {
                            Text("Giá vào \(money(item.entryPrice))")
                            Spacer()
                            Text("PNL đã chốt \(money(item.realizedPnl))")
                        }
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }
            }
            .navigationTitle("Vị thế")
            .toolbar { RefreshToolbarItem(model: model) }
            .overlay { if model.positions.isEmpty { EmptyContent("Chưa có vị thế PAPER đang mở.") } }
        }
    }
}

private struct PositionDetailView: View {
    let position: ViThe
    let currentPrice: Double?

    var body: some View {
        List {
            Section("Tổng quan") {
                InfoRow(label: "Mã", value: position.symbol)
                InfoRow(label: "Hướng", value: viSide(position.side))
                InfoRow(label: "Trạng thái", value: position.status)
                InfoRow(label: "Giá vào", value: money(position.entryPrice))
                InfoRow(label: "Giá hiện tại", value: money(currentPrice))
                InfoRow(label: "Khối lượng còn lại", value: number(position.remainingQuantity))
            }
            Section("Quản trị rủi ro") {
                InfoRow(label: "Stop loss", value: money(position.stopLoss))
                InfoRow(label: "Take profit", value: position.takeProfits.map(money).joined(separator: " / "))
                InfoRow(label: "Break-even", value: position.breakEvenActive ? "Đang bật" : "Tắt")
                InfoRow(label: "Trailing stop", value: position.trailingStopActive ? "Đang bật" : "Tắt")
            }
            Section("PNL") {
                InfoRow(label: "PNL đã chốt", value: money(position.realizedPnl))
                InfoRow(label: "Phí đã trả", value: money(position.feesPaid))
                InfoRow(label: "Funding đã trả", value: money(position.fundingPaid))
            }
        }
        .navigationTitle(position.symbol)
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
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(trade.symbol).font(.headline)
                        Spacer()
                        Text(trade.netPnl > 0 ? "Thắng" : "Thua")
                            .foregroundStyle(trade.netPnl > 0 ? .green : .red)
                    }
                    HStack {
                        Text("\(viSide(trade.side)) \(number(trade.quantity))")
                        Spacer()
                        Text("Ròng \(money(trade.netPnl))")
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
                .padding(.vertical, 4)
            }
            .navigationTitle("Lịch sử lệnh")
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
            .overlay { if rows.isEmpty { EmptyContent("Chưa có lịch sử lệnh PAPER.") } }
        }
    }
}

private struct MoreView: View {
    @ObservedObject var model: TradingViewModel
    @ObservedObject var push: PushNotificationCoordinator

    var body: some View {
        NavigationStack {
            List {
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
                Section("Xác thực backend") {
                    SecureField("Auth token", text: $model.tokenDraft)
                    Button("Lưu token vào Keychain") {
                        model.saveToken()
                    }
                    Button("Xóa token") {
                        model.tokenDraft = ""
                        model.saveToken()
                    }
                }
                Section("Chuẩn bị push APNs") {
                    InfoRow(label: "Quyền thông báo", value: viNotificationStatus(push.authorizationStatus))
                    Button("Xin quyền thông báo") {
                        Task { await push.requestPermission() }
                    }
                    if let token = push.deviceToken {
                        Text(token)
                            .font(.footnote.monospaced())
                            .textSelection(.enabled)
                    }
                }
                Section("Cấu hình scanner") {
                    InfoRow(label: "Khối lượng tối thiểu", value: compact(model.settings?.minQuoteVolume))
                    InfoRow(label: "Spread tối đa", value: "\(number(model.settings?.maxSpreadBps)) bps")
                    InfoRow(label: "Tuổi niêm yết tối thiểu", value: "\(model.settings?.minListingAgeDays ?? 0) ngày")
                    InfoRow(label: "Điểm vào lệnh tối thiểu", value: "\(model.settings?.minScoreToTrade ?? 0)")
                }
            }
            .navigationTitle("Thêm")
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
        .background(.background)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary))
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
    }
}

private struct InfoRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
            Spacer()
            Text(value)
                .fontWeight(.semibold)
                .foregroundStyle(.secondary)
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
    return value.formatted(.currency(code: "USD").precision(.fractionLength(value > 10 ? 2 : 6)))
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
    value == "LONG" ? "Long" : "Short"
}

private func viNotificationStatus(_ value: UNAuthorizationStatus) -> String {
    switch value {
    case .authorized: return "Đã cho phép"
    case .denied: return "Đã từ chối"
    case .ephemeral: return "Tạm thời"
    case .notDetermined: return "Chưa hỏi"
    case .provisional: return "Tạm cho phép"
    @unknown default: return "Không rõ"
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
