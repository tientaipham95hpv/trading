# Strategy V3 — Trend Pullback preregistration

**Frozen before fetching or inspecting the new evaluation candles:** 2026-08-15 UTC.
**Status:** independent, advisory/read-only research; no runtime/config/order integration.

## Existing-solutions preflight and decision

Trusted causal backtest patterns are event-driven, next-bar execution, rolling/expanding chronological validation, immutable data fingerprints, and explicit costs (patterns commonly supported by mature engines such as backtrader/vectorbt). The repository already has candle models, Binance historical pagination, indicators, cost-aware simulation, and chronological fold patterns. **Decision:** use a small isolated stdlib Python engine and the existing `Candle` model/fetch pattern; add no dependency. This minimizes integration and semantic risk. No prior strategy signal/threshold or the 133 locked OOS trades is used for selection.

## Thesis and causal signal

In an established directional trend, a shallow pullback toward EMA20 followed by closed-candle momentum re-acceleration may have positive expectancy. LONG and SHORT are symmetric and reported separately; both remain enabled because this thesis does not preregister a side preference.

At signal candle `t`, only candles with `close_time <= close_time[t]` are used. Entry is at next candle `t+1` open, including adverse slippage. Indicators are recursively computed from current/past closes only:

* Trend: EMA20 > EMA50 (LONG; inverse SHORT), EMA50 > EMA200 (inverse SHORT), and normalized 5-candle EMA20 slope >= `slope_min` (<= negative for SHORT).
* Pullback: during signal candle or either of the previous two closed candles, price touches an EMA20 band of `pullback_atr * ATR14`; it must not close through EMA50 against the trend.
* Re-acceleration on `t`: LONG close > prior high and close > open; SHORT close < prior low and close < open.
* One position per dataset; no overlapping trades. Warm-up 205 candles.

## Fixed candidate grid (maximum four)

Only these configurations may be selected, on train→validation evidence only:

| ID | slope_min | pullback_atr | stop_atr | target_R | max_hold |
|---|---:|---:|---:|---:|---:|
| A | 0.0010 | 0.50 | 1.5 | 2.0 | 24 bars |
| B | 0.0010 | 0.75 | 1.5 | 2.0 | 24 bars |
| C | 0.0015 | 0.50 | 2.0 | 2.0 | 30 bars |
| D | 0.0015 | 0.75 | 2.0 | 2.5 | 30 bars |

Slope is `(EMA20[t]-EMA20[t-5]) / (5*ATR14[t])`.

## Entry, exit, sizing, costs

* Entry: next open; LONG pays +2 bps slippage, SHORT receives -2 bps.
* Initial stop: `stop_atr * ATR14(signal)` from slipped entry. Target: `target_R * initial stop distance`.
* If stop and target occur within one candle, stop executes first (conservative). Otherwise exit at first touched stop/target; time exit at close after max_hold bars, with adverse 2 bps exit slippage.
* Fixed fractional sizing: risk 1% of current equity, initial capital 10,000 USDT; no leverage cap needed for normalized R, but quantity is risk/stop distance.
* Taker fee: 5 bps each entry and exit.
* Funding proxy: adverse 1 bp of notional per each eight hours held (charged pro-rata by elapsed hours, including at least actual fraction). This deliberately does not assume beneficial funding.
* Net PnL and R include fees, slippage, and funding. No compounding across datasets; each dataset starts at 10,000.

## New data, splits, selection, locking

Datasets: BTCUSDT, ETHUSDT, SOLUSDT × 1h, 4h Binance USD-M closed klines. Fetch an older window ending strictly before the earliest timestamp represented by the prior locked OOS trade ledger. Require every new candle `close_time < old_locked_min_timestamp`; otherwise stop and report blocker. Store only data metadata/fingerprints in reports (cache may remain outside repo).

Each dataset is partitioned into three chronological folds, each with expanding train, immediately following validation, then untouched OOS. Use the final 60% after warm-up as three equal fold blocks; for each fold, validation is the immediately preceding block of equal size and train is all earlier data. A configuration is selected independently per fold using validation only, then fingerprint-locked before simulating that fold's OOS. OOS is never used to revise the grid or select again.

Selection objective: among candidates with >=5 validation trades, maximize `average net R - 0.25 * max_drawdown_R`; ties resolve lexicographically by config ID. If none has 5 validation trades, select the config with most trades, then the objective, then ID. This fallback is marked low-evidence.

## Invalidation and strict promotion

No second tuning round. **PROMOTE candidate only if aggregate untouched OOS has:** >=30 trades, PF >1.2, positive net expectancy, positive average net R, at least 2/3 chronological aggregate folds profitable, and no single symbol contributes >70% of positive aggregate PnL or all other symbols together are non-positive. Otherwise REJECT.

Also report per dataset, side, fold, max drawdown, maximum loss streak, selected-config stability, timestamps/fingerprints, disjointness, and determinism. Any lookahead, overlap, incomplete candle, data-fetch, or provenance failure invalidates the experiment.
