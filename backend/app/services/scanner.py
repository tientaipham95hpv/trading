import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from app.domain.models import (
    BotSettings,
    Candle,
    IndicatorSnapshot,
    MarketRegime,
    ScannerResult,
    Side,
    SignalAction,
    StrategySignal,
    SymbolCandidate,
    Timeframe,
)
from app.services.indicators import calculate_indicators


class MarketDataClient(Protocol):
    async def exchange_info(self) -> Mapping[str, Any]:
        ...

    async def ticker_24h(self) -> list[Mapping[str, Any]]:
        ...

    async def book_ticker(self) -> list[Mapping[str, Any]]:
        ...

    async def premium_index(self) -> list[Mapping[str, Any]]:
        ...

    async def klines(self, symbol: str, interval: str, limit: int = 250) -> list[Candle]:
        ...


class FuturesScanner:
    def __init__(self, client: MarketDataClient, settings: BotSettings | None = None) -> None:
        self._client = client
        self.settings = settings or BotSettings()
        self.last_markets: list[SymbolCandidate] = []
        self.last_results: list[ScannerResult] = []

    async def scan_usdm_pairs(self) -> list[SymbolCandidate]:
        payload, tickers, book_tickers, premium_indexes = await asyncio.gather(
            self._client.exchange_info(),
            self._client.ticker_24h(),
            self._client.book_ticker(),
            self._client.premium_index(),
        )
        ticker_by_symbol = {item.get("symbol"): item for item in tickers}
        book_by_symbol = {item.get("symbol"): item for item in book_tickers}
        premium_by_symbol = {item.get("symbol"): item for item in premium_indexes}
        symbols = payload.get("symbols", [])

        candidates: list[SymbolCandidate] = []
        now_ms = datetime.now(UTC).timestamp() * 1000
        for item in symbols:
            if item.get("quoteAsset") != "USDT":
                continue
            if item.get("contractType") != "PERPETUAL":
                continue
            if item.get("status") != "TRADING":
                continue
            symbol = item["symbol"]
            ticker = ticker_by_symbol.get(symbol, {})
            book = book_by_symbol.get(symbol, {})
            premium = premium_by_symbol.get(symbol, {})
            bid = _to_float(book.get("bidPrice"))
            ask = _to_float(book.get("askPrice"))
            last = _to_float(ticker.get("lastPrice"))
            quote_volume = _to_float(ticker.get("quoteVolume"))
            price_change_percent = _to_float(ticker.get("priceChangePercent"))
            funding_rate = _to_float(premium.get("lastFundingRate"))
            mid = (bid + ask) / 2 if bid and ask else last
            spread_bps = ((ask - bid) / mid * 10_000) if mid and ask and bid else 0.0
            onboard_date = item.get("onboardDate")
            listing_age_days = (
                (now_ms - float(onboard_date)) / 86_400_000 if onboard_date else None
            )
            candidate = SymbolCandidate(
                symbol=symbol,
                base_asset=item["baseAsset"],
                quote_asset=item["quoteAsset"],
                contract_type=item["contractType"],
                status=item["status"],
                onboard_date=onboard_date,
                quote_volume=quote_volume,
                price_change_percent=price_change_percent,
                funding_rate=funding_rate,
                bid_price=bid,
                ask_price=ask,
                last_price=last,
                spread_bps=spread_bps,
                listing_age_days=listing_age_days,
            )
            if self._passes_filters(candidate):
                candidates.append(candidate)
        candidates.sort(key=lambda item: item.quote_volume, reverse=True)
        self.last_markets = candidates
        return candidates

    async def scan(
        self,
        *,
        symbols: list[str] | None = None,
        timeframes: list[Timeframe] | None = None,
        limit: int = 30,
    ) -> list[ScannerResult]:
        markets = await self.scan_usdm_pairs()
        if symbols:
            allowed = set(symbols)
            markets = [market for market in markets if market.symbol in allowed]
        frames = timeframes or self.settings.scan_timeframes
        jobs = [
            self._scan_symbol_timeframe(market, timeframe)
            for market in markets[:limit]
            for timeframe in frames
        ]
        results = [result for result in await asyncio.gather(*jobs) if result is not None]
        results.sort(key=lambda result: max(result.long_score, result.short_score), reverse=True)
        self.last_results = results
        return results

    def signal_from_result(self, result: ScannerResult) -> StrategySignal | None:
        if result.action == SignalAction.NO_TRADE or not result.stop_loss:
            return None
        return StrategySignal(
            symbol=result.symbol,
            side=Side(result.action.value),
            confidence=max(result.long_score, result.short_score) / 100,
            entry_price=result.price,
            stop_loss=result.stop_loss,
            take_profit=result.take_profits[-1] if result.take_profits else None,
            take_profits=result.take_profits,
            leverage=max(1, min(self.settings.max_leverage, 10)),
            strategy=result.strategy or "scanner",
            timeframe=result.timeframe,
            metadata={"regime": result.regime.value},
        )

    def _passes_filters(self, candidate: SymbolCandidate) -> bool:
        if self.settings.whitelist and candidate.symbol not in self.settings.whitelist:
            return False
        if candidate.symbol in self.settings.blacklist:
            return False
        if candidate.quote_volume < self.settings.min_quote_volume:
            return False
        if candidate.spread_bps > self.settings.max_spread_bps:
            return False
        return not (
            candidate.listing_age_days is not None
            and candidate.listing_age_days < self.settings.min_listing_age_days
        )

    async def _scan_symbol_timeframe(
        self, market: SymbolCandidate, timeframe: Timeframe
    ) -> ScannerResult | None:
        candles = await self._client.klines(market.symbol, timeframe.value, limit=250)
        if len(candles) < 60:
            return None
        indicators = calculate_indicators(candles)
        regime = detect_regime(candles, indicators)
        long_score, short_score, reasons = score_market(candles, indicators, regime)
        price = candles[-1].close
        action = SignalAction.NO_TRADE
        strategy = None
        stop_loss = None
        take_profits: list[float] = []
        risk_reward = None
        min_score = self.settings.min_score_to_trade
        if long_score >= min_score and long_score > short_score:
            action = SignalAction.LONG
            strategy = "Trend Pullback" if regime == MarketRegime.TRENDING_UP else "Breakout"
            stop_loss, take_profits, risk_reward = build_trade_levels("LONG", price, indicators)
        elif short_score >= min_score and short_score > long_score:
            action = SignalAction.SHORT
            strategy = "Trend Pullback" if regime == MarketRegime.TRENDING_DOWN else "Breakout"
            stop_loss, take_profits, risk_reward = build_trade_levels("SHORT", price, indicators)
        return ScannerResult(
            symbol=market.symbol,
            timeframe=timeframe,
            regime=regime,
            long_score=long_score,
            short_score=short_score,
            action=action,
            strategy=strategy,
            price=price,
            price_change_percent=market.price_change_percent,
            quote_volume=market.quote_volume,
            funding_rate=market.funding_rate,
            stop_loss=stop_loss,
            take_profits=take_profits,
            risk_reward=risk_reward,
            indicators=indicators,
            reasons=reasons,
        )


