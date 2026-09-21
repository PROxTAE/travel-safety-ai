"""Module 05 service entry point."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.envelope import error
from app.api.internal import health_router, internal_router
from app.api.snapshots import router as snapshot_router
from app.observability.context import correlation_id, request_id
from app.observability.logging import configure_logging
from app.observability.metrics import http_latency, http_requests, requests_rejected
from app.repositories.db import build_engine
from app.settings import get_settings


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    application.state.engine = build_engine(settings.database_url)
    try:
        yield
    finally:
        await application.state.engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(title="Data Integration", version="0.1.0", lifespan=lifespan)

    @application.middleware("http")
    async def trace_and_measure(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid4())
        cid = request.headers.get("X-Correlation-ID") or rid
        request_id.set(rid)
        correlation_id.set(cid)
        started = time.perf_counter()
        route = "unmatched"
        try:
            response = await call_next(request)
            return response
        finally:
            matched = request.scope.get("route")
            route = getattr(matched, "path", "unmatched")
            duration = time.perf_counter() - started
            http_latency.labels(request.method, route).observe(duration)
            status = str(response.status_code) if "response" in locals() else "500"
            http_requests.labels(request.method, route, status).inc()
            if "response" in locals():
                response.headers["X-Request-ID"] = rid
                response.headers["X-Correlation-ID"] = cid
                response.headers["X-Contract-Version"] = get_settings().contract_version

    @application.exception_handler(HTTPException)
    async def http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        code = "AUTHENTICATION_REQUIRED" if exc.status_code == 401 else "NOT_FOUND"
        return error(code, str(exc.detail), exc.status_code)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Paths only: a rejected value is never echoed back.
        codes = {"missing": "REQUIRED", "extra_forbidden": "UNKNOWN_FIELD"}
        field_errors = [
            {
                "path": ".".join(str(part) for part in item["loc"][1:])[:256],
                "code": codes.get(item["type"], "INVALID_FORMAT"),
            }
            for item in exc.errors()
        ]
        for item in field_errors:
            requests_rejected.labels(code=item["code"]).inc()
        return error("VALIDATION_ERROR", "Request does not match the contract", 422, field_errors)

    @application.exception_handler(Exception)
    async def unknown_exception(_: Request, __: Exception) -> JSONResponse:
        return error("INTERNAL_ERROR", "Internal error", 500)

    @application.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    application.include_router(health_router)
    application.include_router(internal_router)
    application.include_router(snapshot_router)
    return application


app = create_app()
