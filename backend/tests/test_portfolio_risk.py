from types import SimpleNamespace

import pytest

from app.domain.models import (
    Candle,
    ExchangeBalance,
    ExchangeOrder,
    ExchangePosition,
    ExchangeSnapshot,
    OrderPlan,
    Side,
)
from app.services.auto_trader import AutoTrader
from app.services.portfolio_risk import PortfolioRiskEngine


def limits() -> dict[str, float]:
    return {
        "max_open_risk_fraction": 0.03,
        "max_exposure_fraction": 0.50,
        "max_symbol_exposure_fraction": 0.20,
        "max_directional_exposure_fraction": 0.40,
        "max_symbol_open_risk_fraction": 0.015,
    }


def stop(symbol: str, side: str, price: float, order_id: int = 1) -> ExchangeOrder:
    return ExchangeOrder(
        symbol=symbol,
        order_id=order_id,
        client_order_id=f"sl-{order_id}",
        side=side,
        order_type="STOP_MARKET",
        status="NEW",
        quantity=1,
        stop_price=price,
    )


def test_accounts_long_short_and_current_partial_quantity():
    exchange = ExchangeSnapshot(
        balance=ExchangeBalance(balance=1000, margin_balance=1000),
        positions=[
            ExchangePosition(
                symbol="BTCUSDT", side="LONG", quantity=0.5, entry_price=100, mark_price=110
            ),
            ExchangePosition(
                symbol="ETHUSDT", side="SHORT", quantity=2, entry_price=50, mark_price=45
            ),
        ],
        orders=[stop("BTCUSDT", "SELL", 95), stop("ETHUSDT", "BUY", 55, 2)],
    )
    result = PortfolioRiskEngine().snapshot(exchange, **limits())
    assert result.gross_exposure == 145
    assert result.net_exposure == -35
    assert result.open_risk == 12.5
    assert result.positions[0].quantity == 0.5
    assert not result.would_reject_new_entries


def test_missing_duplicate_and_wrong_side_stops_fail_closed():
    engine = PortfolioRiskEngine()
    base = {
        "balance": ExchangeBalance(balance=1000),
        "positions": [
            ExchangePosition(
                symbol="BTCUSDT", side="LONG", quantity=1, entry_price=100, mark_price=100
            )
        ],
    }
    missing = engine.snapshot(ExchangeSnapshot(**base), **limits())
    wrong = engine.snapshot(
        ExchangeSnapshot(**base, orders=[stop("BTCUSDT", "SELL", 105)]), **limits()
    )
    duplicate = engine.snapshot(
        ExchangeSnapshot(
            **base, orders=[stop("BTCUSDT", "SELL", 95), stop("BTCUSDT", "SELL", 94, 2)]
        ),
        **limits(),
    )
    assert all(item.would_reject_new_entries for item in (missing, wrong, duplicate))
    assert "nhiều Stop Loss" in duplicate.reasons[0]


def test_symbol_direction_and_boundary_concentration_are_deterministic():
    exchange = ExchangeSnapshot(
        balance=ExchangeBalance(balance=1000),
        positions=[
            ExchangePosition(
                symbol="BTCUSDT", side="LONG", quantity=2.01, entry_price=100, mark_price=100
            )
        ],
        orders=[stop("BTCUSDT", "SELL", 95)],
    )
    result = PortfolioRiskEngine().snapshot(exchange, **limits())
    assert "BTCUSDT vượt giới hạn tập trung theo symbol" in result.reasons
    assert result.positions[0].notional_fraction == pytest.approx(0.201)
    boundary = exchange.model_copy(deep=True)
    boundary.positions[0].quantity = 2
    exact = PortfolioRiskEngine().snapshot(boundary, **limits())
    assert "BTCUSDT vượt giới hạn tập trung theo symbol" not in exact.reasons


