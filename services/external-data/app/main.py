"""FastAPI application for module 04 - external data services."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.adapters.factory import AdapterRegistry
from app.api import internal
from app.api.deps import InternalAuthError
from app.api.envelope import FieldError, error_response, provider_error_response
from app.cache.provider_cache import ProviderCache
from app.domain.errors import ApiErrorCode, ProviderError
from app.observability.context import (
    CONTRACT_VERSION_HEADER,
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    correlation_id_var,
    new_id,
    request_id_var,
)
from app.observability.logging import configure_logging, get_logger
from app.observability.metrics import http_latency, http_requests
from app.providers.registry import ResolvedRegistry, load_registry
from app.repositories.db import build_engine, build_session_factory
from app.repositories.provider_repo import ProviderRepository
from app.settings import get_settings
from app.transport.http import ProviderTransport

log = get_logger(__name__)


def _route_label(request: Request) -> str:
    """Metric label for a request.

    Templated route path when one matched, the constant "unmatched" otherwise -
    an unrouted URL must never become its own label value, or anyone scanning
    for paths can grow the metric cardinality without bound.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(
        service=settings.service_name,
        environment=settings.app_env,
        level=settings.log_level,
    )

    registry = ResolvedRegistry(load_registry(settings.provider_config_path), settings)
    app.state.registry = registry
    app.state.transport = ProviderTransport(registry.defaults)

    # Short, non-retrying socket settings: the cache is an optimisation, so a
    # dead Redis must fail fast rather than add its timeout to every request.
    app.state.redis = Redis.from_url(
        str(settings.redis_url),
        socket_connect_timeout=0.5,
        socket_timeout=1.0,
        retry_on_timeout=False,
        single_connection_client=False,
    )
    app.state.cache = ProviderCache(app.state.redis, env=settings.app_env)

    app.state.engine = build_engine(settings.database_url)
    app.state.sessions = build_session_factory(app.state.engine)
    app.state.repo = ProviderRepository(app.state.sessions)

    # The repository doubles as the health recorder, so every provider call
    # leaves an observation behind for /internal/v1/providers/health.
    app.state.adapters = AdapterRegistry(
        registry,
        app.state.transport,
        app.state.cache,
        env=settings.app_env,
        health_recorder=app.state.repo,
    )

    blocked = [p.id for p in registry.all() if not p.is_callable]
    log.info(
        "startup",
        providers_total=len(registry.all()),
        providers_active=len(registry.all()) - len(blocked),
        providers_blocked=blocked,
        internal_auth_configured=settings.internal_service_token is not None,
        adapters=app.state.adapters.ids,
    )

    # Mirroring the registry needs the database, and on a first boot the tables
    # do not exist yet - the documented order runs `alembic upgrade head` after
    # the container is up. A cold or unmigrated Postgres must not stop the
    # process from starting, so the failure is recorded and readiness retries
    # it. Without the retry the mirror stays empty for the life of the process
    # and every health write fails its foreign key, silently.
    app.state.registry_synced = False
    try:
        count = await app.state.repo.sync_registry(registry)
        app.state.registry_synced = True
        log.info("registry_synced", rows=count)
    except Exception as exc:
        log.warning("registry_sync_failed", error=str(exc))

    try:
        yield
    finally:
        await app.state.transport.aclose()
        await app.state.redis.aclose()
        await app.state.engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="External Data Service",
        version="0.1.0",
        description="Module 04 - real provider adapters with provenance, cache and quota",
        lifespan=lifespan,
        docs_url="/internal/docs" if not settings.is_production else None,
        openapi_url="/internal/openapi.json" if not settings.is_production else None,
    )

    @app.middleware("http")
    async def correlation_and_metrics(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_id()
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or request_id
        request_id_var.set(request_id)
        correlation_id_var.set(correlation_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            http_requests.labels(
                method=request.method, route=_route_label(request), status="500"
            ).inc()
            raise
        finally:
            # Resolved only after the router has run. Reading it earlier always
            # fell back to the raw URL, so every scanned path minted a new
            # metric series.
            http_latency.labels(
                method=request.method, route=_route_label(request)
            ).observe(time.perf_counter() - started)

        http_requests.labels(
            method=request.method,
            route=_route_label(request),
            status=str(response.status_code),
        ).inc()
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        response.headers[CONTRACT_VERSION_HEADER] = settings.contract_version
        return response

    @app.exception_handler(ProviderError)
    async def _provider_error(_: Request, exc: ProviderError) -> JSONResponse:
        log.warning(
            "provider_error",
            provider=exc.provider_id,
            error_code=str(exc.code),
            status=exc.http_status,
        )
        return provider_error_response(exc)

    @app.exception_handler(InternalAuthError)
    async def _auth_error(_: Request, exc: InternalAuthError) -> JSONResponse:
        return error_response(
            ApiErrorCode.AUTHENTICATION_REQUIRED,
            str(exc.detail),
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            ApiErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            status_code=422,
            field_errors=[
                FieldError(
                    path=".".join(str(part) for part in err.get("loc", ())),
                    code=str(err.get("type", "INVALID")).upper(),
                )
                for err in exc.errors()
            ],
        )

    # Starlette raises its own HTTPException for an unmatched route, so
    # registering only the FastAPI one would let a 404 escape the envelope.
    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        _: Request, exc: HTTPException | StarletteHTTPException
    ) -> JSONResponse:
        code = {
            401: ApiErrorCode.AUTHENTICATION_REQUIRED,
            403: ApiErrorCode.FORBIDDEN,
            404: ApiErrorCode.NOT_FOUND,
            429: ApiErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ApiErrorCode.INTERNAL_ERROR)
        return error_response(code, str(exc.detail), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Log the type, never the message: an upstream exception can carry a
        # credential or a full URL with query parameters.
        log.error("unhandled_error", error_type=type(exc).__name__)
        return error_response(
            ApiErrorCode.INTERNAL_ERROR,
            "Internal error",
            status_code=500,
        )

    app.include_router(internal.health_router)
    app.include_router(internal.router)
    return app


app = create_app()
