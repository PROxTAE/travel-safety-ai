"""Request identity and correlation.

Every request gets a `request_id` and a `correlation_id`, bound into the logging context so that
every line produced while handling it carries them without the handler passing them around. Both
are echoed on the response, which is what lets a user paste an id from an error message and have
someone find the exact request across eight services.

A client may supply either header. They are treated as untrusted: anything that is not a UUID is
replaced rather than propagated, so a crafted header cannot inject content into the log stream.
"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID, uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware.headers import decode_headers

REQUEST_ID_HEADER = "x-request-id"
CORRELATION_ID_HEADER = "x-correlation-id"
TRACEPARENT_HEADER = "traceparent"
CONTRACT_VERSION_HEADER = "x-contract-version"

#: Readable from anywhere in the request, including the exception handlers, which run outside the
#: endpoint's own scope and still have to put the right id in the envelope.
request_id_var: ContextVar[UUID | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[UUID | None] = ContextVar("correlation_id", default=None)


def current_request_id() -> UUID:
    """The id for the request in flight, minting one if the middleware did not run.

    A None here would end up in a response envelope, so it is filled rather than propagated.
    """
    return request_id_var.get() or uuid4()


def current_correlation_id() -> UUID | None:
    return correlation_id_var.get()


def _parse_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        # Not a UUID: drop it. Echoing arbitrary client input into logs and response headers is
        # how header injection and log forging start.
        return None


class RequestContextMiddleware:
    """Pure ASGI rather than `BaseHTTPMiddleware`.

    `BaseHTTPMiddleware` buffers the response through a queue, which breaks the SSE stream this
    service has to serve: progress events would arrive in a clump at the end instead of as they
    happen.
    """

    def __init__(self, app: ASGIApp, *, contract_version: str) -> None:
        self.app = app
        self.contract_version = contract_version

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = decode_headers(scope)

        request_id = _parse_uuid(headers.get(REQUEST_ID_HEADER)) or uuid4()
        # An absent correlation id means this request starts the chain, so it becomes the anchor
        # every downstream hop will carry.
        correlation_id = _parse_uuid(headers.get(CORRELATION_ID_HEADER)) or request_id

        request_token = request_id_var.set(request_id)
        correlation_token = correlation_id_var.set(correlation_id)

        structlog.contextvars.bind_contextvars(
            request_id=str(request_id),
            correlation_id=str(correlation_id),
        )

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                raw_headers.extend(
                    [
                        (REQUEST_ID_HEADER.encode(), str(request_id).encode()),
                        (CORRELATION_ID_HEADER.encode(), str(correlation_id).encode()),
                        (CONTRACT_VERSION_HEADER.encode(), self.contract_version.encode()),
                    ]
                )
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "correlation_id")
            request_id_var.reset(request_token)
            correlation_id_var.reset(correlation_token)