def test_pretrade_audit_is_shadow_only_and_has_stable_fingerprint():
    exchange = ExchangeSnapshot(balance=ExchangeBalance(balance=1000))
    plan = OrderPlan(
        client_order_id="candidate",
        symbol="BTCUSDT",
        side=Side.LONG,
        quantity=3,
        entry_price=100,
        stop_loss=95,
        leverage=5,
        take_profits=[110],
    )
    first = PortfolioRiskEngine().evaluate_plan(exchange, plan, **limits())
    second = PortfolioRiskEngine().evaluate_plan(exchange, plan, **limits())
    assert first.decision == "WOULD_REJECT"
    assert first.before.enforcement_enabled is False
    assert first.after and first.after.enforcement_enabled is False
    assert first.fingerprint == second.fingerprint
    assert "BTCUSDT vượt giới hạn tập trung theo symbol" in first.reasons


def test_portfolio_enforcement_is_opt_in_and_fail_closed():
    audit = SimpleNamespace(decision="WOULD_REJECT", reasons=["Vượt gross exposure"])
    shadow = AutoTrader(SimpleNamespace(portfolio_risk_enforcement_enabled=False))
    enforced = AutoTrader(SimpleNamespace(portfolio_risk_enforcement_enabled=True))

    assert shadow._portfolio_risk_rejection(audit) is None
    assert enforced._portfolio_risk_rejection(audit) == "Vượt gross exposure"
    assert (
        enforced._portfolio_risk_rejection(SimpleNamespace(decision="WOULD_REJECT", reasons=[]))
        == "Portfolio risk từ chối entry mới"
    )
    assert (
        enforced._portfolio_risk_rejection(SimpleNamespace(decision="WOULD_ALLOW", reasons=[]))
        is None
    )


def test_snapshot_fingerprint_ignores_price_noise_but_tracks_protection_changes():
    engine = PortfolioRiskEngine()
    exchange = ExchangeSnapshot(
        balance=ExchangeBalance(balance=1000, margin_balance=1000),
        positions=[
            ExchangePosition(
                symbol="BTCUSDT", side="LONG", quantity=1, entry_price=100, mark_price=101
            )
        ],
        orders=[stop("BTCUSDT", "SELL", 95)],
    )
    first = engine.audit_snapshot(exchange, **limits())
    noisy = exchange.model_copy(deep=True)
    noisy.balance.margin_balance = 1000.5
    noisy.positions[0].mark_price = 101.05
    assert first.fingerprint == engine.audit_snapshot(noisy, **limits()).fingerprint

    changed = exchange.model_copy(deep=True)
    changed.orders[0].stop_price = 96
    assert first.fingerprint != engine.audit_snapshot(changed, **limits()).fingerprint


def candles(prices: list[float], *, shift: int = 0) -> list[Candle]:
    return [
        Candle(
            open_time=shift + index * 60_000,
            close_time=shift + (index + 1) * 60_000 - 1,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1,
            quote_volume=price,
        )
        for index, price in enumerate(prices)
    ]


def test_closed_candle_correlation_is_deterministic_and_builds_clusters():
    exchange = ExchangeSnapshot(
        balance=ExchangeBalance(balance=10_000),
        positions=[
            ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=1, entry_price=100),
            ExchangePosition(symbol="ETHUSDT", side="LONG", quantity=2, entry_price=50),
        ],
        orders=[stop("BTCUSDT", "SELL", 99), stop("ETHUSDT", "SELL", 49, 2)],
    )
    prices = [100 + index + (index % 3) for index in range(31)]
    evidence = {"BTCUSDT": candles(prices), "ETHUSDT": candles([p * 2 for p in prices])}
    first = (
        PortfolioRiskEngine()
        .snapshot(
            exchange,
            **limits(),
            correlation_candles=evidence,
            correlation_lookback=30,
            correlation_closed_at=2_000_000,
        )
        .correlation
    )
    second = (
        PortfolioRiskEngine()
        .snapshot(
            exchange,
            **limits(),
            correlation_candles=evidence,
            correlation_lookback=30,
            correlation_closed_at=2_000_000,
        )
        .correlation
    )
    assert first == second
    assert first.status == "COMPLETE"
    assert first.pairs[0].correlation == pytest.approx(1)
    assert first.clusters[0].symbols == ["BTCUSDT", "ETHUSDT"]
    assert first.adjusted_exposure > 200


