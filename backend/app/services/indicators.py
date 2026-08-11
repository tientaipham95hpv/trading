from itertools import pairwise

from app.domain.models import Candle, IndicatorSnapshot


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (value - current) * multiplier + current
    return current


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in pairwise(values):
        change = current - previous
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) < 35:
        return None, None, None
    macd_line: list[float] = []
    for index in range(26, len(values) + 1):
        partial = values[:index]
        fast = ema(partial, 12)
        slow = ema(partial, 26)
        if fast is not None and slow is not None:
            macd_line.append(fast - slow)
    signal = ema(macd_line, 9)
    latest = macd_line[-1] if macd_line else None
    histogram = latest - signal if latest is not None and signal is not None else None
    return latest, signal, histogram


def atr(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    true_ranges: list[float] = []
    for previous, current in pairwise(candles):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(true_ranges[-period:]) / period


def bollinger(values: list[float], period: int = 20) -> tuple[float | None, float | None, float | None]:
    mid = sma(values, period)
    if mid is None:
        return None, None, None
    window = values[-period:]
    variance = sum((value - mid) ** 2 for value in window) / period
    std_dev = variance**0.5
    return mid, mid + 2 * std_dev, mid - 2 * std_dev


def vwap(candles: list[Candle]) -> float | None:
    total_volume = sum(candle.volume for candle in candles)
    if total_volume <= 0:
        return None
    total = sum(((candle.high + candle.low + candle.close) / 3) * candle.volume for candle in candles)
    return total / total_volume


def adx(candles: list[Candle], period: int = 14) -> float | None:
    if len(candles) <= period + 1:
        return None
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    true_ranges: list[float] = []
    for previous, current in pairwise(candles):
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    tr_sum = sum(true_ranges[-period:])
    if tr_sum == 0:
        return 0.0
    plus_di = 100 * (sum(plus_dm[-period:]) / tr_sum)
    minus_di = 100 * (sum(minus_dm[-period:]) / tr_sum)
    denominator = plus_di + minus_di
    if denominator == 0:
        return 0.0
    return 100 * abs(plus_di - minus_di) / denominator


def calculate_indicators(candles: list[Candle]) -> IndicatorSnapshot:
    closes = [candle.close for candle in candles]
    volumes = [candle.volume for candle in candles]
    macd_line, macd_signal, macd_histogram = macd(closes)
    boll_mid, boll_upper, boll_lower = bollinger(closes)
    return IndicatorSnapshot(
        ema20=ema(closes, 20),
        ema50=ema(closes, 50),
        ema200=ema(closes, 200),
        rsi=rsi(closes),
        macd=macd_line,
        macd_signal=macd_signal,
        macd_histogram=macd_histogram,
        atr=atr(candles),
        bollinger_mid=boll_mid,
        bollinger_upper=boll_upper,
        bollinger_lower=boll_lower,
        vwap=vwap(candles[-80:]),
        adx=adx(candles),
        volume_sma20=sma(volumes, 20),
    )
