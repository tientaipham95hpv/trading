import Foundation

public enum KetNoiRealtime: String {
    case live = "LIVE"
    case stale = "STALE"
    case offline = "OFFLINE"
}

public struct TrangThaiBot: Codable, Equatable {
    public let mode: String
    public let liveEnabled: Bool
    public let botState: String
    public let emergencyStop: Bool
    public let safeMode: Bool
    public let safeModeReason: String?
    public let exchange: ExchangeSnapshot
    public let risk: RuiRo
    public let liveReadiness: LiveReadiness

    enum CodingKeys: String, CodingKey {
        case mode
        case liveEnabled = "live_enabled"
        case botState = "bot_state"
        case emergencyStop = "emergency_stop"
        case safeMode = "safe_mode"
        case safeModeReason = "safe_mode_reason"
        case exchange
        case risk
        case liveReadiness = "live_readiness"
    }
}

public struct LiveReadiness: Codable, Equatable {
    public let liveEnabled: Bool
    public let allTestsPass: Bool
    public let demoStable: Bool
    public let slProtectionPass: Bool
    public let reconnectPass: Bool
    public let reconciliationPass: Bool
    public let duplicateOrderTestsPass: Bool
    public let allowed: Bool
    public let blockers: [String]

    enum CodingKeys: String, CodingKey {
        case liveEnabled = "live_enabled"
        case allTestsPass = "all_tests_pass"
        case demoStable = "demo_stable"
        case slProtectionPass = "sl_protection_pass"
        case reconnectPass = "reconnect_pass"
        case reconciliationPass = "reconciliation_pass"
        case duplicateOrderTestsPass = "duplicate_order_tests_pass"
        case allowed
        case blockers
    }
}

public struct ExchangeSnapshot: Codable, Equatable {
    public let mode: String
    public let connection: String
    public let safeMode: Bool
    public let safeModeReason: String?
    public let balance: ExchangeBalance
    public let orders: [ExchangeOrder]
    public let positions: [ExchangePosition]
    public let lastReconciledAt: String?
    public let lastUserStreamAt: String?

    enum CodingKeys: String, CodingKey {
        case mode
        case connection
        case safeMode = "safe_mode"
        case safeModeReason = "safe_mode_reason"
        case balance
        case orders
        case positions
        case lastReconciledAt = "last_reconciled_at"
        case lastUserStreamAt = "last_user_stream_at"
    }
}

public struct ExchangeBalance: Codable, Equatable {
    public let asset: String
    public let balance: Double
    public let available: Double
    public let marginBalance: Double
    public let unrealizedPnl: Double

    enum CodingKeys: String, CodingKey {
        case asset
        case balance
        case available
        case marginBalance = "margin_balance"
        case unrealizedPnl = "unrealized_pnl"
    }
}

public struct ExchangeOrder: Codable, Identifiable, Equatable {
    public var id: String { clientOrderId }
    public let symbol: String
    public let orderId: FlexibleID
    public let clientOrderId: String
    public let side: String
    public let orderType: String
    public let status: String
    public let price: Double
    public let quantity: Double
    public let executedQuantity: Double
    public let reduceOnly: Bool
    public let stopPrice: Double?

    enum CodingKeys: String, CodingKey {
        case symbol
        case orderId = "order_id"
        case clientOrderId = "client_order_id"
        case side
        case orderType = "order_type"
        case status
        case price
        case quantity
        case executedQuantity = "executed_quantity"
        case reduceOnly = "reduce_only"
        case stopPrice = "stop_price"
    }
}

public struct ExchangePosition: Codable, Identifiable, Equatable {
    public var id: String { "\(symbol)-\(side)" }
    public let symbol: String
    public let side: String
    public let quantity: Double
    public let entryPrice: Double
    public let markPrice: Double
    public let unrealizedPnl: Double
    public let liquidationPrice: Double?
    public let leverage: Int?
    public let marginType: String?

    enum CodingKeys: String, CodingKey {
        case symbol
        case side
        case quantity
        case entryPrice = "entry_price"
        case markPrice = "mark_price"
        case unrealizedPnl = "unrealized_pnl"
        case liquidationPrice = "liquidation_price"
        case leverage
        case marginType = "margin_type"
    }
}

