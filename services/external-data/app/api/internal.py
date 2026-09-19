"""Internal API surface for Phase 1.

Live and ready probes plus the provider health endpoint. The capability
endpoints (geocode, weather, disasters, routes, transport, places, context)
arrive with their adapters in Phases 2-6.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import InternalAuth
from app.api.envelope import success
from app.domain.enums import HealthState, ProviderStatus
from app.observability.metrics import REGISTRY
from app.providers.registry import ResolvedRegistry
from app.settings import get_settings

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

    providers: list[dict[str, Any]] = []
    degraded: list[str] = []

    for resolved in registry.all():
        entry = resolved.entry
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
            state = (
                HealthState.CIRCUIT_OPEN
                if guards.circuit.state is CircuitState.OPEN
                else HealthState.UP
            )

        if state is not HealthState.UP:
            degraded.append(resolved.id)

        providers.append(
            {
                "provider": resolved.id,
                "kind": str(entry.kind),
                "registry_status": str(entry.status),
                "effective_status": str(resolved.effective_status),
                "health": str(state),
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
