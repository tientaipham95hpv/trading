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
    public let risk: RuiRo

    enum CodingKeys: String, CodingKey {
        case mode
        case liveEnabled = "live_enabled"
        case botState = "bot_state"
        case emergencyStop = "emergency_stop"
        case risk
    }
}

public struct RuiRo: Codable, Equatable {
    public let maxLeverage: Int
    public let riskPerTrade: Double
    public let maxRiskPerTrade: Double
    public let maxDailyLoss: Double
    public let maxOpenPositions: Int
    public let minimumRiskReward: Double

    enum CodingKeys: String, CodingKey {
        case maxLeverage = "max_leverage"
        case riskPerTrade = "risk_per_trade"
        case maxRiskPerTrade = "max_risk_per_trade"
        case maxDailyLoss = "max_daily_loss"
        case maxOpenPositions = "max_open_positions"
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
