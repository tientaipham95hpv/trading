"""Shared Binance access gateway: rate limiter, TTL cache and circuit breaker.

Một gateway duy nhất cho mỗi base URL được dùng chung bởi market-data client
và exchange adapter, để tổng lưu lượng gửi tới Binance luôn nằm trong ngân sách
weight thay vì mỗi client tự gọi tự do.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar


class EndpointClass(str, Enum):
    MARKET = "market"
    PRIVATE = "private"
    ORDER = "order"


class CircuitOpenError(Exception):
    """Gateway đang mở circuit breaker, từ chối request để tránh bị ban IP."""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Circuit breaker mở, thử lại sau {retry_after_seconds:.1f}s"
        )


class RateLimitBudgetExceeded(Exception):
    """Không thể đặt lịch request trong thời gian chờ tối đa cho phép."""


@dataclass
class GatewayLimits:
    # Ngân sách weight/phút theo lớp endpoint (Binance futures: 2400 weight/phút tổng).
    market_weight_per_minute: float = 900.0
    private_weight_per_minute: float = 600.0
    order_requests_per_10s: float = 20.0
    max_wait_seconds: float = 30.0


class _SlidingWindow:
    """Ngân sách weight trong cửa sổ trượt, dùng asyncio lock để an toàn đa task."""

    def __init__(self, capacity: float, window_seconds: float) -> None:
        self.capacity = capacity
        self.window_seconds = window_seconds
        self._events: list[tuple[float, float]] = []
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] <= cutoff:
            self._events.pop(0)

    def current_usage(self) -> float:
        self._prune(time.monotonic())
        return sum(weight for _, weight in self._events)

    async def acquire(self, weight: float, *, max_wait_seconds: float) -> None:
        if weight > self.capacity:
            raise RateLimitBudgetExceeded(f"Weight {weight} vượt ngân sách {self.capacity}")
        deadline = time.monotonic() + max_wait_seconds
        while True:
            async with self._lock:
                now = time.monotonic()
                self._prune(now)
                usage = sum(weight for _, weight in self._events)
                if usage + weight <= self.capacity:
                    self._events.append((now, weight))
                    return
                oldest = self._events[0][0]
                wait = oldest + self.window_seconds - now
            if time.monotonic() + wait > deadline:
                raise RateLimitBudgetExceeded(
                    f"Chờ {wait:.1f}s để đủ ngân sách weight, vượt giới hạn {max_wait_seconds}s"
                )
            await asyncio.sleep(min(wait, max(0.05, deadline - time.monotonic())))


class CircuitBreaker:
    """Mở khi gặp lỗi liên tiếp hoặc 429/418; half-open cho 1 request thăm dò."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        clock=time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._consecutive_failures = 0
        self._open_until: float | None = None
        self._half_open_probe_active = False

    @property
    def is_open(self) -> bool:
        if self._open_until is None:
            return False
        return self._clock() < self._open_until

    def remaining_cooldown(self) -> float:
        if self._open_until is None:
            return 0.0
        return max(0.0, self._open_until - self._clock())

    def allow_request(self) -> bool:
        if not self.is_open:
            return True
        if not self._half_open_probe_active:
            self._half_open_probe_active = True
            return True
        return False

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._open_until = None
        self._half_open_probe_active = False

    def record_failure(self, *, cooldown_override_seconds: float | None = None) -> None:
        self._consecutive_failures += 1
        self._half_open_probe_active = False
        if self._consecutive_failures >= self.failure_threshold or cooldown_override_seconds:
            cooldown = cooldown_override_seconds or self.cooldown_seconds
            self._open_until = self._clock() + cooldown

    def trip(self, cooldown_seconds: float) -> None:
        self._consecutive_failures = self.failure_threshold
        self._half_open_probe_active = False
        self._open_until = self._clock() + cooldown_seconds

    def status(self) -> dict[str, Any]:
        return {
            "state": "open" if self.is_open else "closed",
            "consecutive_failures": self._consecutive_failures,
            "remaining_cooldown_seconds": round(self.remaining_cooldown(), 1),
        }


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, _CacheEntry] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        entry = self._items.get(key)
        if entry is None or self._clock() >= entry.expires_at:
            if entry is not None:
                self._items.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        self._items[key] = _CacheEntry(value=value, expires_at=self._clock() + ttl_seconds)


def cache_key(path: str, params: dict[str, Any] | None) -> str:
    if not params:
        return path
    rendered = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return f"{path}?{rendered}"


