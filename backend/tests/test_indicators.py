from app.domain.models import Candle
from app.services.indicators import calculate_indicators, ema, rsi


def candles() -> list[Candle]:
    return [
        Candle(
            open_time=index,
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=1000 + index,
            close_time=index + 1,
        )
        for index in range(240)
    ]


def test_ema_and_rsi_are_calculated():
    values = [float(value) for value in range(1, 60)]

    assert ema(values, 20) is not None
    assert rsi(values) == 100.0


def test_indicator_snapshot_contains_required_phase_1_indicators():
    snapshot = calculate_indicators(candles())

    assert snapshot.ema20 is not None
    assert snapshot.ema50 is not None
    assert snapshot.ema200 is not None
    assert snapshot.macd is not None
    assert snapshot.atr is not None
    assert snapshot.bollinger_upper is not None
    assert snapshot.vwap is not None
    assert snapshot.adx is not None
    assert snapshot.volume_sma20 is not None
