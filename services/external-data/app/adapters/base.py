"""Common adapter interface.

Mirrors the concept list in the module plan:

    provider_name/version/kind
    coverage(query)      -> supported / unsupported + reason
    build_request(query) -> approved URL + params
    fetch(request)       -> provider response          (shared transport)
    validate(response)   -> typed provider model
    normalize(model)     -> canonical records
    provenance(response) -> SourceProvenance
    health()             -> ProviderHealth

Phase 1 ships the protocol, the coverage/provenance/health machinery and the
cache-aware fetch loop. Concrete adapters arrive in Phases 2-5.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar

from app.cache.provider_cache import ProviderCache, build_key
from app.domain.canonical import SourceProvenance, content_hash
from app.domain.enums import HealthState, ProviderStatus
from app.domain.errors import ProviderError, ProviderErrorCode
from app.observability.logging import get_logger
from app.providers.registry import ResolvedProvider
from app.transport.http import ProviderResponse, ProviderTransport

log = get_logger(__name__)

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
    ) -> None:
        self.provider = provider
        self.transport = transport
        self.cache = cache
        self.env = env

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
    def normalize(self, model: Any, response: ProviderResponse) -> list[RecordT]:
        """Provider model -> canonical records, units and time converted."""

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
            records = self.normalize(model, response)
        except ProviderError:
            if self.cache is not None and cache_key is not None:
                negative_ttl = self.provider.entry.cache.negative_ttl_seconds or 30
                await self.cache.set_negative(cache_key, self.provider_id, negative_ttl)
            raise
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

    # Adapters holding Pydantic records override these two; the defaults keep
    # plain dict payloads working without ceremony.
    def _dehydrate(self, records: list[RecordT]) -> Any:
        return [
            record.model_dump(mode="json") if hasattr(record, "model_dump") else record
            for record in records
        ]

    def _rehydrate(self, payload: Any) -> list[RecordT]:
        return list(payload)
