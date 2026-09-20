"""Request size limit and client address resolution.

The size limit runs before anything reads the body, so an oversized upload is refused at the first
chunk rather than after it has been buffered in memory. A declared `Content-Length` is rejected
immediately; a chunked body is counted as it streams, because a client can simply omit the header.

The client address is resolved here too, once, from a configured number of trusted proxy hops.
Rate limiting keys on it, so taking the leftmost `X-Forwarded-For` entry — the usual shortcut —
would let any caller pick its own rate-limit bucket by sending the header itself.
"""

from __future__ import annotations

from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware.headers import decode_headers
from app.observability.metrics import request_body_rejected_total

client_address_var: ContextVar[str | None] = ContextVar("client_address", default=None)

FORWARDED_FOR_HEADER = "x-forwarded-for"


def current_client_address() -> str:
    return client_address_var.get() or "unknown"


def resolve_client_address(scope: Scope, trusted_proxy_hops: int) -> str:
    """The address to attribute this request to.

    With no trusted proxy the socket address is used and forwarding headers are ignored entirely.
    With `n` trusted proxies the address is taken `n` entries from the right of `X-Forwarded-For`:
    those are the entries our own infrastructure appended, and everything to their left is
    whatever the client chose to send.
    """
    socket_address = scope.get("client")
    fallback = socket_address[0] if socket_address else "unknown"

    if trusted_proxy_hops <= 0:
        return fallback

    headers = decode_headers(scope)
    forwarded = headers.get(FORWARDED_FOR_HEADER)
    if not forwarded:
        return fallback

    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if not hops:
        return fallback

    index = len(hops) - trusted_proxy_hops
    return hops[index] if 0 <= index < len(hops) else hops[0]


class RequestGuardMiddleware:
    """Refuse oversized bodies and pin down the client address."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int, trusted_proxy_hops: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.trusted_proxy_hops = trusted_proxy_hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = client_address_var.set(resolve_client_address(scope, self.trusted_proxy_hops))
        try:
            headers = decode_headers(scope)

            declared = headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_body_bytes:
                request_body_rejected_total.labels(reason="content_length").inc()
                await _send_payload_too_large(send, self.max_body_bytes)
                return

            received = 0

            async def counting_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_body_bytes:
                        request_body_rejected_total.labels(reason="streamed_body").inc()
                        # Starve the application of further body rather than letting it keep
                        # buffering. The 413 is emitted below by the exception this raises.
                        raise _BodyTooLarge
                return message

            try:
                await self.app(scope, counting_receive, send)
            except _BodyTooLarge:
                await _send_payload_too_large(send, self.max_body_bytes)
        finally:
            client_address_var.reset(token)


class _BodyTooLarge(Exception):
    """Internal signal; never surfaces to a client as itself."""


async def _send_payload_too_large(send: Send, limit: int) -> None:
    """Hand-built response: the error handlers are further in and may never be reached."""
    import orjson

    from app.errors.codes import ErrorCode
    from app.middleware.request_context import current_correlation_id, current_request_id

    request_id = current_request_id()
    correlation_id = current_correlation_id()

    from datetime import UTC, datetime

    body = orjson.dumps(
        {
            "error": {
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"The request body is larger than the {limit} byte limit.",
                "field_errors": [],
                "retryable": False,
                "retry_after_seconds": None,
            },
            "meta": {
                "request_id": str(request_id),
                "correlation_id": str(correlation_id) if correlation_id else None,
                "contract_version": "1.0.0",
                "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "degraded_services": [],
            },
        }
    )

    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