public enum FlexibleID: Codable, Equatable {
    case string(String)
    case int(Int)

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let int = try? container.decode(Int.self) {
            self = .int(int)
        } else {
            self = .string(try container.decode(String.self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .int(let value): try container.encode(value)
        }
    }
}

public struct RuiRo: Codable, Equatable {
    public let maxLeverage: Int
    public let riskPerTrade: Double
    public let maxRiskPerTrade: Double
    public let maxDailyLoss: Double
    public let maxWeeklyDrawdown: Double
    public let maxOpenPositions: Int
    public let maxPortfolioExposure: Double
    public let maxCorrelatedPositions: Int
    public let maxLossStreak: Int
    public let minimumRiskReward: Double

    enum CodingKeys: String, CodingKey {
        case maxLeverage = "max_leverage"
        case riskPerTrade = "risk_per_trade"
        case maxRiskPerTrade = "max_risk_per_trade"
        case maxDailyLoss = "max_daily_loss"
        case maxWeeklyDrawdown = "max_weekly_drawdown"
        case maxOpenPositions = "max_open_positions"
        case maxPortfolioExposure = "max_portfolio_exposure"
        case maxCorrelatedPositions = "max_correlated_positions"
        case maxLossStreak = "max_loss_streak"
        case minimumRiskReward = "minimum_risk_reward"
    }
}

public struct ThiTruong: Codable, Identifiable, Equatable {
    public var id: String { symbol }
    public let symbol: String
    public let baseAsset: String
    public let quoteAsset: String
    public let status: String
    public let quoteVolume: Double
    public let priceChangePercent: Double
    public let fundingRate: Double
    public let bidPrice: Double
    public let askPrice: Double
    public let lastPrice: Double
    public let spreadBps: Double
    public let listingAgeDays: Double?

    enum CodingKeys: String, CodingKey {
        case symbol
        case baseAsset = "base_asset"
        case quoteAsset = "quote_asset"
        case status
        case quoteVolume = "quote_volume"
        case priceChangePercent = "price_change_percent"
        case fundingRate = "funding_rate"
        case bidPrice = "bid_price"
        case askPrice = "ask_price"
        case lastPrice = "last_price"
        case spreadBps = "spread_bps"
        case listingAgeDays = "listing_age_days"
    }
}

public struct ChiBao: Codable, Equatable {
    public let atr: Double?
    public let rsi: Double?
    public let adx: Double?
    public let ema20: Double?
    public let ema50: Double?
    public let ema200: Double?
    public let macdHistogram: Double?
    public let vwap: Double?

    enum CodingKeys: String, CodingKey {
        case atr
        case rsi
        case adx
        case ema20
        case ema50
        case ema200
        case macdHistogram = "macd_histogram"
        case vwap
    }
}

public struct TinHieuQuet: Codable, Identifiable, Equatable {
    public var id: String { "\(symbol)-\(timeframe)-\(scannedAt)" }
    public let symbol: String
    public let timeframe: String
    public let regime: String
    public let longScore: Int
    public let shortScore: Int
    public let action: String
    public let strategy: String?
    public let price: Double
    public let priceChangePercent: Double
    public let quoteVolume: Double
    public let fundingRate: Double
    public let stopLoss: Double?
    public let takeProfits: [Double]
    public let riskReward: Double?
    public let indicators: ChiBao
    public let reasons: [String]
    public let scannedAt: String

    enum CodingKeys: String, CodingKey {
        case symbol
        case timeframe
        case regime
        case longScore = "long_score"
        case shortScore = "short_score"
        case action
        case strategy
        case price
        case priceChangePercent = "price_change_percent"
        case quoteVolume = "quote_volume"
        case fundingRate = "funding_rate"
        case stopLoss = "stop_loss"
        case takeProfits = "take_profits"
        case riskReward = "risk_reward"
        case indicators
        case reasons
        case scannedAt = "scanned_at"
    }
}

public struct ViThe: Codable, Identifiable, Equatable {
    public let id: String
    public let symbol: String
    public let side: String
    public let status: String
    public let quantity: Double
    public let remainingQuantity: Double
    public let entryPrice: Double
    public let stopLoss: Double
    public let takeProfits: [Double]
    public let realizedPnl: Double
    public let feesPaid: Double
    public let fundingPaid: Double
    public let breakEvenActive: Bool
    public let trailingStopActive: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case symbol
        case side
        case status
        case quantity
        case remainingQuantity = "remaining_quantity"
        case entryPrice = "entry_price"
        case stopLoss = "stop_loss"
        case takeProfits = "take_profits"
        case realizedPnl = "realized_pnl"
        case feesPaid = "fees_paid"
        case fundingPaid = "funding_paid"
        case breakEvenActive = "break_even_active"
        case trailingStopActive = "trailing_stop_active"
    }
}