class BinanceGateway:
    """Rate limiter + TTL cache + circuit breaker cho một Binance base URL."""

    # TTL mặc định cho các endpoint GET công khai, an toàn để cache ngắn hạn.
    DEFAULT_CACHE_TTLS: ClassVar[dict[str, float]] = {
        "/fapi/v1/exchangeInfo": 600.0,
        "/fapi/v1/ticker/24hr": 10.0,
        "/fapi/v1/ticker/bookTicker": 2.0,
        "/fapi/v1/premiumIndex": 10.0,
    }

    def __init__(self, base_url: str, limits: GatewayLimits | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.limits = limits or GatewayLimits()
        self.market_window = _SlidingWindow(
            self.limits.market_weight_per_minute, window_seconds=60.0
        )
        self.private_window = _SlidingWindow(
            self.limits.private_weight_per_minute, window_seconds=60.0
        )
        self.order_window = _SlidingWindow(
            self.limits.order_requests_per_10s, window_seconds=10.0
        )
        self.circuit_breaker = CircuitBreaker()
        self.cache = TTLCache()
        self.cache_ttls = dict(self.DEFAULT_CACHE_TTLS)

    def classify(self, method: str, path: str, *, signed: bool) -> tuple[EndpointClass, float]:
        """Trả về lớp endpoint và weight ước lượng theo bảng giá Binance futures."""
        if method != "GET":
            if path in {"/fapi/v1/order", "/fapi/v1/algoOrder"} and method == "POST":
                return EndpointClass.ORDER, 1.0
            return EndpointClass.PRIVATE, 1.0
        if signed:
            weight = 5.0 if path in {"/fapi/v2/account"} else 1.0
            return EndpointClass.PRIVATE, weight
        weights = {
            "/fapi/v1/exchangeInfo": 1.0,
            "/fapi/v1/ticker/24hr": 40.0,
            "/fapi/v1/ticker/bookTicker": 2.0,
            "/fapi/v1/premiumIndex": 10.0,
            "/fapi/v1/klines": 2.0,
            "/fapi/v1/time": 1.0,
        }
        return EndpointClass.MARKET, weights.get(path, 1.0)

    async def acquire(
        self,
        method: str,
        path: str,
        *,
        signed: bool,
    ) -> None:
        """Chờ tới lượt theo ngân sách weight; raise nếu circuit breaker mở."""
        if not self.circuit_breaker.allow_request():
            raise CircuitOpenError(self.circuit_breaker.remaining_cooldown())
        endpoint_class, weight = self.classify(method, path, signed=signed)
        max_wait = self.limits.max_wait_seconds
        if endpoint_class == EndpointClass.ORDER:
            await self.order_window.acquire(1.0, max_wait_seconds=max_wait)
            await self.private_window.acquire(weight, max_wait_seconds=max_wait)
        elif endpoint_class == EndpointClass.PRIVATE:
            await self.private_window.acquire(weight, max_wait_seconds=max_wait)
        else:
            await self.market_window.acquire(weight, max_wait_seconds=max_wait)

    def cached(self, path: str, params: dict[str, Any] | None) -> Any | None:
        if path not in self.cache_ttls:
            return None
        return self.cache.get(cache_key(path, params))

    def store(self, path: str, params: dict[str, Any] | None, value: Any) -> None:
        ttl = self.cache_ttls.get(path)
        if ttl:
            self.cache.set(cache_key(path, params), value, ttl)

    def record_success(self) -> None:
        self.circuit_breaker.record_success()

    def record_failure(
        self, *, status_code: int | None = None, retry_after_seconds: float | None = None
    ) -> None:
        if status_code == 429:
            # Binance yêu cầu giảm tải ngay khi thấy 429; cooldown tối thiểu 2 phút.
            self.circuit_breaker.trip(max(retry_after_seconds or 0.0, 120.0))
        elif status_code == 418:
            self.circuit_breaker.trip(max(retry_after_seconds or 0.0, 600.0))
        elif status_code is None or status_code >= 500:
            self.circuit_breaker.record_failure()

    def status(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "circuit_breaker": self.circuit_breaker.status(),
            "cache": {"hits": self.cache.hits, "misses": self.cache.misses},
            "usage": {
                "market_weight_last_minute": self.market_window.current_usage(),
                "private_weight_last_minute": self.private_window.current_usage(),
                "order_requests_last_10s": self.order_window.current_usage(),
            },
        }


_gateways: dict[str, BinanceGateway] = {}


def gateway_for(base_url: str, limits: GatewayLimits | None = None) -> BinanceGateway:
    """Gateway dùng chung cho mọi client trỏ về cùng một base URL."""
    key = base_url.rstrip("/")
    gateway = _gateways.get(key)
    if gateway is None:
        gateway = BinanceGateway(key, limits)
        _gateways[key] = gateway
    return gateway


def reset_gateways() -> None:
    _gateways.clear()
