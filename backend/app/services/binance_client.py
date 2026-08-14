from itertools import pairwise
from typing import Any

import httpx

from app.domain.models import Candle
from app.services.binance_gateway import BinanceGateway, gateway_for


class BinanceMarketDataClient:
    """Read-only Binance USD-M Futures data client through the shared gateway."""

    def __init__(self, base_url: str, *, gateway: BinanceGateway | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self.gateway = gateway or gateway_for(self._base_url)

    async def _get(
        self, path: str, *, params: dict[str, Any] | None = None, timeout: float = 15.0
    ) -> Any:
        cached = self.gateway.cached(path, params)
        if cached is not None:
            return cached
        await self.gateway.acquire("GET", path, signed=False)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{self._base_url}{path}", params=params)
            if response.status_code >= 400:
                self.gateway.record_failure(
                    status_code=response.status_code,
                    retry_after_seconds=_retry_after_seconds(response),
                )
                response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            self.gateway.record_failure()
            raise
        self.gateway.record_success()
        self.gateway.store(path, params, payload)
        return payload

    async def exchange_info(self) -> dict[str, Any]:
        return await self._get("/fapi/v1/exchangeInfo", timeout=10.0)

    async def ticker_24h(self) -> list[dict[str, Any]]:
        payload = await self._get("/fapi/v1/ticker/24hr", timeout=10.0)
        return payload if isinstance(payload, list) else [payload]

    async def book_ticker(self) -> list[dict[str, Any]]:
        payload = await self._get("/fapi/v1/ticker/bookTicker", timeout=10.0)
        return payload if isinstance(payload, list) else [payload]

    async def premium_index(self) -> list[dict[str, Any]]:
        payload = await self._get("/fapi/v1/premiumIndex", timeout=10.0)
        return payload if isinstance(payload, list) else [payload]

    async def klines(self, symbol: str, interval: str, limit: int = 250) -> list[Candle]:
        rows = await self._get(
            "/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=15.0,
        )
        return self._candles(rows)

    async def closed_klines_range(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: int,
        end_time: int,
        limit: int,
    ) -> list[Candle]:
        """Fetch one bounded historical range, retaining only candles closed before exit."""
        if limit < 1 or limit > 5000:
            raise ValueError("Số nến lifecycle phải nằm trong khoảng 1-5000")
        rows: list[list[Any]] = []
        cursor = start_time
        while len(rows) < limit and cursor < end_time:
            page_limit = min(1000, limit - len(rows))
            page = await self._get(
                "/fapi/v1/klines",
                params={
                    "symbol": symbol.upper(), "interval": interval, "startTime": cursor,
                    "endTime": end_time - 1, "limit": page_limit,
                },
                timeout=30.0,
            )
            if not isinstance(page, list) or not page:
                break
            rows.extend(page)
            cursor = int(page[-1][6]) + 1
            if len(page) < page_limit:
                break
        candles = [candle for candle in self._candles(rows) if candle.close_time < end_time]
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
        while len(rows) < limit:
            page_limit = min(1000, limit - len(rows))
            params: dict[str, Any] = {"symbol": symbol.upper(), "interval": interval, "limit": page_limit}
            if end_time is not None:
                params["endTime"] = end_time
            page = await self._get("/fapi/v1/klines", params=params, timeout=30.0)
            if not isinstance(page, list) or not page:
                break
            rows = page + rows
            end_time = int(page[0][0]) - 1
            if len(page) < page_limit:
                break
        by_open_time = {int(row[0]): row for row in rows if len(row) >= 8}
        candles = self._candles([by_open_time[key] for key in sorted(by_open_time)][-limit:])
        self._validate_historical_candles(candles, limit)
        return candles

    async def closed_klines(
        self, symbol: str, interval: str, *, limit: int, end_time: int
    ) -> list[Candle]:
        """Read an exact bounded window whose candles all closed before one shared cutoff."""
        if limit < 2 or limit > 500:
            raise ValueError("Số nến tương quan phải nằm trong khoảng 2-500")
        rows = await self._get(
            "/fapi/v1/klines",
            params={"symbol": symbol.upper(), "interval": interval, "endTime": end_time - 1, "limit": limit},
            timeout=15.0,
        )
        candles = [candle for candle in self._candles(rows) if candle.close_time < end_time]
        self._validate_historical_candles(candles, limit)
        return candles

    @staticmethod
    def _candles(rows: list[list[Any]]) -> list[Candle]:
        return [
            Candle(open_time=int(row[0]), open=float(row[1]), high=float(row[2]),
                   low=float(row[3]), close=float(row[4]), volume=float(row[5]),
                   close_time=int(row[6]), quote_volume=float(row[7]))
            for row in rows if len(row) >= 8
        ]

    @staticmethod
    def _validate_historical_candles(candles: list[Candle], requested: int) -> None:
        if len(candles) != requested:
            raise ValueError(f"Chỉ nhận được {len(candles)}/{requested} nến lịch sử")
        for previous, current in pairwise(candles):
            if current.open_time <= previous.open_time:
                raise ValueError("Dữ liệu nến không theo thứ tự thời gian")
            if current.open_time != previous.close_time + 1:
                raise ValueError(f"Thiếu nến lịch sử giữa {previous.open_time} và {current.open_time}")
        for candle in candles:
            if candle.low > min(candle.open, candle.close) or candle.high < max(candle.open, candle.close):
                raise ValueError(f"OHLC không hợp lệ tại {candle.open_time}")
            if candle.volume < 0 or candle.quote_volume < 0:
                raise ValueError(f"Volume không hợp lệ tại {candle.open_time}")


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
