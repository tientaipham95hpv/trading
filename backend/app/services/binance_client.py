from typing import Any

import httpx

from app.domain.models import Candle


class BinanceMarketDataClient:
    """Read-only Binance USD-M Futures market data client."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def exchange_info(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base_url}/fapi/v1/exchangeInfo")
            response.raise_for_status()
            return response.json()

    async def ticker_24h(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base_url}/fapi/v1/ticker/24hr")
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else [payload]

    async def book_ticker(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base_url}/fapi/v1/ticker/bookTicker")
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else [payload]

    async def premium_index(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base_url}/fapi/v1/premiumIndex")
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else [payload]

    async def klines(self, symbol: str, interval: str, limit: int = 250) -> list[Candle]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self._base_url}/fapi/v1/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            response.raise_for_status()
            rows = response.json()
        return [
            Candle(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=int(row[6]),
                quote_volume=float(row[7]),
            )
            for row in rows
        ]
