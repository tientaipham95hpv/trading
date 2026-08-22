import Foundation

public actor TradingAPI {
    public static let shared = TradingAPI()

    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder
    private let authStore: SecureAuthStore

    public init(
        baseURL: URL = URL(string: "https://trading.cineviet.live")!,
        session: URLSession = .shared,
        authStore: SecureAuthStore = .shared
    ) {
        self.baseURL = baseURL
        self.session = session
        self.authStore = authStore
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    public func status() async throws -> TrangThaiBot {
        try await get("/api/status")
    }

    public func markets() async throws -> [ThiTruong] {
        let response: DanhSachPhanHoi<ThiTruong> = try await get("/api/markets")
        return response.items
    }

    public func klines(symbol: String, interval: String = "15m", limit: Int = 180) async throws -> KlineResponse {
        try await get("/api/klines/\(symbol.uppercased())?interval=\(interval)&limit=\(limit)")
    }

    public func scanner(limit: Int = 40, timeframes: String = "15m") async throws -> [TinHieuQuet] {
        let response: DanhSachPhanHoi<TinHieuQuet> = try await get("/api/scanner?limit=\(limit)&timeframes=\(timeframes)")
        return response.items
    }

    public func positions() async throws -> [ViThe] {
        let response: DanhSachPhanHoi<ViThe> = try await get("/api/positions")
        return response.items
    }

    public func trades() async throws -> [LenhDaChot] {
        let response: DanhSachPhanHoi<LenhDaChot> = try await get("/api/trades")
        return response.items
    }

    public func performance() async throws -> HieuSuat {
        try await get("/api/performance")
    }

    public func operations() async throws -> OperationsStatus {
        try await get("/api/operations")
    }

    public func latestBacktest() async throws -> BacktestReport {
        try await get("/api/backtests/latest")
    }

    public func exchange() async throws -> ExchangeSnapshot {
        try await get("/api/exchange")
    }

    public func settings() async throws -> CaiDatBot {
        try await get("/api/settings")
    }

    public func updateSettings(_ settings: CaiDatBot) async throws -> CaiDatBot {
        try await send("/api/settings", method: "PUT", body: settings)
    }

    @discardableResult
    public func setMode(_ mode: String) async throws -> ModeResponse {
        try await post("/api/mode/\(mode)")
    }

    @discardableResult
    public func controlBot(_ action: BotAction) async throws -> PhanHoiBot {
        try await post("/api/bot/\(action.rawValue)")
    }

    @discardableResult
    public func resetSafeMode() async throws -> ControlResponse {
        try await post("/api/safe-mode/reset")
    }

    @discardableResult
    public func tradingControl(_ action: TradingControlAction) async throws -> ControlResponse {
        try await post("/api/controls/\(action.rawValue)")
    }

    @discardableResult
    public func emergencyStop() async throws -> EmergencyStopResponse {
        try await post("/api/emergency-stop")
    }

    @discardableResult
    public func updateLiveConfig(_ update: LiveConfigUpdate) async throws -> LiveReadiness {
        try await send("/api/live/config", method: "PUT", body: update)
    }

    @discardableResult
    public func prepareLive() async throws -> PrepareLiveResponse {
        try await post("/api/live/prepare")
    }

    public func websocketURL(channel: String) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        components.path = "/api/ws/\(channel)"
        components.scheme = baseURL.scheme == "https" ? "wss" : "ws"
        return components.url!
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = try request(path: path, method: "GET")
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(T.self, from: data)
    }

    private func post<T: Decodable>(_ path: String) async throws -> T {
        let request = try request(path: path, method: "POST")
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(T.self, from: data)
    }

    private func send<Body: Encodable, Output: Decodable>(_ path: String, method: String, body: Body) async throws -> Output {
        var request = try request(path: path, method: method)
        request.httpBody = try encoder.encode(body)
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(Output.self, from: data)
    }

    private func request(path: String, method: String) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "content-type")
        request.setValue("application/json", forHTTPHeaderField: "accept")
        if let token = authStore.loadToken(), !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        }
        return request
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            let message = String(data: data, encoding: .utf8) ?? "Backend trả lỗi không đọc được"
            throw TradingAPIError.requestFailed(message)
        }
    }
}

public enum BotAction: String, CaseIterable, Identifiable {
    case start
    case pause
    case stop

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .start: return "Chạy"
        case .pause: return "Tạm dừng"
        case .stop: return "Dừng"
        }
    }
}

public enum TradingControlAction: String, CaseIterable, Identifiable {
    case pauseNewTrades = "pause-new-trades"
    case cancelOrders = "cancel-orders"
    case closeAll = "close-all"

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .pauseNewTrades: return "Pause New Trades"
        case .cancelOrders: return "Cancel Orders"
        case .closeAll: return "Close All"
        }
    }
}

public struct ControlResponse: Codable {
    public let accepted: Bool
    public let reason: String?
}

public struct EmergencyStopResponse: Codable {
    public let active: Bool
    public let reason: String?
}

public struct LiveConfigUpdate: Codable {
    public var liveEnabled: Bool? = nil
    public var allTestsPass: Bool? = nil
    public var demoStable: Bool? = nil
    public var slProtectionPass: Bool? = nil
    public var reconnectPass: Bool? = nil
    public var reconciliationPass: Bool? = nil
    public var duplicateOrderTestsPass: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case liveEnabled = "live_enabled"
        case allTestsPass = "all_tests_pass"
        case demoStable = "demo_stable"
        case slProtectionPass = "sl_protection_pass"
        case reconnectPass = "reconnect_pass"
        case reconciliationPass = "reconciliation_pass"
        case duplicateOrderTestsPass = "duplicate_order_tests_pass"
    }
}

public struct ModeResponse: Codable {
    public let accepted: Bool
    public let mode: String?
    public let reason: String?
}

public struct PrepareLiveResponse: Codable {
    public let accepted: Bool
    public let reason: String?
    public let readiness: LiveReadiness?
}

public enum TradingAPIError: Error, LocalizedError {
    case requestFailed(String)

    public var errorDescription: String? {
        switch self {
        case .requestFailed(let message): return message
        }
    }
}
