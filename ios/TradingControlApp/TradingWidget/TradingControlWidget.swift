import SwiftUI
import WidgetKit

private struct TradingWidgetStatus: Decodable {
    let mode: String
    let botState: String
    let safeMode: Bool
    let exchange: TradingWidgetExchange

    enum CodingKeys: String, CodingKey {
        case mode
        case botState = "bot_state"
        case safeMode = "safe_mode"
        case exchange
    }
}

private struct TradingWidgetExchange: Decodable {
    let connection: String
    let balance: TradingWidgetBalance
    let orders: [TradingWidgetOrder]
    let positions: [TradingWidgetPosition]
}

private struct TradingWidgetBalance: Decodable {
    let balance: Double
    let unrealizedPnl: Double

    enum CodingKeys: String, CodingKey {
        case balance
        case unrealizedPnl = "unrealized_pnl"
    }
}

private struct TradingWidgetOrder: Decodable {}
private struct TradingWidgetPosition: Decodable {}

private struct TradingEntry: TimelineEntry {
    let date: Date
    let status: TradingWidgetStatus?
}

private struct TradingProvider: TimelineProvider {
    func placeholder(in context: Context) -> TradingEntry {
        TradingEntry(date: Date(), status: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (TradingEntry) -> Void) {
        Task { completion(await loadEntry()) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TradingEntry>) -> Void) {
        Task {
            let entry = await loadEntry()
            completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(300))))
        }
    }

    private func loadEntry() async -> TradingEntry {
        guard let url = URL(string: "https://trading.cineviet.live/api/status") else {
            return TradingEntry(date: Date(), status: nil)
        }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let status = try JSONDecoder().decode(TradingWidgetStatus.self, from: data)
            return TradingEntry(date: Date(), status: status)
        } catch {
            return TradingEntry(date: Date(), status: nil)
        }
    }
}

private struct TradingWidgetView: View {
    let entry: TradingEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Trading")
                    .font(.headline)
                Spacer()
                Text(entry.status?.mode ?? "-")
                    .font(.caption.bold())
                    .foregroundStyle(entry.status?.mode == "LIVE" ? .red : .green)
            }
            Text(entry.status.map(statusLine) ?? "Chưa tải được trạng thái")
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            if let status = entry.status {
                HStack {
                    metric("Order", "\(status.exchange.orders.count)")
                    metric("Vị thế", "\(status.exchange.positions.count)")
                    metric("PNL", money(status.exchange.balance.unrealizedPnl))
                }
            }
        }
        .containerBackground(.background, for: .widget)
    }

    private func metric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.caption.bold()).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func statusLine(_ status: TradingWidgetStatus) -> String {
        "\(botState(status.botState)) • \(exchange(status.exchange.connection)) • \(money(status.exchange.balance.balance))"
    }

    private func botState(_ value: String) -> String {
        switch value {
        case "RUNNING": return "Đang chạy"
        case "PAUSED": return "Tạm dừng"
        case "SAFE_MODE": return "SAFE"
        default: return "Dừng"
        }
    }

    private func exchange(_ value: String) -> String {
        value == "CONNECTED" ? "Kết nối" : "Mất kết nối"
    }

    private func money(_ value: Double) -> String {
        value.formatted(.currency(code: "USD").precision(.fractionLength(0...2)))
    }
}

@main
struct TradingControlWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "TradingControlWidget", provider: TradingProvider()) { entry in
            TradingWidgetView(entry: entry)
        }
        .configurationDisplayName("Trading Bot")
        .description("Theo dõi nhanh trạng thái bot, vị thế và PNL.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}
