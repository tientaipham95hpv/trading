# BTC-only SHORT-only V4 research preregistration

**Frozen before fetching or inspecting this experiment's evaluation candles:** 2026-08-22 UTC.
**Status:** advisory-only, offline research; no runtime/config/order integration.

## Hypothesis

The prior frozen OOS ledger showed weaker LONG performance and relatively less-negative SHORT performance. This is a **new hypothesis**, not evidence of efficacy: restricting the unchanged V3 trend-pullback engine to `BTCUSDT` and `SHORT` entries may improve out-of-sample expectancy. It must be disproved or supported on fresh disjoint data.

## Fixed rule

- Universe: `BTCUSDT` only.
- Side: `SHORT` only; every LONG signal is ignored.
- Signal, four V3 configuration grid, next-bar execution, exits, fees, slippage, funding proxy, sizing and risk: unchanged from `reports/strategy_v3_trend_pullback_preregistration.md`.
- No new filters, no stop widening, no exit change, no risk increase, no parameter added.

## Data provenance and disjointness

The prior locked ledgers are `reports/oos_attribution.json` and `reports/strategy_v3_trend_pullback.json`. The experiment must use only completed Binance USD-M BTCUSDT candles whose `open_time` is **strictly after** the maximum timestamp represented by every prior locked trade (`signal_time`, `entry_time`, `exit_time`). The script records both bounds and a data fingerprint. Any overlap, incomplete candle, fetch error, or provenance failure invalidates the experiment.

## Splits and selection

Use the first sufficiently large newly fetched BTCUSDT candle window after the locked boundary. Warm up 205 candles, then split the remaining data into three chronological blocks. For each fold: expanding train, the immediately preceding equal-sized validation block, then the untouched OOS block. Select one of the unchanged V3 configurations only from validation under the original V3 objective and tie-breaks. Lock selection before simulating its OOS block.

## Promotion gate

No candidate may be integrated unless aggregate untouched OOS meets **all** of:

1. at least 30 trades;
2. profit factor > 1.20;
3. positive net expectancy;
4. positive average net R;
5. at least 2 of 3 chronological OOS folds profitable.

Failure of any gate is `REJECT`. This result cannot alter the bot, DEMO state, risk, entries, exits, or configuration. A passing report is only permission to consider writing a separate candidate for review.

## Determinism

The report records dataset fingerprint, candle bounds, selected configuration per fold, OOS metrics, costs, causality, and disjointness. It is advisory/read-only.
