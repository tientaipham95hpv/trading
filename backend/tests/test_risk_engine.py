from app.domain.models import EmergencyStopState, Side, StrategySignal
from app.services.risk_engine import RiskEngine


def make_signal(**overrides):
    data = {
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "confidence": 0.7,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "take_profits": [105.0, 109.0, 110.0],
        "leverage": 5,
        "risk_fraction": 0.005,
    }
    data.update(overrides)
    return StrategySignal(**data)


def test_risk_engine_accepts_valid_signal():
    decision = RiskEngine().evaluate(
        make_signal(),
        open_positions=0,
        daily_loss_fraction=0,
        emergency_stop=EmergencyStopState(active=False),
    )

    assert decision.accepted is True
    assert decision.quantity == 10
    assert decision.risk_reward == 2


def test_risk_engine_rejects_excess_leverage():
    decision = RiskEngine().evaluate(
        make_signal(leverage=6),
        open_positions=0,
        daily_loss_fraction=0,
        emergency_stop=EmergencyStopState(active=False),
    )

    assert decision.accepted is False
    assert decision.reason == "Đòn bẩy vượt giới hạn tối đa"


def test_risk_engine_rejects_emergency_stop():
    decision = RiskEngine().evaluate(
        make_signal(),
        open_positions=0,
        daily_loss_fraction=0,
        emergency_stop=EmergencyStopState(active=True, reason="manual"),
    )

    assert decision.accepted is False
    assert decision.reason == "Dừng khẩn cấp đang bật"


def test_risk_engine_rejects_rr_below_minimum():
    decision = RiskEngine().evaluate(
        make_signal(take_profit=102.0),
        open_positions=0,
        daily_loss_fraction=0,
        emergency_stop=EmergencyStopState(active=False),
    )

    assert decision.accepted is False
    assert decision.reason == "RR nhỏ hơn 1.8"


def test_position_sizing_respects_half_percent_risk():
    decision = RiskEngine().evaluate(
        make_signal(entry_price=100.0, stop_loss=90.0, take_profit=120.0),
        open_positions=0,
        daily_loss_fraction=0,
        emergency_stop=EmergencyStopState(active=False),
        account_equity=20_000,
    )

    assert decision.accepted is True
    assert decision.risk_amount == 100
    assert decision.quantity == 10
