import Combine
import Foundation

@MainActor
public final class TradingViewModel: ObservableObject {
    @Published public private(set) var status: TrangThaiBot?
    @Published public private(set) var markets: [ThiTruong] = []
    @Published public private(set) var scanner: [TinHieuQuet] = []
    @Published public private(set) var positions: [ViThe] = []
    @Published public private(set) var trades: [LenhDaChot] = []
    @Published public private(set) var journal: [NhatKy] = []
    @Published public private(set) var performance: HieuSuat?
    @Published public private(set) var operations: OperationsStatus?
    @Published public private(set) var latestBacktest: BacktestReport?
    @Published public private(set) var exchange: ExchangeSnapshot?
    @Published public private(set) var settings: CaiDatBot?
    @Published public private(set) var realtimeState: KetNoiRealtime = .offline
    @Published public private(set) var lastRealtimeAt: Date?
    @Published public private(set) var isRefreshing = false
    @Published public var errorMessage: String?
    @Published public var tokenDraft: String = ""
    @Published public var passwordDraft: String = ""
    @Published public private(set) var isAuthenticated = false
    @Published public private(set) var isAuthenticating = false

    private let api: TradingAPI
    private let authStore: SecureAuthStore
    private let biometricGate: BiometricGate
    private let systemRealtime: RealtimeClient
    private let scannerRealtime: RealtimeClient
    private var refreshTask: Task<Void, Never>?

    public init(
        api: TradingAPI = .shared,
        authStore: SecureAuthStore = .shared,
        biometricGate: BiometricGate = BiometricGate()
    ) {
        self.api = api
        self.authStore = authStore
        self.biometricGate = biometricGate
        self.systemRealtime = RealtimeClient(api: api)
        self.scannerRealtime = RealtimeClient(api: api)
        self.tokenDraft = authStore.loadToken() ?? ""
    }

    deinit {
        refreshTask?.cancel()
        systemRealtime.close()
        scannerRealtime.close()
    }

