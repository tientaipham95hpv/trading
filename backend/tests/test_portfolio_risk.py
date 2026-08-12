from app.domain.models import ExchangeBalance, ExchangeOrder, ExchangePosition, ExchangeSnapshot
from app.services.portfolio_risk import PortfolioRiskEngine


def test_portfolio_risk_accounts_long_short_and_verified_stops():
    exchange = ExchangeSnapshot(
        balance=ExchangeBalance(balance=1000, margin_balance=1000),
        positions=[
            ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=1, entry_price=100, mark_price=110),
            ExchangePosition(symbol="ETHUSDT", side="SHORT", quantity=2, entry_price=50, mark_price=45),
        ],
        orders=[
            ExchangeOrder(symbol="BTCUSDT", order_id=1, client_order_id="sl", side="SELL", order_type="STOP_MARKET", status="NEW", quantity=1, stop_price=95),
            ExchangeOrder(symbol="ETHUSDT", order_id=2, client_order_id="sl", side="BUY", order_type="STOP_MARKET", status="NEW", quantity=2, stop_price=55),
        ],
    )
    result = PortfolioRiskEngine().snapshot(exchange, max_open_risk_fraction=.03, max_exposure_fraction=.30)
    assert result.gross_exposure == 200
    assert result.net_exposure == 20
    assert result.open_risk == 15
    assert result.open_risk_remaining == 15
    assert not result.would_reject_new_entries


def test_portfolio_risk_shadow_fails_closed_when_stop_missing():
    exchange = ExchangeSnapshot(balance=ExchangeBalance(balance=1000), positions=[ExchangePosition(symbol="BTCUSDT", side="LONG", quantity=1, entry_price=100, mark_price=100)])
    result = PortfolioRiskEngine().snapshot(exchange, max_open_risk_fraction=.03, max_exposure_fraction=.30)
    assert result.would_reject_new_entries
    assert result.enforcement_enabled is False
    assert "chưa có Stop Loss hợp lệ" in result.reasons[0]
