from app.domain.models import Candle
from app.services.strategy_v3_trend_pullback import CONFIGS, dataset_fingerprint, simulate


def candles(count=400):
    rows = []
    for i in range(count):
        close = 100 + i * 0.1
        rows.append(
            Candle(
                open_time=i * 3_600_000,
                close_time=(i + 1) * 3_600_000 - 1,
                open=close - 0.02,
                high=close + 0.08,
                low=close - 0.08,
                close=close,
                volume=100,
                quote_volume=10_000,
            )
        )
    return rows


def test_deterministic_and_next_bar_causal():
    rows = candles()
    first = simulate(rows, CONFIGS[0], 205, len(rows))
    second = simulate(rows, CONFIGS[0], 205, len(rows))
    assert first == second
    assert all(row["signal_time"] < row["entry_time"] <= row["exit_time"] for row in first)


def test_future_mutation_does_not_change_prior_results():
    rows = candles()
    cutoff = 330
    before = simulate(rows, CONFIGS[0], 205, cutoff)
    changed = rows[:cutoff] + [
        row.model_copy(update={"close": row.close * 10}) for row in rows[cutoff:]
    ]
    assert simulate(changed, CONFIGS[0], 205, cutoff) == before


def test_dataset_fingerprint_is_deterministic_and_sensitive():
    rows = candles(20)
    assert dataset_fingerprint(rows) == dataset_fingerprint(list(rows))
    changed = rows[:-1] + [rows[-1].model_copy(update={"close": rows[-1].close + 1})]
    assert dataset_fingerprint(rows) != dataset_fingerprint(changed)
