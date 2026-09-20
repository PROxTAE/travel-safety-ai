"""Per-provider circuit breaker, concurrency limiter and quota tracking.

State is in-process. That is deliberate for Phase 1: a breaker that trips on one
replica while another keeps hammering a failing provider is still better than no
breaker, and a shared breaker needs a Redis design that belongs with the
distributed cache work. The limitation is recorded in the handoff.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum

from app.observability.metrics import circuit_state, quota_remaining
from app.providers.registry import CircuitPolicy


class CircuitState(Enum):
    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2


class CircuitOpenError(RuntimeError):
    """Raised instead of calling a provider that is currently shut out."""

    def __init__(self, provider_id: str, retry_after_seconds: float) -> None:
        super().__init__(f"circuit open for {provider_id}")
        self.provider_id = provider_id
        self.retry_after_seconds = retry_after_seconds


@dataclass
class CircuitBreaker:
    provider_id: str
    policy: CircuitPolicy
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    opened_at: float = 0.0
    half_open_inflight: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def _publish(self) -> None:
        circuit_state.labels(provider=self.provider_id).set(self.state.value)

    async def before_call(self) -> None:
        async with self._lock:
            if self.state is CircuitState.OPEN:
                elapsed = time.monotonic() - self.opened_at
                if elapsed < self.policy.open_seconds:
                    raise CircuitOpenError(self.provider_id, self.policy.open_seconds - elapsed)
                # Cooldown elapsed: admit a limited number of probes.
                self.state = CircuitState.HALF_OPEN
                self.half_open_inflight = 0
                self._publish()

            if self.state is CircuitState.HALF_OPEN:
                if self.half_open_inflight >= self.policy.half_open_probes:
                    raise CircuitOpenError(self.provider_id, self.policy.open_seconds)
                self.half_open_inflight += 1

    async def on_success(self) -> None:
        async with self._lock:
            self.failures = 0
            self.half_open_inflight = 0
            if self.state is not CircuitState.CLOSED:
                self.state = CircuitState.CLOSED
                self._publish()

    async def on_failure(self) -> None:
        async with self._lock:
            self.half_open_inflight = 0
            if self.state is CircuitState.HALF_OPEN:
                # A failed probe re-opens immediately; do not wait for the
                # threshold again, the provider has already proven it is down.
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
                self._publish()
                return

            self.failures += 1
            if self.failures >= self.policy.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = time.monotonic()
                self._publish()


@dataclass
class ConcurrencyLimiter:
    """Bounded in-flight requests per provider, so one slow provider cannot
    consume the whole connection pool."""

    provider_id: str
    limit: int = 4
    _semaphore: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.limit)

    async def __aenter__(self) -> ConcurrencyLimiter:
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        self._semaphore.release()


@dataclass
class QuotaTracker:
    """Records whatever quota a provider chooses to report.

    openrouteservice sends `X-Ratelimit-Limit`/`-Remaining`/`-Reset`; the
    Open-Meteo and disaster feeds send nothing. So this reads the common
    spellings and stays silent otherwise. It never invents a number -- an
    unknown quota is reported as unknown, not as "plenty left".
    """

    provider_id: str
    remaining: int | None = None
    limit: int | None = None
    window: str = "unknown"

    _HEADERS: tuple[tuple[str, str, str], ...] = (
        ("x-ratelimit-remaining", "x-ratelimit-limit", "unknown"),
        ("x-ratelimit-remaining-day", "x-ratelimit-limit-day", "day"),
        ("x-ratelimit-remaining-minute", "x-ratelimit-limit-minute", "minute"),
    )

    def observe(self, headers: dict[str, str]) -> None:
        lowered = {k.lower(): v for k, v in headers.items()}
        for remaining_key, limit_key, window in self._HEADERS:
            if remaining_key in lowered:
                try:
                    self.remaining = int(lowered[remaining_key])
                except ValueError:
                    continue
                self.window = window
                if limit_key in lowered:
                    try:
                        self.limit = int(lowered[limit_key])
                    except ValueError:
                        self.limit = None
                quota_remaining.labels(provider=self.provider_id, window=self.window).set(
                    self.remaining
                )
                return

    @property
    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0


@dataclass
class ProviderGuards:
    """The three per-provider guards, created once per provider at startup."""

    circuit: CircuitBreaker
    limiter: ConcurrencyLimiter
    quota: QuotaTracker


def build_guards(provider_id: str, policy: CircuitPolicy) -> ProviderGuards:
    guards = ProviderGuards(
        circuit=CircuitBreaker(provider_id=provider_id, policy=policy),
        limiter=ConcurrencyLimiter(provider_id=provider_id),
        quota=QuotaTracker(provider_id=provider_id),
    )
    circuit_state.labels(provider=provider_id).set(CircuitState.CLOSED.value)
    return guards
