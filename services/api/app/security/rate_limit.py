"""Redis-backed token bucket rate limiting.

Per §7 of the contract document, rate limit keys follow the convention:
`sta:{env}:rate:{subject}:{endpoint}`

The subject is:
- `user:<user_id>` when the caller is authenticated;
- `ip:<client_ip>` when unauthenticated (resolved via trusted proxy hops).

An atomic Lua script maintains the token bucket in Redis with a sliding refill rate, returning
allowed status, remaining tokens, and the calculated retry-after duration.
"""

from __future__ import annotations

import contextlib
import math
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.auth.principal import Principal
from app.errors.exceptions import RateLimited
from app.middleware.body_limit import current_client_address
from app.observability.logging import get_logger
from app.observability.metrics import rate_limit_rejected_total
from app.settings import Settings

logger = get_logger(__name__)

# KEYS[1]: Rate limit key
# ARGV[1]: Capacity (maximum tokens)
# ARGV[2]: Refill rate (tokens per second)
# ARGV[3]: Requested tokens (typically 1)
# ARGV[4]: Current timestamp (seconds, float)
# ARGV[5]: Key TTL (seconds, int)
_RATE_LIMITER_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if tokens == nil or last_updated == nil then
    tokens = capacity
    last_updated = now
else
    local elapsed = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + elapsed * refill_rate)
    last_updated = now
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HSET', key, 'tokens', tokens, 'last_updated', last_updated)
    redis.call('EXPIRE', key, ttl)
    return {1, math.floor(tokens), 0}
else
    local needed = requested - tokens
    local retry_after = math.max(1, math.ceil(needed / refill_rate))
    redis.call('HSET', key, 'tokens', tokens, 'last_updated', last_updated)
    redis.call('EXPIRE', key, ttl)
    return {0, math.floor(tokens), retry_after}
end
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    """Token bucket rate limiter backed by Redis."""

    def _get_script(self, redis: Redis) -> Any:
        script = getattr(redis, "_rate_limit_script", None)
        if script is None:
            script = redis.register_script(_RATE_LIMITER_SCRIPT)
            with contextlib.suppress(Exception):
                setattr(redis, "_rate_limit_script", script)  # noqa: B010
        return script

    async def check(
        self,
        redis: Redis | None,
        settings: Settings,
        *,
        subject: str,
        endpoint: str,
        capacity: int,
        refill_per_second: float,
        requested: int = 1,
    ) -> RateLimitResult:
        """Check and consume tokens for a subject and endpoint.

        Fails open if Redis is unreachable or unconfigured, logging the outage
        without dropping user requests.
        """
        if not settings.rate_limit_enabled or redis is None:
            return RateLimitResult(allowed=True, remaining=capacity, retry_after_seconds=0)

        key = f"{settings.redis_namespace}:rate:{subject}:{endpoint}"
        ttl = max(60, int(math.ceil(capacity / max(refill_per_second, 0.001)) * 2))
        now = time.time()

        try:
            script = self._get_script(redis)
            res = await script(
                keys=[key],
                args=[capacity, refill_per_second, requested, now, ttl],
            )
            allowed = bool(res[0])
            remaining = int(res[1])
            retry_after = int(res[2])
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                retry_after_seconds=retry_after,
            )
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            logger.warning(
                "rate_limit_redis_unavailable",
                event_type="resilience",
                error=str(exc),
                endpoint=endpoint,
                subject=subject,
            )
            # Fail open to prevent Redis blinks from causing total API downtime
            return RateLimitResult(allowed=True, remaining=capacity, retry_after_seconds=0)

    async def enforce(
        self,
        redis: Redis | None,
        settings: Settings,
        *,
        subject: str,
        subject_type: str,
        endpoint: str,
        capacity: int,
        refill_per_second: float,
        requested: int = 1,
    ) -> None:
        """Evaluate rate limit and raise RateLimited exception if exceeded."""
        result = await self.check(
            redis=redis,
            settings=settings,
            subject=subject,
            endpoint=endpoint,
            capacity=capacity,
            refill_per_second=refill_per_second,
            requested=requested,
        )
        if not result.allowed:
            rate_limit_rejected_total.labels(endpoint=endpoint, subject_type=subject_type).inc()
            raise RateLimited(
                message="Too many requests. Try again shortly.",
                retry_after_seconds=result.retry_after_seconds,
            )


limiter = RateLimiter()


def resolve_subject(request: Request) -> tuple[str, str]:
    """Derive rate limit subject (user:<user_id> or ip:<client_ip>)."""
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is not None:
        user_id = getattr(principal, "user_id", None) or getattr(principal, "subject", None)
        if user_id:
            return f"user:{user_id}", "user"
    client_ip = current_client_address()
    return f"ip:{client_ip}", "ip"


def rate_limit(
    endpoint: str,
    *,
    capacity: int | None = None,
    refill_per_second: float | None = None,
) -> Any:
    """FastAPI dependency for rate limiting."""

    async def _dependency(request: Request) -> None:
        settings: Settings = request.app.state.settings
        redis: Redis | None = getattr(request.app.state, "redis", None)

        eff_capacity = capacity if capacity is not None else settings.rate_limit_default_capacity
        eff_refill = (
            refill_per_second
            if refill_per_second is not None
            else settings.rate_limit_default_refill_per_second
        )

        subject, subject_type = resolve_subject(request)
        await limiter.enforce(
            redis=redis,
            settings=settings,
            subject=subject,
            subject_type=subject_type,
            endpoint=endpoint,
            capacity=eff_capacity,
            refill_per_second=eff_refill,
        )

    return _dependency
