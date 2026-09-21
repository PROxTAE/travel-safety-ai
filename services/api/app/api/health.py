"""Health and metrics endpoints.

These are the only unauthenticated routes on the service. They are deliberately dull: they say
whether this instance can serve traffic and nothing about what it holds. `detail` on a failing
check names the exception type, never its message, because a connection error's message contains
the DSN and this response has no authentication in front of it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import ORJSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app.health.checks import CheckResult, run_all
from app.observability.metrics import REGISTRY, readiness_state

router = APIRouter(tags=["health"])


class HealthLiveResponse(BaseModel):
    status: str
    service: str
    version: str


class HealthCheckModel(BaseModel):
    name: str
    required: bool
    status: str
    duration_ms: float
    detail: str | None = None


class HealthReadyResponse(BaseModel):
    status: str
    checks: list[HealthCheckModel]
    checked_at: datetime


def _to_model(result: CheckResult) -> HealthCheckModel:
    return HealthCheckModel(
        name=result.name,
        required=result.required,
        status=result.status,
        duration_ms=result.duration_ms,
        detail=result.detail,
    )


@router.get(
    "/health/live",
    response_model=HealthLiveResponse,
    summary="Process liveness",
)
async def health_live(request: Request) -> HealthLiveResponse:
    """True whenever the process is running.

    Touches no dependency on purpose: a database outage must not make the orchestrator restart
    containers that are working perfectly well.
    """
    settings = request.app.state.settings
    return HealthLiveResponse(
        status="alive",
        service=settings.service_name,
        version=settings.service_version,
    )


@router.get(
    "/health/ready",
    response_model=HealthReadyResponse,
    summary="Dependency readiness",
)
async def health_ready(request: Request) -> Response:
    """Whether this instance can serve traffic right now.

    503 when a required dependency is down, so the instance leaves rotation rather than answering
    requests it cannot honour. Optional dependencies are reported but do not fail the probe.
    """
    settings = request.app.state.settings
    checks = request.app.state.readiness_checks

    ready, results = await run_all(checks, budget_seconds=settings.readiness_timeout_seconds)
    readiness_state.set(1 if ready else 0)

    payload = HealthReadyResponse(
        status="ready" if ready else "not_ready",
        checks=[_to_model(result) for result in results],
        checked_at=datetime.now(UTC),
    )
    return ORJSONResponse(
        status_code=200 if ready else 503,
        content=payload.model_dump(mode="json"),
    )


@router.get(
    "/metrics",
    include_in_schema=False,
    summary="Prometheus metrics",
)
async def metrics() -> Response:
    """Scraped over the internal network only; never exposed publicly.

    Served from this service's own registry rather than the process-global default, so nothing a
    library registers by accident leaks out here.
    """
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
