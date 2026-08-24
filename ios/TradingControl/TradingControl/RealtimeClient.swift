import Foundation

public final class RealtimeClient {
    private let api: TradingAPI
    private let session: URLSession
    private var task: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?

    public init(api: TradingAPI = .shared, session: URLSession = .shared) {
        self.api = api
        self.session = session
    }

    deinit {
        close()
    }

    public func connectSystem(onMessage: @escaping @Sendable (TrangThaiBot) async -> Void, onState: @escaping @Sendable (KetNoiRealtime) async -> Void) {
        connect(channel: "system", onState: onState) { data in
            if let envelope = try? JSONDecoder().decode(GoiRealtime<TrangThaiBot>.self, from: data),
               let status = envelope.data {
                await onMessage(status)
            }
        }
    }

    public func connectScanner(onMessage: @escaping @Sendable ([TinHieuQuet]) async -> Void, onState: @escaping @Sendable (KetNoiRealtime) async -> Void) {
        connect(channel: "scanner", onState: onState) { data in
            if let envelope = try? JSONDecoder().decode(GoiRealtime<TinHieuQuet>.self, from: data),
               let items = envelope.items {
                await onMessage(items)
            }
        }
    }

    public func connectKline(
        symbol: String,
        interval: String,
        onMessage: @escaping @Sendable (KlineRealtimeEnvelope) async -> Void,
        onState: @escaping @Sendable (KetNoiRealtime) async -> Void
    ) {
        connect(channel: "kline:\(symbol.uppercased()):\(interval)", onState: onState) { data in
            if let envelope = try? JSONDecoder().decode(KlineRealtimeEnvelope.self, from: data) {
                await onMessage(envelope)
            }
        }
    }

    public func close() {
        receiveTask?.cancel()
        task?.cancel(with: .goingAway, reason: nil)
        receiveTask = nil
        task = nil
    }

    private func connect(
        channel: String,
        onState: @escaping @Sendable (KetNoiRealtime) async -> Void,
        handle: @escaping @Sendable (Data) async -> Void
    ) {
        close()
        Task { await onState(.stale) }
        receiveTask = Task { [weak self] in
            guard let self else { return }
            let url = await api.websocketURL(channel: channel)
            let socket = session.webSocketTask(with: url)
            task = socket
            socket.resume()
            await onState(.live)
            while !Task.isCancelled {
                do {
                    let message = try await socket.receive()
                    await onState(.live)
                    switch message {
                    case .data(let data):
                        await handle(data)
                    case .string(let text):
                        await handle(Data(text.utf8))
                    @unknown default:
                        break
                    }
                } catch {
                    await onState(.offline)
                    try? await Task.sleep(nanoseconds: 2_500_000_000)
                    if !Task.isCancelled {
                        connect(channel: channel, onState: onState, handle: handle)
                    }
                    return
                }
            }
        }
    }
}
