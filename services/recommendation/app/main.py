from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest
from sqlalchemy import text

from app.api.internal import router as internal_router
from app.database import get_engine, get_session_factory
from app.directory.ingest import ingest_emergency_directory
from app.observability import setup_observability
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_observability(get_settings().LOG_LEVEL)
    # On startup, seed emergency directory if path exists
    settings = get_settings()
    if settings.EMERGENCY_DIRECTORY_PATH:
        try:
            factory = get_session_factory()
            async with factory() as session:
                await ingest_emergency_directory(session, settings.EMERGENCY_DIRECTORY_PATH)
        except Exception as exc:
            # Startup should not crash if database is temporarily unavailable during initial build
            structlog.get_logger().warning(
                "Initial emergency directory seeding skipped", error=str(exc)
            )
    yield
    # Shutdown
    engine = get_engine()
    await engine.dispose()


app = FastAPI(
    title="Smart Travel Recommendation and Feedback Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def correlation_and_logging_middleware(request: Request, call_next: Any) -> Response:
    start_time = time.perf_counter()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))

    request.state.request_id = request_id
    request.state.correlation_id = correlation_id

    response: Response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    code = "INTERNAL_ERROR"
    message = str(exc.detail)
    field_errors: list[dict[str, Any]] = []

    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", "ERROR")
        message = exc.detail.get("message", "An error occurred")
        field_errors = exc.detail.get("field_errors", [])
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        code = "NOT_FOUND"
    elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "AUTHENTICATION_REQUIRED"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = "FORBIDDEN"
    elif exc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        code = "VALIDATION_ERROR"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "field_errors": field_errors,
                "retryable": exc.status_code >= 500,
                "retry_after_seconds": None,
            },
            "meta": {
                "request_id": request_id,
                "correlation_id": correlation_id,
                "contract_version": get_settings().CONTRACT_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    field_errors = [
        {
            "path": ".".join(str(loc) for loc in err["loc"]),
            "code": err["type"],
            "message": err["msg"],
        }
        for err in exc.errors()
    ]

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "field_errors": field_errors,
                "retryable": False,
                "retry_after_seconds": None,
            },
            "meta": {
                "request_id": request_id,
                "correlation_id": correlation_id,
                "contract_version": get_settings().CONTRACT_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        },
    )


# Health and Metrics


@app.get("/health/live", tags=["health"])
async def health_live() -> dict[str, Any]:
    return {"status": "ok", "service": "recommendation", "version": "1.0.0"}


@app.get("/health/ready", tags=["health"])
async def health_ready(response: Response) -> dict[str, Any]:
    settings = get_settings()
    dependencies: dict[str, Any] = {}
    is_ready = True

    # Check PostgreSQL
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        dependencies["postgres"] = {"status": "ok"}
    except Exception as e:
        dependencies["postgres"] = {"status": "unreachable", "message": str(e)}
        is_ready = False

    # Check Redis (non-fatal if degraded, but reported)
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[no-untyped-call]
        await r.ping()
        await r.aclose()
        dependencies["redis"] = {"status": "ok"}
    except Exception as e:
        dependencies["redis"] = {"status": "degraded", "message": str(e)}

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "service": "recommendation", "dependencies": dependencies}

    return {"status": "ready", "service": "recommendation", "dependencies": dependencies}


@app.get("/metrics", tags=["health"])
async def metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type="text/plain; version=0.0.4")


# Mount internal router
app.include_router(internal_router)
