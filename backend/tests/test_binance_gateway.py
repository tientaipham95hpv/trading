import asyncio

import pytest

from app.services.binance_gateway import (
    BinanceGateway,
    CircuitBreaker,
    CircuitOpenError,
    GatewayLimits,
    RateLimitBudgetExceeded,
    TTLCache,
    gateway_for,
    reset_gateways,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_circuit_breaker_opens_after_failures() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow_request()
    breaker.record_failure()
    assert breaker.is_open
    assert breaker.allow_request()  # half-open: cho 1 request thăm dò
    assert not breaker.allow_request()  # vẫn khóa cho đến khi probe xong
    clock.advance(10.1)
    assert breaker.allow_request()  # hết cooldown, circuit đóng lại
    breaker.record_success()
    assert breaker.allow_request()


def test_circuit_breaker_trips_on_429_and_418() -> None:
    clock = FakeClock()
    gateway = BinanceGateway("https://x.test", GatewayLimits())
    gateway.circuit_breaker._clock = clock
    gateway.record_failure(status_code=429, retry_after_seconds=5.0)
    assert gateway.circuit_breaker.is_open
    assert gateway.circuit_breaker.remaining_cooldown() >= 119.0

    gateway.circuit_breaker.record_success()
    gateway.record_failure(status_code=418)
    assert gateway.circuit_breaker.remaining_cooldown() >= 599.0


def test_ttl_cache_expires() -> None:
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    cache.set("k", {"v": 1}, ttl_seconds=5.0)
    assert cache.get("k") == {"v": 1}
    assert cache.hits == 1
    clock.advance(5.1)
    assert cache.get("k") is None
    assert cache.misses == 1


async def test_rate_limiter_blocks_then_passes() -> None:
    limits = GatewayLimits(market_weight_per_minute=42.0, max_wait_seconds=5.0)
    gateway = BinanceGateway("https://x.test", limits)
    # ticker/24hr nặng 40 weight: lần 1 ăn 40, lần 2 phải chờ cửa sổ trôi qua.
    await gateway.acquire("GET", "/fapi/v1/ticker/24hr", signed=False)
    with pytest.raises(RateLimitBudgetExceeded):
        await asyncio.wait_for(
            gateway.acquire("GET", "/fapi/v1/ticker/24hr", signed=False), timeout=1.0
        )


async def test_acquire_raises_when_circuit_open() -> None:
    clock = FakeClock()
    gateway = BinanceGateway("https://x.test", GatewayLimits())
    gateway.circuit_breaker._clock = clock
    gateway.circuit_breaker.trip(cooldown_seconds=60.0)
    assert gateway.circuit_breaker.allow_request()  # half-open probe
    with pytest.raises(CircuitOpenError):
        await gateway.acquire("GET", "/fapi/v1/exchangeInfo", signed=False)


def test_gateway_shared_per_base_url() -> None:
    reset_gateways()
    first = gateway_for("https://fapi.binance.com")
    second = gateway_for("https://fapi.binance.com/")
    assert first is second
    reset_gateways()


def test_cache_only_configured_endpoints() -> None:
    gateway = BinanceGateway("https://x.test", GatewayLimits())
    gateway.store("/fapi/v1/exchangeInfo", None, {"symbols": []})
    assert gateway.cached("/fapi/v1/exchangeInfo", None) == {"symbols": []}
    gateway.store("/fapi/v2/account", None, {"x": 1})
    assert gateway.cached("/fapi/v2/account", None) is None


def test_classify_weights() -> None:
    gateway = BinanceGateway("https://x.test", GatewayLimits())
    assert gateway.classify("POST", "/fapi/v1/order", signed=True)[0].value == "order"
    assert gateway.classify("GET", "/fapi/v2/account", signed=True)[1] == 5.0
    assert gateway.classify("GET", "/fapi/v1/ticker/24hr", signed=False)[1] == 40.0
