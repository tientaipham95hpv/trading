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

    public func settings() async throws -> CaiDatBot {
        try await get("/api/settings")
    }

    public func updateSettings(_ settings: CaiDatBot) async throws -> CaiDatBot {
        try await send("/api/settings", method: "PUT", body: settings)
    }

    @discardableResult
    public func controlBot(_ action: BotAction) async throws -> PhanHoiBot {
        try await post("/api/bot/\(action.rawValue)")
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

public enum TradingAPIError: Error, LocalizedError {
    case requestFailed(String)

    public var errorDescription: String? {
        switch self {
        case .requestFailed(let message): return message
        }
    }
}
