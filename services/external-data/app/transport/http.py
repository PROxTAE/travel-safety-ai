"""Shared outbound HTTP transport.

Every provider call goes through `ProviderTransport.request`. It owns the
timeout budget, the retry policy, the circuit breaker, the concurrency limit and
the mapping from an HTTP failure to the module's error contract, so no adapter
has to re-implement any of that (or forget to).
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.domain.errors import ProviderError, ProviderErrorCode
from app.observability.logging import get_logger
from app.observability.metrics import (
    provider_errors,
    provider_latency,
    provider_requests,
    provider_retries,
    provider_timeouts,
)
from app.providers.registry import Defaults, ResolvedProvider
from app.transport.resilience import CircuitOpenError, ProviderGuards, build_guards

log = get_logger(__name__)

_USER_AGENT = "travel-safety-ai-external-data/0.1 (+module-04)"


@dataclass(slots=True)
class ProviderResponse:
    """What an adapter gets back. `fetched_at` is the wall clock at receipt and
    is the only honest value for SourceProvenance.fetched_at."""

    payload: Any
    status_code: int
    headers: dict[str, str]
    url: str
    fetched_at: float
    elapsed_seconds: float


def _retry_after_seconds(headers: httpx.Headers) -> float | None:
    """Respect Retry-After. Only the delta-seconds form is handled; the HTTP-date
    form is rare on these providers and a wrong parse would be worse than the
    default backoff."""
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


def _classify(status: int, retry_on: list[int]) -> tuple[ProviderErrorCode, bool]:
    if status in (401, 403):
        return ProviderErrorCode.PROVIDER_AUTH, False
    if status == 429:
        return ProviderErrorCode.PROVIDER_RATE_LIMIT, True
    if status == 402:
        return ProviderErrorCode.PROVIDER_QUOTA, False
    if status == 404:
        return ProviderErrorCode.OUTSIDE_COVERAGE, False
    if status == 408:
        return ProviderErrorCode.PROVIDER_TIMEOUT, True
    if status >= 500:
        return ProviderErrorCode.PROVIDER_OUTAGE, status in retry_on
    return ProviderErrorCode.PROVIDER_SCHEMA_CHANGED, False


class ProviderTransport:
    """One shared httpx client, one set of guards per provider."""

    def __init__(self, defaults: Defaults, client: httpx.AsyncClient | None = None) -> None:
        self._defaults = defaults
        timeout = httpx.Timeout(
            connect=defaults.timeout.connect_seconds,
            read=defaults.timeout.read_seconds,
            write=defaults.timeout.read_seconds,
            pool=defaults.timeout.connect_seconds,
        )
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,  # a redirect off our approved host is an SSRF risk
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        self._guards: dict[str, ProviderGuards] = {}

    def guards_for(self, provider: ResolvedProvider) -> ProviderGuards:
        if provider.id not in self._guards:
            self._guards[provider.id] = build_guards(
                provider.id, self._defaults.circuit_breaker
            )
        return self._guards[provider.id]

    async def aclose(self) -> None:
        await self._client.aclose()

    def build_url(self, provider: ResolvedProvider, path_or_url: str) -> str:
        """Resolve a provider-relative path against its configured base URL.

        User input never reaches this. If an adapter passes an absolute URL it
        must still land on the provider's configured host, otherwise the call is
        refused -- the SSRF invariant in shared context § 11.
        """
        base = provider.base_url
        if path_or_url.startswith(("http://", "https://")):
            candidate = path_or_url
        else:
            if not base:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_OUTAGE,
                    provider.id,
                    message="no base URL configured",
                )
            candidate = urljoin(base.rstrip("/") + "/", path_or_url.lstrip("/"))

        if base:
            base_host = urlsplit(base).netloc
            if urlsplit(candidate).netloc != base_host:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_OUTAGE,
                    provider.id,
                    message="refusing request to a host outside the provider config",
                )
        return candidate

    async def request(
        self,
        provider: ResolvedProvider,
        path_or_url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        deadline_seconds: float | None = None,
        decode_json: bool = True,
    ) -> ProviderResponse:
        """`decode_json=False` returns the response without parsing a body.

        A health probe asks whether the provider is reachable and answering as
        documented; whether the body happens to be JSON is a different question,
        and reporting "schema changed" for an empty 204 would name the wrong
        problem.
        """
        if not provider.is_callable:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_AUTH
                if provider.missing_credentials
                else ProviderErrorCode.OUTSIDE_COVERAGE,
                provider.id,
                message=provider.reason or "provider is not active",
            )

        url = self.build_url(provider, path_or_url)
        guards = self.guards_for(provider)
        retry = self._defaults.retry
        budget = deadline_seconds or self._defaults.timeout.total_seconds
        deadline = time.monotonic() + budget

        last_error: ProviderError | None = None

        for attempt in range(1, retry.max_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                provider_timeouts.labels(provider=provider.id).inc()
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_TIMEOUT,
                    provider.id,
                    message="overall deadline exhausted",
                    retryable=True,
                )

            try:
                await guards.circuit.before_call()
            except CircuitOpenError as exc:
                provider_errors.labels(
                    provider=provider.id, error_code=ProviderErrorCode.PROVIDER_OUTAGE
                ).inc()
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_OUTAGE,
                    provider.id,
                    message="circuit open",
                    retryable=True,
                    retry_after_seconds=exc.retry_after_seconds,
                ) from exc

            started = time.monotonic()
            try:
                async with guards.limiter:
                    response = await self._client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=headers,
                        timeout=httpx.Timeout(
                            connect=min(
                                self._defaults.timeout.connect_seconds, remaining
                            ),
                            read=min(self._defaults.timeout.read_seconds, remaining),
                            write=min(self._defaults.timeout.read_seconds, remaining),
                            pool=min(
                                self._defaults.timeout.connect_seconds, remaining
                            ),
                        ),
                    )
            except asyncio.CancelledError:
                # Upstream gave up; propagate immediately without retrying.
                await guards.circuit.on_failure()
                raise
            except httpx.TimeoutException as exc:
                elapsed = time.monotonic() - started
                provider_latency.labels(provider=provider.id).observe(elapsed)
                provider_timeouts.labels(provider=provider.id).inc()
                await guards.circuit.on_failure()
                last_error = ProviderError(
                    ProviderErrorCode.PROVIDER_TIMEOUT,
                    provider.id,
                    message=str(exc),
                    retryable=True,
                )
            except httpx.HTTPError as exc:
                elapsed = time.monotonic() - started
                provider_latency.labels(provider=provider.id).observe(elapsed)
                await guards.circuit.on_failure()
                last_error = ProviderError(
                    ProviderErrorCode.PROVIDER_OUTAGE,
                    provider.id,
                    message=str(exc),
                    retryable=True,
                )
            else:
                elapsed = time.monotonic() - started
                provider_latency.labels(provider=provider.id).observe(elapsed)
                guards.quota.observe(dict(response.headers))

                if response.is_success:
                    await guards.circuit.on_success()
                    provider_requests.labels(provider=provider.id, outcome="success").inc()
                    return ProviderResponse(
                        payload=_decode(response, provider.id) if decode_json else None,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        url=str(response.url),
                        fetched_at=time.time(),
                        elapsed_seconds=elapsed,
                    )

                code, retryable = _classify(response.status_code, retry.retry_on_status)
                provider_errors.labels(provider=provider.id, error_code=code).inc()
                if code in (
                    ProviderErrorCode.PROVIDER_OUTAGE,
                    ProviderErrorCode.PROVIDER_TIMEOUT,
                    ProviderErrorCode.PROVIDER_RATE_LIMIT,
                ):
                    await guards.circuit.on_failure()
                else:
                    # A 404 or an auth failure says nothing about provider health.
                    await guards.circuit.on_success()

                last_error = ProviderError(
                    code,
                    provider.id,
                    message=f"HTTP {response.status_code}",
                    retryable=retryable,
                    retry_after_seconds=_retry_after_seconds(response.headers),
                    http_status=response.status_code,
                )

            if last_error is None or not last_error.retryable or attempt == retry.max_attempts:
                break

            delay = last_error.retry_after_seconds
            if delay is None:
                delay = retry.initial_backoff_seconds * (2 ** (attempt - 1))
                delay += random.uniform(0, retry.initial_backoff_seconds)  # noqa: S311
            if time.monotonic() + delay >= deadline:
                break

            provider_retries.labels(provider=provider.id).inc()
            log.info(
                "provider_retry",
                provider=provider.id,
                attempt=attempt,
                delay_ms=int(delay * 1000),
                error_code=str(last_error.code),
            )
            await asyncio.sleep(delay)

        assert last_error is not None
        provider_requests.labels(provider=provider.id, outcome="error").inc()
        raise last_error


def _decode(response: httpx.Response, provider_id: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
            provider_id,
            message="response body was not valid JSON",
        ) from exc
