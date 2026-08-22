from app.domain.models import Candle
from app.services.indicators import calculate_indicators, ema, macd, rsi


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


def test_macd_matches_prefix_reference_calculation():
    values = [100 + index * 0.2 + (index % 7) * 0.13 for index in range(120)]
    line = []
    for end in range(26, len(values) + 1):
        fast = ema(values[:end], 12)
        slow = ema(values[:end], 26)
        line.append(fast - slow)
    expected_signal = ema(line, 9)
    expected_latest = line[-1]

    latest, signal, histogram = macd(values)

    assert latest == expected_latest
    assert signal == expected_signal
    assert histogram == expected_latest - expected_signal


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
