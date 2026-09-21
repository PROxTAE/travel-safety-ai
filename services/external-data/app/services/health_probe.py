"""Periodic provider health probing.

Without this, `provider.health` only gains a row when a real request happens to
reach a provider — so a provider served entirely from cache stays `UNKNOWN`
forever, and one that went down between requests keeps its last good reading.
Both were flagged in review; this closes them.

The probe deliberately goes through the shared transport rather than a private
client. Health should describe the path real requests take: the same timeouts,
the same circuit breaker, the same quota accounting. A probe that succeeded on a
route real traffic does not use would be a comfortable lie.
"""

from __future__ import annotations

import asyncio
import time

from app.adapters.base import HealthRecorder
from app.domain.enums import HealthState, ProviderStatus
from app.domain.errors import ProviderError, ProviderErrorCode
from app.observability.logging import get_logger
from app.providers.registry import ResolvedProvider, ResolvedRegistry
from app.transport.http import ProviderTransport

log = get_logger(__name__)

# How a failed probe is described. Same split the adapters use: an auth failure
# means our configuration is wrong, a timeout means the provider is.
_STATE_BY_ERROR = {
    ProviderErrorCode.PROVIDER_AUTH: HealthState.NOT_CONFIGURED,
    ProviderErrorCode.PROVIDER_TIMEOUT: HealthState.DOWN,
    ProviderErrorCode.PROVIDER_OUTAGE: HealthState.DOWN,
    ProviderErrorCode.PROVIDER_QUOTA: HealthState.DEGRADED,
    ProviderErrorCode.PROVIDER_RATE_LIMIT: HealthState.DEGRADED,
    ProviderErrorCode.PROVIDER_SCHEMA_CHANGED: HealthState.DEGRADED,
    ProviderErrorCode.OUTSIDE_COVERAGE: HealthState.UP,
    ProviderErrorCode.LICENSE_RESTRICTION: HealthState.UP,
}


class ProviderHealthProbe:
    """Probes every callable provider that declares a `health.url`."""

    def __init__(
        self,
        registry: ResolvedRegistry,
        transport: ProviderTransport,
        recorder: HealthRecorder,
        *,
        interval_seconds: float,
        probe_timeout_seconds: float = 10.0,
    ) -> None:
        self._registry = registry
        self._transport = transport
        self._recorder = recorder
        self._interval = interval_seconds
        self._timeout = probe_timeout_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return self._interval > 0

    def targets(self) -> list[ResolvedProvider]:
        """Only providers we are allowed to call and that told us how to check.

        A blocked provider is deliberately not probed: its state is already
        known from configuration, and calling a provider the Lead has not
        approved would be the exact thing the registry gate exists to prevent.
        """
        return [
            provider
            for provider in self._registry.all()
            if provider.effective_status is ProviderStatus.ACTIVE and provider.entry.health.url
        ]

    async def probe_once(self) -> dict[str, HealthState]:
        """One pass over every target. Never raises."""
        results: dict[str, HealthState] = {}
        for provider in self.targets():
            results[provider.id] = await self._probe(provider)
        return results

    async def _probe(self, provider: ResolvedProvider) -> HealthState:
        probe = provider.entry.health
        assert probe.url is not None
        started = time.monotonic()

        try:
            response = await self._transport.request(
                provider,
                probe.url,
                method=probe.method,
                deadline_seconds=self._timeout,
                # Reachability and status only. A health endpoint that answers
                # 204, or text, is still healthy.
                decode_json=False,
            )
        except ProviderError as exc:
            state = _STATE_BY_ERROR.get(exc.code, HealthState.DEGRADED)
            await self._record(provider, state, None, reason=str(exc.code))
            return state
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a probe must never take the service with it
            log.warning(
                "health_probe_error",
                provider=provider.id,
                error_type=type(exc).__name__,
            )
            await self._record(provider, HealthState.DOWN, None, reason=type(exc).__name__)
            return HealthState.DOWN

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code != probe.expect_status:
            # Reachable but not answering as documented. That is degraded, not
            # healthy, and not down either.
            await self._record(
                provider,
                HealthState.DEGRADED,
                latency_ms,
                reason=f"expected HTTP {probe.expect_status}, got {response.status_code}",
            )
            return HealthState.DEGRADED

        await self._record(provider, HealthState.UP, latency_ms, reason=None)
        return HealthState.UP

    async def _record(
        self,
        provider: ResolvedProvider,
        state: HealthState,
        latency_ms: int | None,
        *,
        reason: str | None,
    ) -> None:
        try:
            await self._recorder.upsert_health(
                provider_id=provider.id,
                state=state,
                latency_ms=latency_ms,
                quota_remaining=self._transport.guards_for(provider).quota.remaining,
                reason=reason,
            )
        except Exception as exc:  # the observation is a side effect
            log.warning(
                "health_probe_record_failed",
                provider=provider.id,
                error_type=type(exc).__name__,
            )

    async def _loop(self) -> None:
        # Probe immediately so the first readiness check after a boot already
        # has real observations rather than a table full of UNKNOWN.
        while True:
            try:
                results = await self.probe_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("health_probe_pass_failed", error_type=type(exc).__name__)
            else:
                log.info(
                    "health_probe_pass",
                    providers=len(results),
                    up=sum(1 for s in results.values() if s is HealthState.UP),
                )
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if not self.enabled:
            log.info("health_probe_disabled")
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="provider-health-probe")
        log.info("health_probe_started", interval_seconds=self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
