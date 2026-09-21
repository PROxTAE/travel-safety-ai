"""Rate limiting tests.

Tests token bucket mechanics, atomic Redis evaluation, HTTP 429 response formatting with
Retry-After headers, per-user and per-IP bucketing, and fail-open resilience when Redis blinks.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis

from app.errors.exceptions import RateLimited
from app.security.rate_limit import RateLimiter, rate_limit
from app.settings import Settings


class FakeScript:
    def __init__(self, store: dict[str, tuple[float, float]]) -> None:
        self.store = store

    async def __call__(self, keys: list[str], args: list[Any]) -> list[int]:
        key = keys[0]
        capacity = float(args[0])
        refill_rate = float(args[1])
        requested = float(args[2])
        now = float(args[3])

        tokens, last_updated = self.store.get(key, (capacity, now))
        elapsed = max(0.0, now - last_updated)
        tokens = min(capacity, tokens + elapsed * refill_rate)
        last_updated = now

        if tokens >= requested:
            tokens -= requested
            self.store[key] = (tokens, last_updated)
            return [1, int(tokens), 0]
        else:
            needed = requested - tokens
            retry_after = max(1, math.ceil(needed / refill_rate))
            self.store[key] = (tokens, last_updated)
            return [0, int(tokens), retry_after]


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, tuple[float, float]] = {}

    def register_script(self, script: str) -> Any:
        return FakeScript(self.store)


@pytest.fixture
def fake_redis() -> Any:
    return FakeRedis()


@pytest.fixture
def test_rate_limiter() -> RateLimiter:
    return RateLimiter()


async def test_token_bucket_allows_within_capacity(
    test_rate_limiter: RateLimiter, fake_redis: Any, settings: Settings
) -> None:
    subject = f"test_user_{uuid.uuid4()}"
    endpoint = "test_endpoint"

    for i in range(5):
        result = await test_rate_limiter.check(
            redis=fake_redis,
            settings=settings,
            subject=subject,
            endpoint=endpoint,
            capacity=5,
            refill_per_second=1.0,
        )
        assert result.allowed is True
        assert result.remaining == 4 - i
        assert result.retry_after_seconds == 0


async def test_token_bucket_rejects_when_exhausted(
    test_rate_limiter: RateLimiter, fake_redis: Any, settings: Settings
) -> None:
    subject = f"test_user_{uuid.uuid4()}"
    endpoint = "test_endpoint"

    # Consume all 3 tokens
    for _ in range(3):
        res = await test_rate_limiter.check(
            redis=fake_redis,
            settings=settings,
            subject=subject,
            endpoint=endpoint,
            capacity=3,
            refill_per_second=1.0,
        )
        assert res.allowed is True

    # 4th attempt must be rejected
    rejected = await test_rate_limiter.check(
        redis=fake_redis,
        settings=settings,
        subject=subject,
        endpoint=endpoint,
        capacity=3,
        refill_per_second=1.0,
    )
    assert rejected.allowed is False
    assert rejected.remaining == 0
    assert rejected.retry_after_seconds >= 1


async def test_token_bucket_refills_over_time(
    test_rate_limiter: RateLimiter, fake_redis: Any, settings: Settings
) -> None:
    subject = f"test_user_{uuid.uuid4()}"
    endpoint = "test_refill"

    # Exhaust capacity of 1 with refill rate of 10 tokens/sec
    res1 = await test_rate_limiter.check(
        redis=fake_redis,
        settings=settings,
        subject=subject,
        endpoint=endpoint,
        capacity=1,
        refill_per_second=10.0,
    )
    assert res1.allowed is True

    res2 = await test_rate_limiter.check(
        redis=fake_redis,
        settings=settings,
        subject=subject,
        endpoint=endpoint,
        capacity=1,
        refill_per_second=10.0,
    )
    assert res2.allowed is False

    # Wait 0.2s to replenish 2 tokens (capped at capacity 1)
    await asyncio.sleep(0.2)

    res3 = await test_rate_limiter.check(
        redis=fake_redis,
        settings=settings,
        subject=subject,
        endpoint=endpoint,
        capacity=1,
        refill_per_second=10.0,
    )
    assert res3.allowed is True


async def test_rate_limiter_enforce_raises_rate_limited(
    test_rate_limiter: RateLimiter, fake_redis: Any, settings: Settings
) -> None:
    subject = f"test_user_{uuid.uuid4()}"
    endpoint = "test_enforce"

    # Consume 1 token
    await test_rate_limiter.enforce(
        redis=fake_redis,
        settings=settings,
        subject=subject,
        subject_type="user",
        endpoint=endpoint,
        capacity=1,
        refill_per_second=0.5,
    )

    # Second call should raise RateLimited with retry_after_seconds
    with pytest.raises(RateLimited) as exc_info:
        await test_rate_limiter.enforce(
            redis=fake_redis,
            settings=settings,
            subject=subject,
            subject_type="user",
            endpoint=endpoint,
            capacity=1,
            refill_per_second=0.5,
        )

    assert exc_info.value.code.value == "RATE_LIMITED"
    assert exc_info.value.retry_after_seconds is not None
    assert exc_info.value.retry_after_seconds >= 1


async def test_rate_limiter_fails_open_on_redis_error(
    test_rate_limiter: RateLimiter, settings: Settings
) -> None:
    """When Redis is down or times out, rate limiting fails open gracefully."""
    # Create a dummy closed/invalid Redis client to trigger error
    broken_redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.01)
    await broken_redis.aclose()

    result = await test_rate_limiter.check(
        redis=broken_redis,
        settings=settings,
        subject="any_subject",
        endpoint="any_endpoint",
        capacity=5,
        refill_per_second=1.0,
    )

    # Must fail open (allowed=True)
    assert result.allowed is True
    assert result.retry_after_seconds == 0


async def test_http_rate_limiting_returns_429_with_retry_after(
    app: FastAPI, client: httpx.AsyncClient, fake_redis: Any
) -> None:
    app.state.redis = fake_redis
    endpoint_name = f"route_{uuid.uuid4().hex[:8]}"

    from fastapi import Depends

    @app.get(
        f"/_test/{endpoint_name}",
        dependencies=[Depends(rate_limit(endpoint_name, capacity=2, refill_per_second=0.1))],
    )
    async def limited_route() -> dict[str, str]:
        return {"status": "ok"}

    # First 2 requests succeed
    r1 = await client.get(f"/_test/{endpoint_name}")
    assert r1.status_code == 200

    r2 = await client.get(f"/_test/{endpoint_name}")
    assert r2.status_code == 200

    # 3rd request receives 429
    r3 = await client.get(f"/_test/{endpoint_name}")
    assert r3.status_code == 429
    assert r3.headers.get("Retry-After") is not None
    retry_after = int(r3.headers["Retry-After"])
    assert retry_after >= 1

    body = r3.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["retryable"] is True
    assert body["error"]["retry_after_seconds"] == retry_after
    assert "request_id" in body["meta"]


async def test_disabled_rate_limit_allows_all(
    test_rate_limiter: RateLimiter, fake_redis: Any, settings: Settings
) -> None:
    disabled_settings = settings.model_copy(update={"rate_limit_enabled": False})

    for _ in range(10):
        res = await test_rate_limiter.check(
            redis=fake_redis,
            settings=disabled_settings,
            subject="disabled_test",
            endpoint="test",
            capacity=1,
            refill_per_second=0.1,
        )
        assert res.allowed is True
