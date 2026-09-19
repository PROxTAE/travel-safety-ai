from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.metrics import DEPENDENCY_STATUS
from app.timeouts import hard_timeout

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "service": "risk-knowledge",
        "version": request.app.state.settings.service_version,
    }


@router.get("/health/ready")
async def readiness(request: Request) -> Response:
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    try:
        database_ready, database_detail = await hard_timeout(
            runtime.database.check_ready(), settings.dependency_timeout_seconds
        )
    except TimeoutError:
        database_ready, database_detail = False, "Database readiness timed out"
    DEPENDENCY_STATUS.labels("postgres").set(1 if database_ready else 0)

    auth_ready = settings.internal_auth_configured
    DEPENDENCY_STATUS.labels("internal_auth").set(1 if auth_ready else 0)

    if database_ready:
        await asyncio.gather(runtime.refresh_knowledge(), runtime.refresh_model())
    else:
        runtime.model.status = "UNAVAILABLE"
        runtime.model.reason = "DATABASE_UNAVAILABLE"
        runtime.model.model = None
        runtime.knowledge.status = "UNAVAILABLE"
        runtime.knowledge.reason = "DATABASE_UNAVAILABLE"
        runtime.knowledge.collection_version = None
        runtime.knowledge.document_cutoff = None
    components: dict[str, dict[str, Any]] = {
        "database": {
            "status": "READY" if database_ready else "UNAVAILABLE",
            "critical": True,
            "detail": database_detail,
        },
        "internal_auth": {
            "status": "READY" if auth_ready else "UNAVAILABLE",
            "critical": True,
            "detail": None if auth_ready else "Internal service token is not configured",
        },
        "risk_model": {
            "status": runtime.model.status,
            "critical": False,
            "detail": runtime.model.reason,
        },
        "knowledge_collection": {
            "status": runtime.knowledge.status,
            "critical": False,
            "detail": runtime.knowledge.reason,
        },
    }
    critical_ready = database_ready and auth_ready
    optional_ready = runtime.model.status == "AVAILABLE" and runtime.knowledge.status == "AVAILABLE"
    if critical_ready and optional_ready:
        status = "ready"
    elif critical_ready:
        status = "degraded"
    else:
        status = "not_ready"
    body = {"status": status, "service": "risk-knowledge", "components": components}
    return Response(
        content=request.app.state.json_dumps(body),
        media_type="application/json",
        status_code=200 if critical_ready else 503,
    )


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
