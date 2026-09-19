"""Common adapter interface.

Mirrors the concept list in the module plan:

    provider_name/version/kind
    coverage(query)      -> supported / unsupported + reason
    build_request(query) -> approved URL + params
    fetch(request)       -> provider response          (shared transport)
    validate(response)   -> typed provider model
    normalize(model, query) -> canonical records
    provenance(response) -> SourceProvenance
    health()             -> ProviderHealth

Phase 1 ships the protocol, the coverage/provenance/health machinery and the
cache-aware fetch loop. Concrete adapters arrive in Phases 2-5.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, Protocol, TypeVar

from app.cache.provider_cache import ProviderCache, build_key
from app.domain.canonical import SourceProvenance, content_hash
from app.domain.enums import HealthState, ProviderStatus
from app.domain.errors import ProviderError, ProviderErrorCode
from app.observability.logging import get_logger
from app.providers.registry import ResolvedProvider
from app.transport.http import ProviderResponse, ProviderTransport

log = get_logger(__name__)

# An auth failure says our configuration is wrong; a timeout or outage says the
# provider is down; a quota or schema problem means it answered, badly.
_HEALTH_BY_ERROR = {
    ProviderErrorCode.PROVIDER_AUTH: HealthState.NOT_CONFIGURED,
    ProviderErrorCode.PROVIDER_TIMEOUT: HealthState.DOWN,
    ProviderErrorCode.PROVIDER_OUTAGE: HealthState.DOWN,
    ProviderErrorCode.PROVIDER_QUOTA: HealthState.DEGRADED,
    ProviderErrorCode.PROVIDER_RATE_LIMIT: HealthState.DEGRADED,
    ProviderErrorCode.PROVIDER_SCHEMA_CHANGED: HealthState.DEGRADED,
    ProviderErrorCode.OUTSIDE_COVERAGE: HealthState.UP,
    ProviderErrorCode.LICENSE_RESTRICTION: HealthState.UP,
}

QueryT = TypeVar("QueryT")
RecordT = TypeVar("RecordT")


@dataclass(slots=True)
class CoverageDecision:
    supported: bool
    reason: str | None = None


@dataclass(slots=True)
class ProviderRequest:
    """An approved outbound call. Built only from config plus validated query
    fields, never from a caller-supplied URL."""

    path_or_url: str
    method: str = "GET"
    params: dict[str, Any] | None = None
    json_body: Any | None = None
    headers: dict[str, str] | None = None
    cache_key_fields: dict[str, Any] | None = None


class HealthRecorder(Protocol):
    """Writes an observed provider state. Implemented by ProviderRepository.

    Kept as a protocol so an adapter never imports the persistence layer, and so
    a caller that has no database can simply pass nothing.
    """

    async def upsert_health(
        self,
        *,
        provider_id: str,
        state: HealthState,
        latency_ms: int | None = None,
        quota_remaining: int | None = None,
        reason: str | None = None,
    ) -> None: ...


@dataclass(slots=True)
class ProviderHealthReport:
    provider_id: str
    state: HealthState
    latency_ms: int | None = None
    quota_remaining: int | None = None
    reason: str | None = None


class ProviderAdapter(abc.ABC, Generic[QueryT, RecordT]):
    """Base class shared by every provider adapter."""

    def __init__(
        self,
        provider: ResolvedProvider,
        transport: ProviderTransport,
        cache: ProviderCache | None = None,
        *,
        env: str = "development",
        health_recorder: HealthRecorder | None = None,
    ) -> None:
        self.provider = provider
        self.transport = transport
        self.cache = cache
        self.env = env
        self.health_recorder = health_recorder

    # ------------------------------------------------------------- identity
    @property
    def provider_id(self) -> str:
        return self.provider.id

    @property
    def kind(self) -> str:
        return str(self.provider.entry.kind)

    @property
    def schema_version(self) -> str:
        return "1.0.0"

    # ------------------------------------------------------------- contract
    @abc.abstractmethod
    def coverage(self, query: QueryT) -> CoverageDecision:
        """Can this provider answer this query at all?"""

    @abc.abstractmethod
    def build_request(self, query: QueryT) -> ProviderRequest:
        """Turn a canonical query into an approved provider request."""

    @abc.abstractmethod
    def validate(self, response: ProviderResponse) -> Any:
        """Parse into a typed provider model, or raise PROVIDER_SCHEMA_CHANGED."""

    @abc.abstractmethod
    def normalize(
        self, model: Any, response: ProviderResponse, query: QueryT
    ) -> list[RecordT]:
        """Provider model -> canonical records, units and time converted.

        The query is passed explicitly rather than stashed on the adapter: one
        adapter instance serves every request, and there is an `await` between
        building the request and normalising the response. Anything kept on
        `self` across that await belongs to whichever request wrote it last.
        """

    # ------------------------------------------------------------ machinery
    def provenance(
        self,
        response: ProviderResponse,
        *,
        provider_record_id: str | None = None,
        observed_at: datetime | None = None,
        published_at: datetime | None = None,
        source_url: str | None = None,
        payload_for_hash: Any | None = None,
    ) -> SourceProvenance:
        fetched_at = datetime.fromtimestamp(response.fetched_at, tz=UTC)
        ttl = self.provider.entry.cache.effective_ttl
        return SourceProvenance(
            source_id=f"{self.provider_id}:{provider_record_id or response.url}",
            provider=self.provider_id,
            provider_record_id=provider_record_id,
            authority=self.provider.entry.authority,
            source_url=source_url or response.url,
            license=self.provider.entry.license.spdx_or_name,
            observed_at=observed_at,
            published_at=published_at,
            fetched_at=fetched_at,
            expires_at=fetched_at + timedelta(seconds=ttl),
            content_hash=content_hash(payload_for_hash)
            if payload_for_hash is not None
            else None,
            schema_version=self.schema_version,
        )

    def health(self) -> ProviderHealthReport:
        """Registry-level health. A live probe is a separate, explicit call so
        that rendering a health page never fans out to every provider."""
        if self.provider.effective_status is not ProviderStatus.ACTIVE:
            state = (
                HealthState.NOT_CONFIGURED
                if self.provider.missing_credentials
                else HealthState.UNKNOWN
            )
            return ProviderHealthReport(
                provider_id=self.provider_id,
                state=state,
                reason=self.provider.reason,
            )
        guards = self.transport.guards_for(self.provider)
        from app.transport.resilience import CircuitState

        if guards.circuit.state is CircuitState.OPEN:
            return ProviderHealthReport(
                provider_id=self.provider_id,
                state=HealthState.CIRCUIT_OPEN,
                quota_remaining=guards.quota.remaining,
                reason="circuit open after repeated failures",
            )
        return ProviderHealthReport(
            provider_id=self.provider_id,
            state=HealthState.UP,
            quota_remaining=guards.quota.remaining,
        )

    async def fetch(
        self, request: ProviderRequest, *, deadline_seconds: float | None = None
    ) -> ProviderResponse:
        return await self.transport.request(
            self.provider,
            request.path_or_url,
            method=request.method,
            params=request.params,
            json_body=request.json_body,
            headers=request.headers,
            deadline_seconds=deadline_seconds,
        )

    async def query(
        self, query: QueryT, *, deadline_seconds: float | None = None
    ) -> list[RecordT]:
        """coverage -> cache -> fetch -> validate -> normalize."""
        decision = self.coverage(query)
        if not decision.supported:
            raise ProviderError(
                ProviderErrorCode.OUTSIDE_COVERAGE,
                self.provider_id,
                message=decision.reason or "outside coverage",
            )

        request = self.build_request(query)
        cache_key: str | None = None

        if self.cache is not None and request.cache_key_fields is not None:
            cache_key = build_key(
                env=self.env,
                provider_id=self.provider_id,
                schema_version=self.schema_version,
                key_fields=request.cache_key_fields,
            )
            hit = await self.cache.get(cache_key, self.provider_id)
            if hit is not None:
                if hit.negative:
                    raise ProviderError(
                        ProviderErrorCode.PROVIDER_OUTAGE,
                        self.provider_id,
                        message="recent failure is cached",
                        retryable=True,
                    )
                return self._rehydrate(hit.payload)

            # Stampede guard: only the lock holder calls the provider.
            if not await self.cache.acquire_lock(cache_key, self.provider_id):
                waited = await self.cache.wait_for_other_fetch(cache_key, self.provider_id)
                if waited is not None and not waited.negative:
                    return self._rehydrate(waited.payload)

        try:
            response = await self.fetch(request, deadline_seconds=deadline_seconds)
            model = self.validate(response)
            records = self.normalize(model, response, query)
        except ProviderError as error:
            await self._record_observation(error=error)
            if self.cache is not None and cache_key is not None:
                negative_ttl = self.provider.entry.cache.negative_ttl_seconds or 30
                await self.cache.set_negative(cache_key, self.provider_id, negative_ttl)
            raise
        else:
            await self._record_observation(response=response)
        finally:
            if self.cache is not None and cache_key is not None:
                await self.cache.release_lock(cache_key)

        if self.cache is not None and cache_key is not None:
            await self.cache.set(
                cache_key,
                self.provider_id,
                self._dehydrate(records),
                self.provider.entry.cache.effective_ttl,
            )
        return records

    async def _record_observation(
        self,
        *,
        response: ProviderResponse | None = None,
        error: ProviderError | None = None,
    ) -> None:
        """Persist what this call actually observed about the provider.

        This is what turns /internal/v1/providers/health from a restatement of
        configuration into a report of reality. Best-effort on purpose: a
        database problem must not fail a request whose data already arrived.
        """
        if self.health_recorder is None:
            return

        if error is not None:
            state = _HEALTH_BY_ERROR.get(error.code, HealthState.DEGRADED)
            latency_ms = None
            reason = str(error.code)
        else:
            assert response is not None
            state = HealthState.UP
            latency_ms = int(response.elapsed_seconds * 1000)
            reason = None

        try:
            await self.health_recorder.upsert_health(
                provider_id=self.provider_id,
                state=state,
                latency_ms=latency_ms,
                quota_remaining=self.transport.guards_for(self.provider).quota.remaining,
                reason=reason,
            )
        except Exception as exc:  # the observation is a side effect, not the answer
            log.warning(
                "health_record_failed",
                provider=self.provider_id,
                error_type=type(exc).__name__,
            )

    # Adapters holding Pydantic records override these two; the defaults keep
    # plain dict payloads working without ceremony.
    def _dehydrate(self, records: list[RecordT]) -> Any:
        return [
            record.model_dump(mode="json") if hasattr(record, "model_dump") else record
            for record in records
        ]

    def _rehydrate(self, payload: Any) -> list[RecordT]:
        return list(payload)
