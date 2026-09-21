from __future__ import annotations

import re
import time
from contextvars import ContextVar
from uuid import UUID, uuid4

import structlog.contextvars
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.logging import get_logger
from app.metrics import REQUEST_COUNT, REQUEST_LATENCY

REQUEST_ID: ContextVar[UUID | None] = ContextVar("request_id", default=None)
CORRELATION_ID: ContextVar[UUID | None] = ContextVar("correlation_id", default=None)
TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="0" * 32)
TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


def current_request_id() -> UUID:
    return REQUEST_ID.get() or UUID(int=0)


def current_correlation_id() -> UUID:
    return CORRELATION_ID.get() or UUID(int=0)


def _parse_uuid(value: str | None) -> UUID:
    if not value:
        return uuid4()
    try:
        parsed = UUID(value)
        if str(parsed) != value.lower():
            raise ValueError
        return parsed
    except ValueError:
        return uuid4()


def _trace_id(value: str | None) -> str:
    if value:
        matched = TRACEPARENT_RE.fullmatch(value.lower())
        if matched:
            return matched.group(1)
    return uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _parse_uuid(request.headers.get("X-Request-ID"))
        correlation_id = _parse_uuid(request.headers.get("X-Correlation-ID"))
        trace_id = _trace_id(request.headers.get("traceparent"))
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        request.state.trace_id = trace_id
        request_token = REQUEST_ID.set(request_id)
        correlation_token = CORRELATION_ID.set(correlation_id)
        trace_token = TRACE_ID.set(trace_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=str(request_id),
            correlation_id=str(correlation_id),
            trace_id=trace_id,
            environment=request.app.state.settings.app_env,
        )
        started = time.perf_counter()
        status_code = 500
        error_code: str | None = "INTERNAL_ERROR"
        route = request.url.path
        try:
            response = await call_next(request)
            status_code = response.status_code
            error_code = response.headers.get("X-Error-Code") if status_code >= 400 else None
            response.headers["X-Request-ID"] = str(request_id)
            response.headers["X-Correlation-ID"] = str(correlation_id)
            return response
        finally:
            matched_route = request.scope.get("route")
            route = getattr(matched_route, "path", route)
            duration = time.perf_counter() - started
            REQUEST_COUNT.labels(request.method, route, str(status_code)).inc()
            REQUEST_LATENCY.labels(request.method, route).observe(duration)
            get_logger().info(
                "http_request_completed",
                method=request.method,
                route=route,
                status=status_code,
                duration_ms=round(duration * 1000, 3),
                error_code=error_code,
            )
            structlog.contextvars.clear_contextvars()
            REQUEST_ID.reset(request_token)
            CORRELATION_ID.reset(correlation_token)
            TRACE_ID.reset(trace_token)
