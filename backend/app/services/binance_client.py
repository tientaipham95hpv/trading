from itertools import pairwise
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

    async def closed_klines_range(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int,
        end_time: int,
        limit: int,
    ) -> list[Candle]:
        """Fetch one bounded, historical range and retain only candles closed before exit."""
        if limit < 1 or limit > 5000:
            raise ValueError("Số nến lifecycle phải nằm trong khoảng 1-5000")
        rows: list[list[Any]] = []
        cursor = start_time
        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(rows) < limit and cursor < end_time:
                page_limit = min(1000, limit - len(rows))
                response = await client.get(
                    f"{self._base_url}/fapi/v1/klines",
                    params={
                        "symbol": symbol.upper(),
                        "interval": interval,
                        "startTime": cursor,
                        "endTime": end_time - 1,
                        "limit": page_limit,
                    },
                )
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list) or not page:
                    break
                rows.extend(page)
                cursor = int(page[-1][6]) + 1
                if len(page) < page_limit:
                    break
        candles = [
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
            if len(row) >= 8 and int(row[6]) < end_time
        ]
        if len(candles) != limit:
            raise ValueError(f"Chỉ nhận được {len(candles)}/{limit} nến lifecycle đã đóng")
        self._validate_historical_candles(candles, limit)
        return candles

    async def historical_klines(
        self, symbol: str, interval: str, limit: int = 1000
    ) -> list[Candle]:
        """Fetch closed candles backwards with deterministic pagination and strict validation."""
        if limit < 1 or limit > 5000:
            raise ValueError("Số nến lịch sử phải nằm trong khoảng 1-5000")
        rows: list[list[Any]] = []
        end_time: int | None = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(rows) < limit:
                page_limit = min(1000, limit - len(rows))
                params: dict[str, Any] = {
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "limit": page_limit,
                }
                if end_time is not None:
                    params["endTime"] = end_time
                response = await client.get(f"{self._base_url}/fapi/v1/klines", params=params)
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list) or not page:
                    break
                rows = page + rows
                end_time = int(page[0][0]) - 1
                if len(page) < page_limit:
                    break
        by_open_time = {int(row[0]): row for row in rows if len(row) >= 8}
        ordered = [by_open_time[key] for key in sorted(by_open_time)][-limit:]
        candles = [
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
            for row in ordered
        ]
        self._validate_historical_candles(candles, limit)
        return candles

    @staticmethod
    def _validate_historical_candles(candles: list[Candle], requested: int) -> None:
        if len(candles) != requested:
            raise ValueError(f"Chỉ nhận được {len(candles)}/{requested} nến lịch sử")
        for previous, current in pairwise(candles):
            if current.open_time <= previous.open_time:
                raise ValueError("Dữ liệu nến không theo thứ tự thời gian")
            expected = previous.close_time + 1
            if current.open_time != expected:
                raise ValueError(
                    f"Thiếu nến lịch sử giữa {previous.open_time} và {current.open_time}"
                )
        for candle in candles:
            if candle.low > min(candle.open, candle.close) or candle.high < max(
                candle.open, candle.close
            ):
                raise ValueError(f"OHLC không hợp lệ tại {candle.open_time}")
            if candle.volume < 0 or candle.quote_volume < 0:
                raise ValueError(f"Volume không hợp lệ tại {candle.open_time}")