    public func start() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            guard let self else { return }
            await refreshAll()
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                await refreshAll()
            }
        }
        systemRealtime.connectSystem { [weak self] nextStatus in
            await MainActor.run {
                self?.status = nextStatus
                self?.lastRealtimeAt = Date()
            }
        } onState: { [weak self] state in
            await MainActor.run { self?.setRealtime(state) }
        }
        scannerRealtime.connectScanner { [weak self] nextScanner in
            await MainActor.run {
                self?.scanner = nextScanner
                self?.lastRealtimeAt = Date()
            }
        } onState: { [weak self] state in
            await MainActor.run { self?.setRealtime(state) }
        }
    }

    public func restoreSession() async {
        if let refreshToken = authStore.loadRefreshToken(), !refreshToken.isEmpty {
            do {
                let unlocked = try await biometricGate.authorizeSensitiveAction(
                    reason: "Xác thực để mở CineViet Trading."
                )
                guard unlocked else { return }
                let response = try await api.refreshSession(refreshToken: refreshToken)
                if let replacement = response.refreshToken {
                    try authStore.saveRefreshToken(replacement)
                }
                isAuthenticated = response.authenticated
            } catch TradingAPIError.unauthorized {
                try? authStore.clearRefreshToken()
                isAuthenticated = false
                errorMessage = "Phiên thiết bị đã hết hạn. Vui lòng đăng nhập lại."
                return
            } catch {
                isAuthenticated = false
                errorMessage = "Chưa thể kết nối máy chủ. Phiên thiết bị vẫn được giữ an toàn."
                return
            }
        }
        await refreshAll()
        if isAuthenticated { start() }
        else { errorMessage = nil }
    }

    public func refreshAll() async {
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            async let nextStatus = api.status()
            // Auxiliary panels refresh independently. A slow market endpoint or
            // a temporarily incompatible optional payload must not blank the
            // whole overview after status has loaded successfully.
            async let nextMarkets = try? api.markets()
            async let nextScanner = try? api.cachedSignals()
            async let nextPositions = try? api.positions()
            async let nextTrades = try? api.trades()
            async let nextJournal = try? api.journal()
            async let nextPerformance = try? api.performance()
            async let nextOperations = try? api.operations()
            async let nextExchange = try? api.exchange()
            async let nextSettings = try? api.settings()
            async let nextBacktest = try? api.latestBacktest()

            status = try await nextStatus
            if let value = await nextMarkets { markets = value }
            if let value = await nextScanner { scanner = value }
            if let value = await nextPositions { positions = value }
            if let value = await nextTrades { trades = value }
            if let value = await nextJournal { journal = value }
            if let value = await nextPerformance { performance = value }
            if let value = await nextOperations { operations = value }
            if let value = await nextExchange { exchange = value }
            if let value = await nextSettings { settings = value }
            latestBacktest = await nextBacktest
            errorMessage = nil
            isAuthenticated = true
        } catch {
            errorMessage = error.localizedDescription
            if error.localizedDescription.contains("401") || error.localizedDescription.localizedCaseInsensitiveContains("token") {
                isAuthenticated = false
            }
        }
    }

    public func login() async {
        let password = passwordDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !password.isEmpty else {
            errorMessage = "Vui lòng nhập mật khẩu vận hành."
            return
        }
        isAuthenticating = true
        defer { isAuthenticating = false }
        do {
            let response = try await api.login(password: password)
            if let refreshToken = response.refreshToken {
                try authStore.saveRefreshToken(refreshToken)
            }
            isAuthenticated = response.authenticated
            passwordDraft = ""
            await refreshAll()
            if isAuthenticated { start() }
        } catch {
            errorMessage = "Không thể đăng nhập. Hãy kiểm tra mật khẩu và kết nối mạng."
        }
    }

    public func logout() async {
        let refreshToken = authStore.loadRefreshToken()
        _ = try? await api.logout(refreshToken: refreshToken)
        try? authStore.clearRefreshToken()
        isAuthenticated = false
        refreshTask?.cancel()
        systemRealtime.close()
        scannerRealtime.close()
    }

    public func saveToken() {
        do {
            if tokenDraft.isEmpty {
                try authStore.clearToken()
            } else {
                try authStore.saveToken(tokenDraft)
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func controlBot(_ action: BotAction) async {
        do {
            let allowed = try await biometricGate.authorizeSensitiveAction(reason: "Xác thực Face ID để \(action.title.lowercased()) bot.")
            guard allowed else { return }
            let response = try await api.controlBot(action)
            status = try await api.status()
            if response.accepted == false {
                errorMessage = response.reason ?? "Backend từ chối thao tác điều khiển bot."
            } else {
                errorMessage = "Bot đã chuyển sang \(viBotState(response.botState))."
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func setMode(_ mode: String) async {
        do {
            guard mode == "DEMO" || mode == "LIVE" else {
                errorMessage = "Chỉ hỗ trợ chế độ DEMO và LIVE."
                return
            }
            let response = try await api.setMode(mode)
            if response.accepted {
                await refreshAll()
            } else {
                errorMessage = response.reason ?? "Không đổi được chế độ"
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func tradingControl(_ action: TradingControlAction) async {
        do {
            let allowed = try await biometricGate.authorizeSensitiveAction(reason: "Xác thực Face ID để \(action.title).")
            guard allowed else { return }
            let response = try await api.tradingControl(action)
            await refreshAll()
            errorMessage = response.accepted ? "\(action.title) đã gửi." : (response.reason ?? "Không thực hiện được")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func resetSafeMode() async {
        do {
            let allowed = try await biometricGate.authorizeSensitiveAction(reason: "Xác thực Face ID để reset SAFE_MODE.")
            guard allowed else { return }
            let response = try await api.resetSafeMode()
            await refreshAll()
            errorMessage = response.accepted ? "SAFE_MODE đã reset. Kiểm tra lại rồi bấm Chạy." : (response.reason ?? "Không reset được SAFE_MODE")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func emergencyStop() async {
        do {
            let allowed = try await biometricGate.authorizeSensitiveAction(reason: "Xác thực Face ID để bật dừng khẩn cấp.")
            guard allowed else { return }
            _ = try await api.emergencyStop()
            await refreshAll()
            errorMessage = "Dừng khẩn cấp đã bật."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func updateLiveConfig(_ update: LiveConfigUpdate) async {
        do {
            _ = try await api.updateLiveConfig(update)
            await refreshAll()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    public func prepareLive() async {
        do {
            let response = try await api.prepareLive()
            await refreshAll()
            errorMessage = response.accepted ? "LIVE đã sẵn sàng. Kiểm tra lại rồi mới chuyển LIVE." : (response.reason ?? "Chưa chuẩn bị được LIVE")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func setRealtime(_ state: KetNoiRealtime) {
        realtimeState = state
        if state == .live {
            lastRealtimeAt = Date()
        }
    }
}
