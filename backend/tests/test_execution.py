import pytest

from app.domain.models import BotSettings, OrderPlan, Side
from app.services.execution import DuplicateOrderError, ExecutionService


def long_plan(**overrides):
    data = {
        "client_order_id": "sim-BTCUSDT-1",
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "quantity": 1.0,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profits": [105.0, 110.0, 115.0],
        "leverage": 2,
    }
    data.update(overrides)
    return OrderPlan(**data)


async def test_execution_blocks_duplicate_client_order_ids():
    service = ExecutionService()
    plan = long_plan()

    await service.submit_order_plan(plan)
    with pytest.raises(DuplicateOrderError):
        await service.submit_order_plan(plan)


async def test_long_hits_partial_tp_break_even_trailing_and_pnl():
    service = ExecutionService(BotSettings(slippage_bps=0, taker_fee_rate=0, funding_rate_per_8h=0))
    await service.submit_order_plan(long_plan())

    trades = service.update_market_price("BTCUSDT", 105.0)
    assert trades[0].reason == "TP"
    assert service.open_positions()[0].break_even_active is True
    assert service.open_positions()[0].remaining_quantity == pytest.approx(0.6)

    service.update_market_price("BTCUSDT", 110.0)
    position = service.open_positions()[0]
    assert position.trailing_stop_active is True
    assert position.stop_loss > position.entry_price

    service.update_market_price("BTCUSDT", 115.0)
    assert service.performance().realized_pnl > 0


async def test_short_stop_loss_and_fee_slippage_reduce_pnl():
    service = ExecutionService(BotSettings(slippage_bps=10, taker_fee_rate=0.001, funding_rate_per_8h=0))
    await service.submit_order_plan(
        long_plan(
            client_order_id="sim-ETHUSDT-1",
            symbol="ETHUSDT",
            side=Side.SHORT,
            entry_price=100.0,
            stop_loss=105.0,
            take_profits=[95.0, 92.0, 90.0],
        )
    )

    trades = service.update_market_price("ETHUSDT", 105.0)
    assert trades[0].reason == "SL"
    assert trades[0].net_pnl < trades[0].gross_pnl
    assert service.performance().fees_paid > 0
