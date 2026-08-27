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
        await refreshAll()
        if isAuthenticated { start() }
        else { errorMessage = nil }
    }

    public func refreshAll() async {
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            async let nextStatus = api.status()
            async let nextMarkets = api.markets()
            // Fetch all decision frames. The UI derives tradable rows only from
            // a 4h + 1h agreement, with 15m acting solely as the entry trigger.
            async let nextScanner = api.scanner(timeframes: "15m,1h,4h")
            async let nextPositions = api.positions()
            async let nextTrades = api.trades()
            async let nextJournal = api.journal()
            async let nextPerformance = api.performance()
            async let nextOperations = api.operations()
            async let nextExchange = api.exchange()
            async let nextSettings = api.settings()
            async let nextBacktest = try? api.latestBacktest()

            status = try await nextStatus
            markets = try await nextMarkets
            scanner = try await nextScanner
            positions = try await nextPositions
            trades = try await nextTrades
            journal = try await nextJournal
            performance = try await nextPerformance
            operations = try await nextOperations
            exchange = try await nextExchange
            settings = try await nextSettings
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
            isAuthenticated = response.authenticated
            passwordDraft = ""
            await refreshAll()
            if isAuthenticated { start() }
        } catch {
            errorMessage = "Không thể đăng nhập. Hãy kiểm tra mật khẩu và kết nối mạng."
        }
    }

    public func logout() async {
        _ = try? await api.logout()
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
