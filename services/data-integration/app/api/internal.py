"""Health and storage inspection; snapshot API follows in Phase 5."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import InternalAuth
from app.api.envelope import error, success
from app.settings import get_settings

health_router = APIRouter()
internal_router = APIRouter()


@health_router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@health_router.get("/health/ready", response_model=None)
async def ready(request: Request) -> JSONResponse | dict[str, str]:
    if get_settings().internal_service_token is None:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "auth"})
    try:
        async with request.app.state.engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM integration.snapshots LIMIT 1"))
            await connection.execute(text("SELECT PostGIS_Version()"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "storage"})
    return {"status": "ready"}


@internal_router.get("/internal/v1/storage/status", response_model=None)
async def storage_status(request: Request, _: InternalAuth) -> dict[str, object] | JSONResponse:
    try:
        async with request.app.state.engine.connect() as connection:
            count = (
                await connection.execute(text("SELECT count(*) FROM integration.snapshots"))
            ).scalar_one()
    except Exception:
        return error("DEPENDENCY_UNAVAILABLE", "Storage unavailable", 503)
    return success({"snapshot_count": count})
