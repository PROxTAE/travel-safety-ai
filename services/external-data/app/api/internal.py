"""Internal API surface.

Health and metrics probes, provider health, plus the geocoding and weather
capabilities. The remaining capability endpoints (disasters, routes, transport,
places, context) arrive with their adapters in Phases 3-6.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.adapters.factory import AdapterRegistry
from app.adapters.open_meteo_geocoding import GeocodeQuery
from app.adapters.open_meteo_weather import CoordinateSample, WeatherQuery
from app.api.deps import InternalAuth
from app.api.envelope import success
from app.api.schemas import (
    DisasterQueryRequest,
    GeocodeSearchRequest,
    WeatherQueryRequest,
)
from app.domain.enums import HealthState, ProviderKind, ProviderStatus
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import DisasterQuery
from app.observability.logging import get_logger
from app.observability.metrics import REGISTRY
from app.providers.registry import ResolvedRegistry
from app.services.dedup import find_duplicate_groups
from app.settings import get_settings

log = get_logger(__name__)

router = APIRouter()
health_router = APIRouter(tags=["health"])


@health_router.get("/health/live")
async def live() -> dict[str, str]:
    """Process liveness only - deliberately touches no dependency, so a database
    blip never triggers a container restart."""
    return {"status": "UP"}


@health_router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: the dependencies this service cannot serve traffic without.

    A failure here means "do not route to me yet", not "restart me" - the
    compose dependency rule requires an unhealthy readiness instead of a crash
    loop when a dependency is temporarily down.
    """
    checks: dict[str, Any] = {}
    state = request.app.state

    cache = getattr(state, "cache", None)
    checks["redis"] = "UP" if cache is not None and await cache.ping() else "DOWN"

    engine = getattr(state, "engine", None)
    if engine is None:
        checks["postgres"] = "DOWN"
    else:
        try:
            from sqlalchemy import text

            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            checks["postgres"] = "UP"
        except Exception:  # readiness reports a failure, it never raises
            checks["postgres"] = "DOWN"

    # An unset internal token is a configuration failure, not a transient one:
    # every internal route would reject every caller, so we are not ready.
    checks["internal_auth"] = (
        "UP" if get_settings().internal_service_token is not None else "NOT_CONFIGURED"
    )

    registry: ResolvedRegistry | None = getattr(state, "registry", None)
    checks["provider_registry"] = "UP" if registry is not None else "DOWN"

    # The registry file being readable says nothing about whether its rows
    # reached the database. Until they have, every health observation fails its
    # foreign key and /internal/v1/providers/health can only ever answer
    # UNKNOWN - so report NOT ready, and keep retrying the mirror here rather
    # than waiting for someone to restart the container.
    repo = getattr(state, "repo", None)
    if getattr(state, "registry_synced", False):
        checks["registry_mirror"] = "UP"
    elif repo is None or registry is None:
        checks["registry_mirror"] = "DOWN"
    else:
        try:
            await repo.sync_registry(registry)
        except Exception as exc:
            log.warning("registry_sync_retry_failed", error_type=type(exc).__name__)
            checks["registry_mirror"] = "DOWN"
        else:
            state.registry_synced = True
            log.info("registry_synced_on_readiness")
            checks["registry_mirror"] = "UP"

    ok = all(value == "UP" for value in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "UP" if ok else "DOWN", "checks": checks},
    )


@health_router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@router.get("/internal/v1/providers/health")
async def providers_health(request: Request, _: InternalAuth) -> dict[str, Any]:
    """Per-provider status, latency and quota. Never a credential, never a raw
    provider body - the plan is explicit that this endpoint leaks nothing."""
    registry: ResolvedRegistry = request.app.state.registry
    transport = request.app.state.transport

    from app.transport.resilience import CircuitState

    # Real observations, written by an adapter after a fetch. A provider with no
    # row here has never been reached, so its state is UNKNOWN - reporting UP
    # from configuration alone would be an assumption, and modules 03/05 route
    # requests on this answer.
    observed: dict[str, Any] = {}
    repo = getattr(request.app.state, "repo", None)
    if repo is not None:
        try:
            observed = {row.provider_id: row for row in await repo.list_health()}
        except Exception as exc:
            # Readiness reports the database separately; here an unreachable DB
            # simply means we have no observations.
            log.warning("health_lookup_failed", error_type=type(exc).__name__)

    providers: list[dict[str, Any]] = []
    degraded: list[str] = []

    for resolved in registry.all():
        entry = resolved.entry
        checked_at: str | None = None

        if resolved.effective_status is not ProviderStatus.ACTIVE:
            state = (
                HealthState.NOT_CONFIGURED
                if resolved.missing_credentials
                else HealthState.UNKNOWN
            )
            quota = None
        else:
            guards = transport.guards_for(resolved)
            quota = guards.quota.remaining
            row = observed.get(resolved.id)
            if guards.circuit.state is CircuitState.OPEN:
                state = HealthState.CIRCUIT_OPEN
            elif row is None:
                state = HealthState.UNKNOWN
            else:
                state = HealthState(row.status)
                checked_at = row.checked_at.isoformat()

        if state is not HealthState.UP:
            degraded.append(resolved.id)

        providers.append(
            {
                "provider": resolved.id,
                "kind": str(entry.kind),
                "registry_status": str(entry.status),
                "effective_status": str(resolved.effective_status),
                "health": str(state),
                "last_checked_at": checked_at,
                "quota_remaining": quota,
                "quota_verified": not entry.quota.verification_required,
                "authority": str(entry.authority),
                "attribution": entry.attribution.text,
                # Names only. The value never leaves the process.
                "missing_credentials": resolved.missing_credentials,
                "reason": resolved.reason,
            }
        )

    return success({"providers": providers}, degraded=degraded)


