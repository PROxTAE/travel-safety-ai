"""Response headers that harden the API surface itself.

This service answers JSON, not documents, so the headers here are the subset that still matters for
an API: stop content-type sniffing, deny framing, send no referrer, and disable the browser
features a JSON endpoint has no use for. The document-level Content-Security-Policy belongs to the
web app, which serves the HTML.

Responses are marked `private, no-store` unless a handler has already decided otherwise. Everything
this API returns is scoped to one signed-in user, and a shared cache holding one user's trips and
serving them to the next is the kind of bug that is found from the outside.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_STATIC_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"geolocation=(), camera=(), microphone=(), payment=()"),
    (b"cross-origin-resource-policy", b"same-origin"),
)

_CACHE_CONTROL = (b"cache-control", b"private, no-store")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                headers.extend((key, value) for key, value in _STATIC_HEADERS if key not in present)
                if b"cache-control" not in present:
                    headers.append(_CACHE_CONTROL)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