def detect_regime(candles: list[Candle], indicators: IndicatorSnapshot) -> MarketRegime:
    close = candles[-1].close
    previous = candles[-2].close
    atr_pct = (indicators.atr or 0) / close
    if close < previous * 0.965 and atr_pct > 0.025:
        return MarketRegime.PANIC
    if atr_pct > 0.025:
        return MarketRegime.HIGH_VOL
    if atr_pct < 0.004:
        return MarketRegime.LOW_VOL
    if indicators.ema20 and indicators.ema50 and indicators.ema200:
        if close > indicators.ema20 > indicators.ema50 > indicators.ema200:
            return MarketRegime.TRENDING_UP
        if close < indicators.ema20 < indicators.ema50 < indicators.ema200:
            return MarketRegime.TRENDING_DOWN
    return MarketRegime.RANGING


def score_market(
    candles: list[Candle], indicators: IndicatorSnapshot, regime: MarketRegime
) -> tuple[int, int, list[str]]:
    close = candles[-1].close
    volume = candles[-1].volume
    long_score = 0
    short_score = 0
    reasons: list[str] = []

    if regime == MarketRegime.TRENDING_UP:
        long_score += 35
        reasons.append("Xu hướng tăng")
    elif regime == MarketRegime.TRENDING_DOWN:
        short_score += 35
        reasons.append("Xu hướng giảm")
    elif regime == MarketRegime.HIGH_VOL:
        long_score += 10
        short_score += 10
        reasons.append("Biến động cao")
    elif regime == MarketRegime.PANIC:
        short_score += 25
        reasons.append("Panic")

    if indicators.rsi is not None:
        if 42 <= indicators.rsi <= 58:
            long_score += 10
            short_score += 10
        if indicators.rsi < 35:
            long_score += 15
            reasons.append("RSI quá bán")
        if indicators.rsi > 65:
            short_score += 15
            reasons.append("RSI quá mua")

    if indicators.macd_histogram is not None:
        if indicators.macd_histogram > 0:
            long_score += 15
            reasons.append("MACD ủng hộ LONG")
        elif indicators.macd_histogram < 0:
            short_score += 15
            reasons.append("MACD ủng hộ SHORT")

    if indicators.vwap:
        if close > indicators.vwap:
            long_score += 10
        else:
            short_score += 10

    if indicators.bollinger_upper and indicators.bollinger_lower:
        if close > indicators.bollinger_upper:
            long_score += 10
            reasons.append("Breakout lên Bollinger")
        if close < indicators.bollinger_lower:
            short_score += 10
            reasons.append("Breakout xuống Bollinger")

    if indicators.adx and indicators.adx > 22:
        long_score += 10 if long_score >= short_score else 0
        short_score += 10 if short_score > long_score else 0
        reasons.append("ADX xác nhận trend")

    if indicators.volume_sma20 and volume > indicators.volume_sma20 * 1.25:
        long_score += 10
        short_score += 10
        reasons.append("Volume tăng")

    return min(long_score, 100), min(short_score, 100), reasons


def build_trade_levels(
    side: str, price: float, indicators: IndicatorSnapshot
) -> tuple[float, list[float], float]:
    atr_value = indicators.atr or price * 0.01
    risk = max(atr_value * 1.2, price * 0.004)
    if side == "LONG":
        stop_loss = price - risk
        take_profits = [price + risk * 1.0, price + risk * 1.8, price + risk * 2.6]
    else:
        stop_loss = price + risk
        take_profits = [price - risk * 1.0, price - risk * 1.8, price - risk * 2.6]
    risk_reward = abs(take_profits[-1] - price) / abs(price - stop_loss)
    return stop_loss, take_profits, risk_reward


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
