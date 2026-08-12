import pytest

from app.domain.models import (
    ExchangeBalance,
    ExchangeOrder,
    ExchangePosition,
    ExchangeSnapshot,
    OrderPlan,
    Side,
)
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