@router.post("/internal/v1/geocode/search")
async def geocode_search(
    request: Request, body: GeocodeSearchRequest, _: InternalAuth
) -> dict[str, Any]:
    """Resolve a place name to canonical LocationRefs.

    A blocked provider raises OUTSIDE_COVERAGE from the adapter registry, which
    the app maps to UNSUPPORTED_COVERAGE. An empty `results` list means the
    provider answered and found nothing - it never means "unavailable".
    """
    adapters: AdapterRegistry = request.app.state.adapters
    registry: ResolvedRegistry = request.app.state.registry

    adapter = adapters.for_kind(ProviderKind.GEOCODING)
    results = await adapter.query(
        GeocodeQuery(
            name=body.query,
            count=body.count,
            language=body.language,
            country_code=body.country_code,
        )
    )

    return success(
        {
            "results": [result.model_dump(mode="json") for result in results],
            "attribution": registry.attributions([adapter.provider_id]),
        }
    )


@router.post("/internal/v1/weather/query")
async def weather_query(
    request: Request, body: WeatherQueryRequest, _: InternalAuth
) -> dict[str, Any]:
    """Forecast for a set of route samples.

    A sample carrying an `eta` yields one point at the nearest forecast hour; a
    sample without one yields every hour inside the window. Points beyond the
    provider budget are dropped by even downsampling, and the surviving records
    carry the reduced `quality.coverage`.
    """
    adapters: AdapterRegistry = request.app.state.adapters
    registry: ResolvedRegistry = request.app.state.registry

    adapter = adapters.for_kind(ProviderKind.WEATHER)
    forecasts = await adapter.query(
        WeatherQuery(
            samples=[
                CoordinateSample(
                    latitude=sample.latitude,
                    longitude=sample.longitude,
                    eta=sample.eta,
                    sample_id=sample.sample_id,
                )
                for sample in body.samples
            ],
            start=body.start,
            end=body.end,
        )
    )

    return success(
        {
            "forecasts": [point.model_dump(mode="json") for point in forecasts],
            "requested_samples": len(body.samples),
            "attribution": registry.attributions([adapter.provider_id]),
        }
    )


@router.post("/internal/v1/disasters/query")
async def disasters_query(
    request: Request, body: DisasterQueryRequest, _: InternalAuth
) -> dict[str, Any]:
    """Hazard events from every configured disaster source.

    The sources are complementary, not interchangeable: the same earthquake
    appears in more than one of them, and the plan forbids dropping a duplicate
    here. Everything each source returned is emitted with its own provenance,
    and module 05 resolves them.

    If one source fails the answer is still returned, with that source named in
    `meta.degraded_services`. If *every* source fails the request fails - an
    empty list would read as "no hazards", which is the one answer this module
    must never invent.
    """
    adapters: AdapterRegistry = request.app.state.adapters
    registry: ResolvedRegistry = request.app.state.registry

    available = adapters.all_for_kind(ProviderKind.DISASTER)
    if not available:
        raise ProviderError(
            ProviderErrorCode.OUTSIDE_COVERAGE,
            provider_id=str(ProviderKind.DISASTER),
            message=adapters.blocked_reason(ProviderKind.DISASTER),
        )

    query = DisasterQuery(
        bbox=body.bbox,
        start=body.start,
        end=body.end,
        event_types=list(body.event_types),
        min_magnitude=body.min_magnitude,
    )

    events: list[Any] = []
    answered: list[str] = []
    degraded: list[str] = []
    not_applicable: list[str] = []
    last_error: ProviderError | None = None

    # Fan out in parallel (shared context § 7): the sources are independent, so
    # the total cost should be the slowest of them, not the sum. Sequentially
    # this endpoint took 12s for a global query and 20s when one source timed
    # out, because every later source waited out the earlier one's deadline.
    results = await asyncio.gather(
        *(adapter.query(query) for adapter in available), return_exceptions=True
    )

    for adapter, result in zip(available, results, strict=True):
        if isinstance(result, ProviderError):
            last_error = result
            if result.code is ProviderErrorCode.OUTSIDE_COVERAGE:
                # "This source publishes nothing about that" is not a failure.
                # Counting it as degraded would mark USGS degraded on every
                # flood query, and a field that is always set stops carrying
                # information.
                not_applicable.append(adapter.provider_id)
            else:
                degraded.append(adapter.provider_id)
                log.warning(
                    "disaster_source_failed",
                    provider=adapter.provider_id,
                    error_code=str(result.code),
                )
        elif isinstance(result, BaseException):
            # Not a provider failure - a bug, or the caller cancelling. Neither
            # should be quietly recorded as "that source is a bit degraded".
            raise result
        else:
            events.extend(result)
            answered.append(adapter.provider_id)

    if not answered:
        assert last_error is not None
        # Every source failing and every source being irrelevant are different
        # answers: one is "we could not find out", the other is "nobody
        # publishes this". `last_error` already distinguishes them.
        raise last_error

    events.sort(key=lambda event: event.effective_at, reverse=True)

    # Grouped, never merged: every event is still emitted below. Module 05 owns
    # the decision about which record of a duplicate pair to believe, and it
    # cannot make that decision about records it never received.
    duplicate_groups = find_duplicate_groups(events)

    return success(
        {
            "events": [event.model_dump(mode="json") for event in events],
            "duplicate_groups": [group.as_dict() for group in duplicate_groups],
            "sources": answered,
            # Named so a consumer can tell "nobody asked" from "nobody answered".
            "sources_not_covering_query": not_applicable,
            "attribution": registry.attributions(answered),
        },
        degraded=degraded,
    )
