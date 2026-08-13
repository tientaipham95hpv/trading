import Foundation
import Testing
@testable import TradingControl

@Test func packageLoads() async throws {
    _ = TradingControlView()
}

@Test func trangThaiBotDecodesSnakeCaseBackendPayload() async throws {
    let data = """
    {
      "mode": "DEMO",
      "live_enabled": false,
      "bot_state": "PAUSED",
      "emergency_stop": false,
      "safe_mode": false,
      "safe_mode_reason": null,
      "exchange": {
        "mode": "DEMO",
        "connection": "DISCONNECTED",
        "safe_mode": false,
        "safe_mode_reason": null,
        "balance": { "asset": "USDT", "balance": 0, "available": 0, "margin_balance": 0, "unrealized_pnl": 0 },
        "orders": [],
        "positions": [],
        "last_reconciled_at": null,
        "last_user_stream_at": null
      },
      "risk": {
        "max_leverage": 5,
        "risk_per_trade": 0.005,
        "max_risk_per_trade": 0.01,
        "max_total_open_risk": 0.03,
        "max_margin_per_trade": 0.10,
        "max_total_margin": 0.30,
        "max_daily_loss": 0.04,
        "max_weekly_drawdown": 0.08,
        "max_open_positions": 4,
        "max_portfolio_exposure": 0.30,
        "max_correlated_positions": 2,
        "max_loss_streak": 3,
        "minimum_risk_reward": 1.8
      },
      "live_readiness": {
        "live_enabled": false,
        "all_tests_pass": false,
        "demo_stable": false,
        "sl_protection_pass": false,
        "reconnect_pass": false,
        "reconciliation_pass": false,
        "duplicate_order_tests_pass": false,
        "allowed": false,
        "blockers": []
      },
      "auto_trader": null
    }
    """.data(using: .utf8)!

    let status = try JSONDecoder().decode(TrangThaiBot.self, from: data)

    #expect(status.mode == "DEMO")
    #expect(status.liveEnabled == false)
    #expect(status.botState == "PAUSED")
    #expect(status.exchange.connection == "DISCONNECTED")
    #expect(status.risk.maxOpenPositions == 4)
}

@Test func scannerRealtimeEnvelopeDecodesItems() async throws {
    let data = """
    {
      "channel": "scanner",
      "items": [
        {
          "symbol": "BTCUSDT",
          "timeframe": "15m",
          "regime": "TRENDING_UP",
          "long_score": 82,
          "short_score": 20,
          "action": "LONG",
          "strategy": "Trend Pullback",
          "price": 65000,
          "price_change_percent": 1.2,
          "quote_volume": 1000000000,
          "funding_rate": 0.0001,
          "stop_loss": 64000,
          "take_profits": [66000, 67000],
          "risk_reward": 2.1,
          "indicators": { "atr": 250, "rsi": 58, "adx": 24, "ema20": 64900, "ema50": 64500, "ema200": 62000, "macd_histogram": 12, "vwap": 64800 },
          "reasons": ["trend"],
          "scanned_at": "2026-08-11T05:00:00Z"
        }
      ]
    }
    """.data(using: .utf8)!

    let envelope = try JSONDecoder().decode(GoiRealtime<TinHieuQuet>.self, from: data)

    #expect(envelope.channel == "scanner")
    #expect(envelope.items?.first?.symbol == "BTCUSDT")
    #expect(envelope.items?.first?.longScore == 82)
}

@Test func settingsDecodesCurrentBackendBalanceKey() async throws {
    let data = """
    {
      "whitelist": [], "blacklist": [], "min_quote_volume": 1,
      "max_spread_bps": 1, "min_listing_age_days": 1,
      "scan_timeframes": ["15m"], "min_score_to_trade": 80,
      "simulation_initial_balance": 5000, "taker_fee_rate": 0.0005,
      "maker_fee_rate": 0.0002, "slippage_bps": 1,
      "funding_rate_per_8h": 0, "max_leverage": 3,
      "risk_per_trade": 0.0025, "max_risk_per_trade": 0.005,
      "max_total_open_risk": 0.01, "max_margin_per_trade": 0.1,
      "max_total_margin": 0.15, "max_daily_loss": 0.02,
      "max_weekly_drawdown": 0.05, "max_open_positions": 1,
      "max_portfolio_exposure": 0.3, "max_correlated_positions": 1,
      "max_loss_streak": 3, "loss_streak_cooldown_minutes": 60,
      "extreme_volatility_atr_fraction": 0.05, "stale_data_seconds": 90,
      "minimum_risk_reward": 2
    }
    """.data(using: .utf8)!

    let settings = try JSONDecoder().decode(CaiDatBot.self, from: data)
    #expect(settings.paperInitialBalance == 5000)
}
