"""Redis cache for provider responses.

Key shape follows 00_API_AND_DATA_CONTRACTS.md § 7:
    sta:{env}:provider-cache:{provider}:{schema}:{hash}

Every key gets a TTL - the contract forbids permanent keys. Negative results are
cached very briefly so a provider outage does not turn into a retry storm, and a
distributed lock keeps a cache miss from stampeding the provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.observability.logging import get_logger
from app.observability.metrics import cache_events

log = get_logger(__name__)

_NEGATIVE_MARKER = "__unavailable__"


def build_key(
    *,
    env: str,
    provider_id: str,
    schema_version: str,
    key_fields: dict[str, Any],
) -> str:
    """Hash the normalised query. Field order never affects the key."""
    blob = json.dumps(key_fields, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
    return f"sta:{env}:provider-cache:{provider_id}:{schema_version}:{digest}"


@dataclass(slots=True)
class CacheHit:
    payload: Any
    negative: bool = False


class ProviderCache:
    def __init__(
        self,
        redis: Redis,
        *,
        env: str,
        lock_timeout_seconds: float = 10.0,
        lock_wait_seconds: float = 5.0,
    ) -> None:
        self._redis = redis
        self._env = env
        self._lock_timeout = lock_timeout_seconds
        self._lock_wait = lock_wait_seconds

    async def get(self, key: str, provider_id: str) -> CacheHit | None:
        # Redis being down must not take a capability with it: the provider is
        # still reachable, so a cache failure degrades to a miss.
        try:
            raw = await self._redis.get(key)
        except (RedisError, OSError) as exc:
            cache_events.labels(provider=provider_id, event="unavailable").inc()
            log.warning("cache_unavailable", operation="get", error=str(exc))
            return None
        if raw is None:
            cache_events.labels(provider=provider_id, event="miss").inc()
            return None
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        if text == _NEGATIVE_MARKER:
            cache_events.labels(provider=provider_id, event="negative_hit").inc()
            return CacheHit(payload=None, negative=True)
        cache_events.labels(provider=provider_id, event="hit").inc()
        return CacheHit(payload=json.loads(text))

    async def set(self, key: str, provider_id: str, payload: Any, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache entries must have a positive TTL")
        try:
            await self._redis.set(
                key,
                json.dumps(payload, ensure_ascii=False, default=str),
                ex=ttl_seconds,
            )
        except (RedisError, OSError) as exc:
            cache_events.labels(provider=provider_id, event="unavailable").inc()
            log.warning("cache_unavailable", operation="set", error=str(exc))
            return
        cache_events.labels(provider=provider_id, event="store").inc()

    async def set_negative(self, key: str, provider_id: str, ttl_seconds: int) -> None:
        """Remember a failure briefly. TTL is intentionally short: a stale
        'unavailable' is as misleading as stale data."""
        try:
            await self._redis.set(key, _NEGATIVE_MARKER, ex=max(1, ttl_seconds))
        except (RedisError, OSError) as exc:
            cache_events.labels(provider=provider_id, event="unavailable").inc()
            log.warning("cache_unavailable", operation="set_negative", error=str(exc))
            return
        cache_events.labels(provider=provider_id, event="store_negative").inc()

    async def acquire_lock(self, key: str, provider_id: str) -> bool:
        try:
            acquired = await self._redis.set(
                f"sta:{self._env}:lock:provider-cache:{key}",
                "1",
                nx=True,
                ex=int(self._lock_timeout),
            )
        except (RedisError, OSError) as exc:
            # No lock service means no stampede protection. Proceeding is the
            # lesser evil: waiting on a lock that can never be granted would
            # stall every request instead of just duplicating a few.
            cache_events.labels(provider=provider_id, event="unavailable").inc()
            log.warning("cache_unavailable", operation="lock", error=str(exc))
            return True
        return bool(acquired)

    async def release_lock(self, key: str) -> None:
        try:
            await self._redis.delete(f"sta:{self._env}:lock:provider-cache:{key}")
        except (RedisError, OSError) as exc:
            log.warning("cache_unavailable", operation="unlock", error=str(exc))

    async def wait_for_other_fetch(self, key: str, provider_id: str) -> CacheHit | None:
        """Someone else holds the lock: poll briefly for their result instead of
        making the same call. Falling through to our own fetch is acceptable -
        a duplicate call is better than a request that hangs on a dead holder."""
        cache_events.labels(provider=provider_id, event="lock_wait").inc()
        deadline = asyncio.get_running_loop().time() + self._lock_wait
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
            hit = await self.get(key, provider_id)
            if hit is not None:
                return hit
        return None

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception as exc:  # readiness must never raise
            log.warning("redis_ping_failed", error=str(exc))
            return False
