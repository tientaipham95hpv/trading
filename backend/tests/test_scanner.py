from app.domain.models import BotSettings, Candle, SignalAction, Timeframe
from app.services.scanner import FuturesScanner


def make_candles(trend: float = 1.0) -> list[Candle]:
    candles: list[Candle] = []
    price = 100.0
    for index in range(260):
        price += trend
        candles.append(
            Candle(
                open_time=index,
                open=price - 0.5,
                high=price + 1.5,
                low=price - 1.5,
                close=price,
                volume=1000 + index * 5,
                close_time=index + 1,
                quote_volume=price * 1000,
            )
        )
    return candles


class FakeClient:
    async def exchange_info(self):
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "onboardDate": 0,
                },
                {
                    "symbol": "ETHBUSD",
                    "baseAsset": "ETH",
                    "quoteAsset": "BUSD",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                },
                {
                    "symbol": "OLDUSDT",
                    "baseAsset": "OLD",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "status": "BREAK",
                },
            ]
        }

    async def ticker_24h(self):
        return [
            {
                "symbol": "BTCUSDT",
                "quoteVolume": "100000000",
                "priceChangePercent": "1.5",
                "lastPrice": "100.01",
            }
        ]

    async def book_ticker(self):
        return [{"symbol": "BTCUSDT", "bidPrice": "100", "askPrice": "100.02"}]

    async def premium_index(self):
        return [{"symbol": "BTCUSDT", "lastFundingRate": "0.0001"}]

    async def klines(self, symbol: str, interval: str, limit: int = 250):
        return make_candles()


async def test_scanner_discovers_trading_usdt_perpetuals_without_hardcoding():
    scanner = FuturesScanner(FakeClient(), BotSettings(min_quote_volume=1, min_listing_age_days=0))
    pairs = await scanner.scan_usdm_pairs()

    assert [pair.symbol for pair in pairs] == ["BTCUSDT"]


async def test_scanner_scores_multi_timeframe_long_signal():
    scanner = FuturesScanner(
        FakeClient(),
        BotSettings(
            min_quote_volume=1,
            min_listing_age_days=0,
            min_score_to_trade=50,
            scan_timeframes=[Timeframe.M15],
        ),
    )
    results = await scanner.scan(limit=1)

    assert results[0].symbol == "BTCUSDT"
    assert results[0].long_score > results[0].short_score
    assert results[0].action == SignalAction.LONG
    assert results[0].take_profits
