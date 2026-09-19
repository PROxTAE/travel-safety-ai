"""Access logging and request metrics.

One line per request, after the response status is known. The line records the *route template*
rather than the path that was requested, and never the query string: a query string on this API
carries place names, bounding boxes and coordinates, all of which describe where a person is.

The same template feeds the metrics labels, which is why it is resolved once here.
"""

from __future__ import annotations

import time

from starlette.routing import Match, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware.body_limit import current_client_address
from app.observability.logging import get_logger
from app.observability.metrics import observe_request

logger = get_logger(__name__)

#: Polled by the orchestrator and Prometheus several times a minute; logging each one would bury
#: the requests a person actually made.
_QUIET_PATHS = frozenset({"/health/live", "/health/ready", "/metrics"})


def route_template(scope: Scope) -> str:
    """The path with its parameters left as placeholders, e.g. `/api/v1/trips/{trip_id}`.

    Falls back to a constant rather than the raw path for unmatched requests: a 404 probe loop
    would otherwise create an unbounded number of metric series.
    """
    app = scope.get("app")
    routes = getattr(app, "routes", None) or []
    for route in routes:
        if not isinstance(route, Route):
            continue
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return route.path
    return "<unmatched>"


class AccessLogMiddleware:
    """Emit one structured line and one metric observation per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500
        template = route_template(scope)

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - started
            observe_request(
                method=scope["method"],
                route=template,
                status_code=status_code,
                duration_seconds=duration,
            )

            if scope["path"] not in _QUIET_PATHS:
                logger.info(
                    "http_request",
                    event_type="http_request",
                    http_method=scope["method"],
                    route=template,
                    status=status_code,
                    duration_ms=round(duration * 1000, 2),
                    client=current_client_address(),
                )