public struct LenhDaChot: Codable, Identifiable, Equatable {
    public let id: String
    public let symbol: String
    public let side: String
    public let entryPrice: Double
    public let exitPrice: Double
    public let quantity: Double
    public let grossPnl: Double
    public let fee: Double
    public let slippage: Double
    public let funding: Double
    public let netPnl: Double
    public let reason: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case symbol
        case side
        case entryPrice = "entry_price"
        case exitPrice = "exit_price"
        case quantity
        case grossPnl = "gross_pnl"
        case fee
        case slippage
        case funding
        case netPnl = "net_pnl"
        case reason
        case createdAt = "created_at"
    }
}

public struct HieuSuat: Codable, Equatable {
    public let balance: Double
    public let equity: Double
    public let realizedPnl: Double
    public let unrealizedPnl: Double
    public let feesPaid: Double
    public let fundingPaid: Double
    public let winRate: Double
    public let totalTrades: Int
    public let openPositions: Int
    public let profitFactor: Double
    public let maxDrawdown: Double
    public let sharpe: Double
    public let sortino: Double
    public let expectancy: Double

    enum CodingKeys: String, CodingKey {
        case balance
        case equity
        case realizedPnl = "realized_pnl"
        case unrealizedPnl = "unrealized_pnl"
        case feesPaid = "fees_paid"
        case fundingPaid = "funding_paid"
        case winRate = "win_rate"
        case totalTrades = "total_trades"
        case openPositions = "open_positions"
        case profitFactor = "profit_factor"
        case maxDrawdown = "max_drawdown"
        case sharpe
        case sortino
        case expectancy
    }
}

public struct CaiDatBot: Codable, Equatable {
    public var whitelist: [String]
    public var blacklist: [String]
    public var minQuoteVolume: Double
    public var maxSpreadBps: Double
    public var minListingAgeDays: Int
    public var scanTimeframes: [String]
    public var minScoreToTrade: Int
    public var paperInitialBalance: Double
    public var takerFeeRate: Double
    public var makerFeeRate: Double
    public var slippageBps: Double
    public var fundingRatePer8h: Double
    public var maxLeverage: Int
    public var riskPerTrade: Double
    public var maxRiskPerTrade: Double
    public var maxDailyLoss: Double
    public var maxWeeklyDrawdown: Double
    public var maxOpenPositions: Int
    public var maxPortfolioExposure: Double
    public var maxCorrelatedPositions: Int
    public var maxLossStreak: Int
    public var lossStreakCooldownMinutes: Int
    public var extremeVolatilityAtrFraction: Double
    public var staleDataSeconds: Int
    public var minimumRiskReward: Double

    enum CodingKeys: String, CodingKey {
        case whitelist
        case blacklist
        case minQuoteVolume = "min_quote_volume"
        case maxSpreadBps = "max_spread_bps"
        case minListingAgeDays = "min_listing_age_days"
        case scanTimeframes = "scan_timeframes"
        case minScoreToTrade = "min_score_to_trade"
        case paperInitialBalance = "paper_initial_balance"
        case takerFeeRate = "taker_fee_rate"
        case makerFeeRate = "maker_fee_rate"
        case slippageBps = "slippage_bps"
        case fundingRatePer8h = "funding_rate_per_8h"
        case maxLeverage = "max_leverage"
        case riskPerTrade = "risk_per_trade"
        case maxRiskPerTrade = "max_risk_per_trade"
        case maxDailyLoss = "max_daily_loss"
        case maxWeeklyDrawdown = "max_weekly_drawdown"
        case maxOpenPositions = "max_open_positions"
        case maxPortfolioExposure = "max_portfolio_exposure"
        case maxCorrelatedPositions = "max_correlated_positions"
        case maxLossStreak = "max_loss_streak"
        case lossStreakCooldownMinutes = "loss_streak_cooldown_minutes"
        case extremeVolatilityAtrFraction = "extreme_volatility_atr_fraction"
        case staleDataSeconds = "stale_data_seconds"
        case minimumRiskReward = "minimum_risk_reward"
    }
}

public struct NhatKy: Codable, Identifiable, Equatable {
    public var id: String { "\(createdAt)-\(message)" }
    public let level: String
    public let message: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case level
        case message
        case createdAt = "created_at"
    }
}

public struct DanhSachPhanHoi<T: Codable>: Codable {
    public let items: [T]
}

public struct PhanHoiBot: Codable {
    public let botState: String

    enum CodingKeys: String, CodingKey {
        case botState = "bot_state"
    }
}

public struct GoiRealtime<T: Codable>: Codable {
    public let channel: String
    public let data: T?
    public let items: [T]?
}
