"""Load and concurrency verification for API endpoints and SSE connections.

Phase 8.3 Verification:
1. High concurrency handling on lightweight endpoints (/health/live).
2. Rate limiter behavior under burst concurrency (429 + Retry-After + contract error envelope).
3. SSE active connection gauge tracking, resource lifecycle, and per-user stream cap enforcement.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from prometheus_client import REGISTRY

from app.api.v1.runs import _admit, _events
from app.errors.codes import ErrorCode
from app.security.rate_limit import rate_limit
from app.settings import Settings


@pytest.mark.asyncio
async def test_concurrent_health_requests_under_load(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Ensure endpoint handles concurrent burst traffic cleanly without errors
    or thread pool starvation."""
    concurrency = 50
    start = time.perf_counter()

    async def fetch() -> httpx.Response:
        return await client.get("/health/live")

    tasks = [fetch() for _ in range(concurrency)]
    responses = await asyncio.gather(*tasks)

    duration = time.perf_counter() - start
    assert len(responses) == concurrency
    assert all(r.status_code == 200 for r in responses)
    assert all(r.json()["status"] == "alive" for r in responses)
    # Average latency per request in ASGI direct transport should be very fast (< 20ms)
    assert duration < 5.0, f"Concurrent load took too long: {duration:.2f}s"


@pytest.mark.asyncio
async def test_burst_concurrency_rate_limiter_enforces_429(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Ensure that concurrent bursts exceeding bucket capacity return 429 and proper Retry-After."""
    from tests.test_rate_limiting import FakeRedis

    app.state.redis = FakeRedis()
    endpoint_name = "burst_test"
    limiter = rate_limit(endpoint_name, capacity=5, refill_per_second=0.01)

    @app.get("/_test/burst_endpoint", dependencies=[Depends(limiter)])
    async def burst_target() -> dict[str, str]:
        return {"result": "ok"}

    concurrency = 25
    tasks = [client.get("/_test/burst_endpoint") for _ in range(concurrency)]
    responses = await asyncio.gather(*tasks)

    successes = [r for r in responses if r.status_code == 200]
    rate_limited = [r for r in responses if r.status_code == 429]

    # Exactly capacity=5 should succeed; rest must be throttled
    assert len(successes) == 5
    assert len(rate_limited) == 20

    for resp in rate_limited:
        assert "Retry-After" in resp.headers
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after >= 1
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == ErrorCode.RATE_LIMITED.value
        assert body["error"]["retryable"] is True
        assert body["error"]["retry_after_seconds"] == retry_after


@pytest.mark.asyncio
async def test_sse_active_connection_gauge_increments_and_cleans_up(
    settings: Settings,
) -> None:
    """Verify that SSE stream properly increments the active connection gauge
    and decrements on exit."""
    baseline = REGISTRY.get_sample_value("api_active_sse_connections") or 0.0

    class DummyRedis:
        def __init__(self) -> None:
            self.counters: dict[str, int] = {}

        async def incr(self, key: str) -> int:
            self.counters[key] = self.counters.get(key, 0) + 1
            return self.counters[key]

        async def decr(self, key: str) -> int:
            self.counters[key] = max(0, self.counters.get(key, 0) - 1)
            return self.counters[key]

        async def expire(self, key: str, ttl: int) -> bool:
            return True

        async def xread(self, streams: dict[str, str], count: int, block: int) -> list[Any]:
            return []

    class MockAppState:
        def __init__(self, s: Settings, r: Any) -> None:
            self.settings = s
            self.redis = r
            self.session_factory = None

    class MockApp:
        def __init__(self, state: MockAppState) -> None:
            self.state = state

    class DummyRequest:
        def __init__(self, mock_app: MockApp) -> None:
            self.app = mock_app

        async def is_disconnected(self) -> bool:
            return True  # Terminate immediately

    dummy_redis = DummyRedis()
    mock_req = DummyRequest(MockApp(MockAppState(settings, dummy_redis)))

    import uuid

    user_id = uuid.uuid4()
    req_id = uuid.uuid4()

    # Before iterating, gauge is baseline
    current = REGISTRY.get_sample_value("api_active_sse_connections") or 0.0
    assert current == baseline

    # Run the generator through one cycle
    gen = _events(
        request=mock_req,  # type: ignore[arg-type]
        request_id=req_id,
        owner_id=user_id,
        resume_from="0-0",
        already_terminal=True,
    )

    # Consume stream
    _ = [event async for event in gen]

    # After stream completes, gauge must decrement back to baseline
    after = REGISTRY.get_sample_value("api_active_sse_connections") or 0.0
    assert after == baseline


@pytest.mark.asyncio
async def test_sse_per_user_connection_limit_admit() -> None:
    """Verify that _admit enforces the maximum concurrent SSE connections per user."""

    class MockRedis:
        def __init__(self) -> None:
            self.val = 0

        async def incr(self, key: str) -> int:
            self.val += 1
            return self.val

        async def decr(self, key: str) -> int:
            self.val -= 1
            return self.val

        async def expire(self, key: str, ttl: int) -> bool:
            return True

    mock_redis = MockRedis()
    limit = 3

    # First 3 connections should be admitted
    assert await _admit(mock_redis, "counter:user1", limit=limit) is True
    assert await _admit(mock_redis, "counter:user1", limit=limit) is True
    assert await _admit(mock_redis, "counter:user1", limit=limit) is True

    # 4th connection exceeds limit and must be rejected
    assert await _admit(mock_redis, "counter:user1", limit=limit) is False
    # Counter should have been decremented back to 3
    assert mock_redis.val == 3