def test_correlation_requires_complete_aligned_coverage_and_fails_safe_in_vietnamese():
    exchange = ExchangeSnapshot(
        balance=ExchangeBalance(balance=1000),
        positions=[
            ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=1, entry_price=100),
            ExchangePosition(symbol="ETHUSDT", side="SHORT", quantity=1, entry_price=100),
        ],
        orders=[stop("BTCUSDT", "SELL", 99), stop("ETHUSDT", "BUY", 101, 2)],
    )
    prices = [100 + index for index in range(31)]
    result = PortfolioRiskEngine().snapshot(
        exchange,
        **limits(),
        correlation_candles={
            "BTCUSDT": candles(prices),
            "ETHUSDT": candles(prices, shift=60_000),
        },
        correlation_lookback=30,
        correlation_closed_at=2_000_000,
    )
    assert result.correlation.status == "INCOMPLETE"
    assert result.correlation.missing_symbols == ["ETHUSDT"]
    assert "Không đủ dữ liệu nến đã đóng" in result.reasons[-1]
    assert result.would_reject_new_entries is True


def test_loss_streak_groups_partial_close_fills_by_lifecycle():
    from datetime import UTC, datetime, timedelta

    from app.domain.models import TradeRecord

    closed_at = datetime(2026, 8, 15, tzinfo=UTC)

    def trade(identifier: str, pnl: float, at: datetime) -> TradeRecord:
        return TradeRecord(
            id=identifier,
            symbol="BTCUSDT",
            side=Side.SHORT,
            entry_price=100,
            exit_price=101,
            quantity=1,
            gross_pnl=pnl,
            fee=0,
            slippage=0,
            net_pnl=pnl,
            reason="TP" if pnl > 0 else "SL",
            created_at=at,
        )

    # Two partial fills at one timestamp are one winning lifecycle, followed by
    # two independent losing lifecycles. Fill-counting would incorrectly return 3.
    trades = [
        trade("win-1", 2, closed_at),
        trade("win-2", 1, closed_at),
        trade("loss-1", -1, closed_at + timedelta(minutes=1)),
        trade("loss-2a", -1, closed_at + timedelta(minutes=2)),
        trade("loss-2b", -1, closed_at + timedelta(minutes=2)),
    ]
    state = SimpleNamespace(
        portfolio_risk_enforcement_enabled=True,
        execution=SimpleNamespace(trades=trades),
    )

    assert AutoTrader(state)._loss_streak() == 2


def test_high_risk_symbol_is_watchlisted_not_hard_blacklisted():
    from app.domain.models import MarketRegime, Timeframe

    state = SimpleNamespace(
        portfolio_risk_enforcement_enabled=True,
        bot_settings=SimpleNamespace(min_score_to_trade=85),
        settings=SimpleNamespace(
            scanner_high_risk_symbols="AVAXUSDT,ADAUSDT",
            scanner_high_risk_min_score=90,
        ),
    )
    trader = AutoTrader(state)

    base = {
        "symbol": "AVAXUSDT",
        "short_score": 0,
        "timeframe": Timeframe.H1,
        "risk_reward": 2.2,
        "regime": MarketRegime.TRENDING_UP,
        "reasons": [],
    }
    accepted, reason = trader._candidate_has_enough_confirmation(
        SimpleNamespace(**base, long_score=89)
    )
    assert accepted is False
    assert "90" in reason

    accepted, reason = trader._candidate_has_enough_confirmation(
        SimpleNamespace(**base, long_score=92)
    )
    assert accepted is True
    assert reason == "Trend rõ"


@pytest.mark.asyncio
async def test_risk_endpoint_reports_runtime_enforcement(monkeypatch):
    from app.api import routes
    from app.domain.models import ExchangeSnapshot

    snapshot = ExchangeSnapshot()
    monkeypatch.setattr(routes.state, "portfolio_risk_enforcement_enabled", True)
    monkeypatch.setattr(routes.state.demo_exchange, "snapshot_cache", snapshot)
    monkeypatch.setattr(routes.state.storage, "portfolio_risk_audits", lambda _limit: _async([]))
    monkeypatch.setattr(routes.state.storage, "portfolio_risk_audit_summary", lambda: _async({}))
    monkeypatch.setattr(routes, "status", lambda: _async({"risk": {}}))

    result = await routes.risk()

    assert result["portfolio"]["mode"] == "ENFORCED"
    assert result["portfolio"]["enforcement_enabled"] is True


def _async(value):
    async def result():
        return value

    return result()
