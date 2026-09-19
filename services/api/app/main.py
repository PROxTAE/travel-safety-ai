"""Application factory and lifespan.

The middleware order below is the part worth reading carefully. Starlette applies middleware in
reverse order of registration, so the list here reads outermost-first, and each layer depends on
the ones outside it:

1. **Security headers** — outermost, so every response carries them, including ones produced by a
   layer that rejected the request before it reached a handler.
2. **Request guard** — size limit and client address. Runs before anything reads the body, so an
   oversized upload is refused at the first chunk rather than after being buffered.
3. **Request context** — mints `request_id` and `correlation_id` and binds them to the log
   context. Everything inside it can log with correlation; everything outside it cannot, which is
   why only the two layers above sit further out.
4. **CORS** — must see the identity headers so it can expose them to the browser.
5. **Access log** — innermost of the cross-cutting layers, so the duration it records is the time
   the application actually spent, and the status it records is the final one.

Authentication is **not** a layer in this chain. It is a FastAPI dependency instead, declared per
router (`app/auth/dependencies.py`). A middleware would have to run for `/health/*` and `/metrics`
too and then decide to skip them, and that skip list fails open as routes are added; a dependency
makes "unauthenticated" something someone wrote down, visible in the OpenAPI document.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from redis.asyncio import Redis

from app.api import health as health_routes
from app.api.v1 import me as me_routes
from app.auth.jwks import JwksCache
from app.db.engine import create_engine, create_session_factory, dispose_engine
from app.errors.handlers import register_exception_handlers
from app.health.probes import agent_check, database_check, oidc_discovery_check, redis_check
from app.middleware.access_log import AccessLogMiddleware
from app.middleware.body_limit import RequestGuardMiddleware
from app.middleware.request_context import (
    CONTRACT_VERSION_HEADER,
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
)
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.observability.logging import configure_logging, get_logger
from app.observability.tracing import configure_tracing, instrument_app
from app.settings import Settings, get_settings

logger = get_logger(__name__)

DESCRIPTION = """\
Public trust boundary for the Smart Travel Assistant.

The browser reaches `web` and `api` and nothing else. Authentication is an OIDC access token;
ownership is resolved from that token and never from a body field. Anything safety-relevant carries
its source and freshness, and when a dependency is unavailable the response says so rather than
substituting a plausible value.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open shared clients at startup, close them at shutdown.

    Nothing here blocks startup on a dependency being reachable. The container starts, readiness
    reports what is missing, and the service recovers when the dependency returns — a start-up
    that refuses to boot without PostgreSQL turns a brief outage into a crash loop.
    """
    settings: Settings = app.state.settings

    engine = create_engine(settings)
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)

    redis_client: Redis = Redis.from_url(
        str(settings.redis_url),
        decode_responses=True,
        socket_connect_timeout=settings.redis_timeout_seconds,
        socket_timeout=settings.redis_timeout_seconds,
        health_check_interval=30,
    )
    app.state.redis = redis_client

    # One client for every internal call, so connections are pooled and the timeout budget is
    # applied in one place. Base URLs come from settings; a URL is never taken from a request.
    internal_http = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.downstream_connect_timeout_seconds,
            read=settings.downstream_read_timeout_seconds,
            write=settings.downstream_connect_timeout_seconds,
            pool=settings.downstream_connect_timeout_seconds,
        ),
        follow_redirects=False,  # a redirect from an internal service is a misconfiguration
        headers={"user-agent": f"{settings.service_name}/{settings.service_version}"},
    )
    app.state.internal_http = internal_http

    # One cache per process, sharing the internal HTTP client so its timeouts apply to the
    # identity provider too.
    app.state.jwks = JwksCache(settings=settings, client=internal_http)
    await app.state.jwks.warm()

    app.state.readiness_checks = [
        database_check(engine, settings),
        redis_check(redis_client, settings),
        oidc_discovery_check(internal_http, settings),
        agent_check(internal_http, settings),
    ]

    logger.info(
        "service_started",
        event_type="lifecycle",
        environment=settings.app_env,
        contract_version=settings.contract_version,
    )

    try:
        yield
    finally:
        await internal_http.aclose()
        await redis_client.aclose()
        await dispose_engine(engine)
        logger.info("service_stopped", event_type="lifecycle")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Takes settings as an argument so tests can construct an app against a throwaway database
    without touching the process environment.
    """
    settings = settings or get_settings()

    configure_logging(
        service_name=settings.service_name,
        environment=settings.app_env,
        version=settings.service_version,
        level=settings.log_level,
    )
    configure_tracing(settings)

    app = FastAPI(
        title="Smart Travel Assistant — Public API",
        version=settings.contract_version,
        description=DESCRIPTION,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )
    app.state.settings = settings
    app.state.readiness_checks = []

    # Registered innermost-first; see the module docstring for why this order.
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "if-match",
            "idempotency-key",
            "last-event-id",
            REQUEST_ID_HEADER,
            CORRELATION_ID_HEADER,
            CONTRACT_VERSION_HEADER,
            "traceparent",
        ],
        expose_headers=[
            REQUEST_ID_HEADER,
            CORRELATION_ID_HEADER,
            CONTRACT_VERSION_HEADER,
            "etag",
            "retry-after",
        ],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, contract_version=settings.contract_version)
    app.add_middleware(
        RequestGuardMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
        trusted_proxy_hops=settings.trusted_proxy_hops,
    )
    app.add_middleware(SecurityHeadersMiddleware)

    register_exception_handlers(app, settings)

    app.include_router(health_routes.router)
    app.include_router(me_routes.router)

    instrument_app(app)
    return app


# No module-level `app = create_app()`. Building the application at import time would read and
# validate the environment during any import of this module — including from a test that wanted
# nothing more than the factory — and would turn a configuration problem into an import error with
# a stack trace instead of a startup message. uvicorn is started with `--factory` instead.
