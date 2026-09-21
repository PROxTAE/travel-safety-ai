"""Internal API surface.

Health and metrics probes, provider health, plus the geocoding and weather
capabilities, plus disasters, routes, the emergency directory and the combined
context fan-out, and live transit for the registered agency feeds. Flight is
the one capability module 04 does not answer: serving Amadeus test data as a
real result is forbidden by the shared context, so it stays UNAVAILABLE.
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
    CONTEXT_CAPABILITIES,
    ContextQueryRequest,
    DisasterQueryRequest,
    GeocodeSearchRequest,
    NearbyPlacesRequest,
    RouteQueryRequest,
    TransitQueryRequest,
    WeatherQueryRequest,
)
from app.domain.enums import HealthState, ProviderKind, ProviderStatus
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import (
    DisasterQuery,
    NearbyPlacesQuery,
    RouteQuery,
    TransitQuery,
)
from app.observability.logging import get_logger
from app.observability.metrics import (
    REGISTRY,
    context_capabilities,
    degraded_results,
)
from app.providers.registry import ResolvedRegistry
from app.services.context import (
    CapabilityCall,
    CapabilityResult,
    ContextGatherer,
    Outcome,
)
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
                HealthState.NOT_CONFIGURED if resolved.missing_credentials else HealthState.UNKNOWN
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


@router.post("/internal/v1/routes/query")
async def routes_query(
    request: Request, body: RouteQueryRequest, _: InternalAuth
) -> dict[str, Any]:
    """Raw-canonical road routes (contract § 5.2).

    "Raw" is the important word. The routes come back with geometry, distance,
    duration and turn instructions, and with `exposure` null and `risk_level`
    UNKNOWN, because a routing engine has no view on hazards. Ranking them is
    `/routes/evaluate` in module 05, after the corridor has been intersected
    with weather and disaster events.

    A coordinate with no road near it is a coverage answer, not an outage: the
    provider says so explicitly (error 2010) and it arrives as
    UNSUPPORTED_COVERAGE with the provider's own explanation.
    """
    adapters: AdapterRegistry = request.app.state.adapters
    registry: ResolvedRegistry = request.app.state.registry

    adapter = adapters.for_kind(ProviderKind.ROUTE)
    query = RouteQuery(
        waypoints=[(lon, lat) for lon, lat in body.waypoints],
        mode=body.mode,
        alternatives=body.alternatives,
        avoid_polygons=body.avoid_polygons,
        preference=body.preference,
        departure_at=body.departure_at,
        language=body.language,
    )
    routes = await adapter.query(query)

    return success(
        {
            "routes": [route.model_dump(mode="json") for route in routes],
            "requested_waypoints": len(body.waypoints),
            "attribution": registry.attributions([adapter.provider_id]),
        }
    )


@router.post("/internal/v1/places/nearby")
async def places_nearby(
    request: Request, body: NearbyPlacesRequest, _: InternalAuth
) -> dict[str, Any]:
    """Police, hospitals and embassies near a coordinate (contract § 5.2).

    Two things a consumer of this endpoint must carry through to the user:

    An empty list means nothing is tagged in OpenStreetMap within the radius.
    It does not mean there is no hospital there, and it must never be rendered
    as "no help nearby".

    This is not an official emergency directory. The shared context is explicit
    about it, the records carry quality flags saying which fields are missing,
    and embassies in particular are flagged as unreliable on every record.
    """
    adapters: AdapterRegistry = request.app.state.adapters
    registry: ResolvedRegistry = request.app.state.registry

    adapter = adapters.for_kind(ProviderKind.EMERGENCY_DIRECTORY)
    query = NearbyPlacesQuery(
        longitude=body.longitude,
        latitude=body.latitude,
        radius_m=body.radius_m,
        place_types=list(body.place_types),
        limit=body.limit,
        language=body.language,
    )
    places = await adapter.query(query)

    return success(
        {
            "places": [place.model_dump(mode="json") for place in places],
            "searched_radius_m": body.radius_m,
            # Said out loud in the payload, not only in a doc comment, because
            # whoever renders this may never read the doc.
            "directory_caveat": (
                "community-maintained OpenStreetMap data; not an official "
                "emergency directory and not a substitute for local emergency "
                "numbers"
            ),
            "attribution": registry.attributions([adapter.provider_id]),
        }
    )


@router.post("/internal/v1/context/query")
async def context_query(
    request: Request, body: ContextQueryRequest, _: InternalAuth
) -> dict[str, Any]:
    """Everything module 04 knows about one journey, in one call (contract § 5.2).

    The capabilities run concurrently under a single deadline. One that overruns
    is cancelled and reported as timed out; the rest of the answer still comes
    back, because a traveller waiting on a hazard check should not lose the
    weather because a routing provider is slow.

    Every capability appears in `capabilities[]` with what happened to it, even
    the ones that answered nothing. An absent key would be indistinguishable
    from "nothing to report", and for hazards those are opposite answers.

    Nothing here is combined into a verdict. This endpoint concatenates records
    and says where each came from; building `IntegratedTravelContext` out of
    them is module 05 (shared context § 7 step 5), and judging them is 06/07.
    """
    adapters: AdapterRegistry = request.app.state.adapters
    registry: ResolvedRegistry = request.app.state.registry

    requested = _requested_capabilities(body)
    plan: dict[ProviderKind, CapabilityCall] = {}
    unavailable: dict[ProviderKind, str] = {}

    for kind in requested:
        call = _capability_call(adapters, kind, body)
        if isinstance(call, str):
            unavailable[kind] = call
        else:
            plan[kind] = call

    gatherer = ContextGatherer(adapters)
    result = await gatherer.gather(
        plan,
        deadline_seconds=body.deadline_seconds,
        skipped=[kind for kind in CONTEXT_CAPABILITIES if kind not in requested],
    )

    for kind, reason in unavailable.items():
        result.capabilities[kind] = CapabilityResult(
            kind=kind, outcome=Outcome.UNAVAILABLE, reason=reason
        )
        context_capabilities.labels(
            capability=str(kind), outcome=str(Outcome.UNAVAILABLE).lower()
        ).inc()

    degraded = result.degraded_services
    if degraded:
        degraded_results.labels(capability="context").inc()

    return success(
        {
            "weather": [
                record.model_dump(mode="json") for record in result.records(ProviderKind.WEATHER)
            ],
            "disaster_events": [
                record.model_dump(mode="json") for record in result.records(ProviderKind.DISASTER)
            ],
            "routes": [
                record.model_dump(mode="json") for record in result.records(ProviderKind.ROUTE)
            ],
            "transport": [
                record.model_dump(mode="json") for record in result.records(ProviderKind.TRANSIT)
            ],
            "places": [
                record.model_dump(mode="json")
                for record in result.records(ProviderKind.EMERGENCY_DIRECTORY)
            ],
            # Grouped, never merged - every record above is still present.
            "duplicate_groups": [group.as_dict() for group in result.duplicate_groups],
            # What happened to each capability, including the ones that did not
            # run. This is the part a caller must read before rendering.
            "capabilities": [
                result.capabilities[kind].as_dict()
                for kind in CONTEXT_CAPABILITIES
                if kind in result.capabilities
            ],
            "provider_health": _health_snapshot(adapters, registry),
            "attribution": registry.attributions(result.answering_providers),
        },
        degraded=degraded,
    )


def _requested_capabilities(body: ContextQueryRequest) -> list[ProviderKind]:
    """What to ask, from what was sent.

    Naming a capability explicitly always wins; otherwise the inputs decide, so
    that a caller who sent no waypoints is not charged a routing call against a
    200-a-day quota.
    """
    if body.include:
        return list(dict.fromkeys(body.include))

    wanted: list[ProviderKind] = []
    if body.samples:
        wanted.append(ProviderKind.WEATHER)
    # Hazards are the reason this service exists; a bbox or a journey is enough.
    wanted.append(ProviderKind.DISASTER)
    if body.waypoints:
        wanted.append(ProviderKind.ROUTE)
    # Transit coverage is per agency, so it is only worth asking when the query
    # says where it is about. Without a box the adapter would answer
    # OUTSIDE_COVERAGE for every request.
    if body.bbox:
        wanted.append(ProviderKind.TRANSIT)
    if body.place_types or body.places_near:
        wanted.append(ProviderKind.EMERGENCY_DIRECTORY)
    return wanted


def _places_anchor(body: ContextQueryRequest) -> tuple[float, float] | None:
    """Where to look for hospitals and police.

    The destination by default: that is where a traveller who needs them will
    be, and the origin is usually home.
    """
    if body.places_near is not None:
        return (body.places_near.longitude, body.places_near.latitude)
    if body.waypoints:
        return body.waypoints[-1]
    if body.samples:
        last = body.samples[-1]
        return (last.longitude, last.latitude)
    return None


def _disaster_call(adapters: AdapterRegistry, body: ContextQueryRequest) -> CapabilityCall | str:
    available = adapters.all_for_kind(ProviderKind.DISASTER)
    if not available:
        return adapters.blocked_reason(ProviderKind.DISASTER)

    query = DisasterQuery(
        bbox=body.bbox,
        start=body.start,
        end=body.end,
        event_types=list(body.event_types),
    )

    async def run(budget: float) -> tuple[list[Any], list[str]]:
        # The disaster sources are complementary, not interchangeable: the same
        # earthquake appears in more than one, so all of them are asked and
        # everything they return is emitted.
        results = await asyncio.gather(
            *(adapter.query(query, deadline_seconds=budget) for adapter in available),
            return_exceptions=True,
        )
        events: list[Any] = []
        answered: list[str] = []
        last_error: ProviderError | None = None
        for adapter, outcome in zip(available, results, strict=True):
            if isinstance(outcome, ProviderError):
                last_error = outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                events.extend(outcome)
                answered.append(adapter.provider_id)
        if not answered and last_error is not None:
            # Every source failing is not the same as no hazards, and an empty
            # list is the one answer this module must never invent.
            raise last_error
        events.sort(key=lambda event: event.effective_at, reverse=True)
        return events, answered

    return run


def _capability_call(
    adapters: AdapterRegistry, kind: ProviderKind, body: ContextQueryRequest
) -> CapabilityCall | str:
    """Bind one capability to a callable, or say why it cannot run.

    Returning the reason as a string rather than raising keeps an unconfigured
    provider out of the concurrent fan-out entirely: there is nothing to wait
    for, and the caller still learns exactly what is missing.
    """
    if kind is ProviderKind.DISASTER:
        return _disaster_call(adapters, body)

    try:
        adapter = adapters.for_kind(kind)
    except ProviderError as error:
        return error.message

    if kind is ProviderKind.WEATHER:
        weather_query = WeatherQuery(
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

        async def weather(budget: float) -> tuple[list[Any], list[str]]:
            records = await adapter.query(weather_query, deadline_seconds=budget)
            return list(records), [adapter.provider_id]

        return weather

    if kind is ProviderKind.TRANSIT:
        transit_query = TransitQuery(bbox=body.bbox, limit=50)

        async def transit(budget: float) -> tuple[list[Any], list[str]]:
            records = await adapter.query(transit_query, deadline_seconds=budget)
            return list(records), [adapter.provider_id]

        return transit

    if kind is ProviderKind.ROUTE:
        if not body.waypoints:
            return "routes were requested but no waypoints were sent"
        route_query = RouteQuery(
            waypoints=[(lon, lat) for lon, lat in body.waypoints],
            mode=body.mode,
            alternatives=body.alternatives,
            avoid_polygons=body.avoid_polygons,
            departure_at=body.start,
            language=body.language,
        )

        async def routes(budget: float) -> tuple[list[Any], list[str]]:
            records = await adapter.query(route_query, deadline_seconds=budget)
            return list(records), [adapter.provider_id]

        return routes

    anchor = _places_anchor(body)
    if anchor is None:
        return "emergency places were requested but there is no coordinate " "to search around"
    places_query = NearbyPlacesQuery(
        longitude=anchor[0],
        latitude=anchor[1],
        radius_m=body.places_radius_m,
        place_types=list(body.place_types),
        language=body.language,
    )

    async def places(budget: float) -> tuple[list[Any], list[str]]:
        records = await adapter.query(places_query, deadline_seconds=budget)
        return list(records), [adapter.provider_id]

    return places


def _health_snapshot(adapters: AdapterRegistry, registry: ResolvedRegistry) -> list[dict[str, Any]]:
    """Registry-level health for the capabilities this endpoint covers.

    Included in the response on purpose: a consumer deciding whether to show a
    "we could not check" banner needs it in the same payload as the records, not
    from a second call that may see a different moment.
    """
    snapshot: list[dict[str, Any]] = []
    for kind in CONTEXT_CAPABILITIES:
        for resolved in registry.for_kind(kind):
            adapter = adapters.get(resolved.id)
            report = adapter.health() if adapter is not None else None
            snapshot.append(
                {
                    "provider": resolved.id,
                    "capability": str(kind),
                    "effective_status": str(resolved.effective_status),
                    "health": str(report.state) if report is not None else "UNKNOWN",
                    "reason": resolved.reason or (report.reason if report is not None else None),
                }
            )
    return snapshot


@router.post("/internal/v1/transport/query")
async def transport_query(
    request: Request, body: TransitQueryRequest, _: InternalAuth
) -> dict[str, Any]:
    """Live status for registered transit feeds (contract § 5.2).

    Coverage is per agency and never global. A query outside every registered
    feed comes back as UNSUPPORTED_COVERAGE naming the feeds that do exist -
    not as an empty list, which would read as "no trains are running here".

    Read `status` carefully: § 3.6 requires real-time evidence for ON_TIME and
    forbids inferring it from the absence of an alert. A running trip whose
    scheduled counterpart cannot be found is UNKNOWN with a null delay, because
    without the timetable there is nothing to be on time against. About two
    thirds of live trips are in that state at any moment, which is normal.
    """
    adapters: AdapterRegistry = request.app.state.adapters
    registry: ResolvedRegistry = request.app.state.registry

    adapter = adapters.for_kind(ProviderKind.TRANSIT)
    query = TransitQuery(
        bbox=body.bbox,
        route_ids=list(body.route_ids),
        stop_ids=list(body.stop_ids),
        feed_ids=list(body.feed_ids),
        limit=body.limit,
    )
    statuses = await adapter.query(query)

    matched = sum(1 for s in statuses if s.scheduled_arrival is not None)
    return success(
        {
            "statuses": [status.model_dump(mode="json") for status in statuses],
            # Said out loud: a consumer that sees mostly UNKNOWN should know it
            # is the schedule join, not a broken feed.
            "trips_matched_to_schedule": matched,
            "trips_without_schedule": len(statuses) - matched,
            "attribution": registry.attributions([adapter.provider_id]),
        }
    )
