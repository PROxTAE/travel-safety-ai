"""The middleware chain.

Correlation, request size, client address and security headers. These are the layers that hold
whether or not a handler remembers them, so they are tested at the HTTP surface rather than by
calling the classes directly.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.middleware.body_limit import resolve_client_address


async def test_request_id_is_minted_when_the_client_sends_none(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health/live")

    UUID(response.headers["x-request-id"])  # raises if it is not a UUID


async def test_client_supplied_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    """A user quoting an id from an error message must find that exact request in the logs."""
    supplied = str(uuid4())

    response = await client.get("/health/live", headers={"X-Request-ID": supplied})

    assert response.headers["x-request-id"] == supplied


async def test_a_malformed_request_id_is_replaced_not_propagated(
    client: httpx.AsyncClient,
) -> None:
    """Echoing arbitrary client input into headers and logs is how log forging starts."""
    response = await client.get(
        "/health/live", headers={"X-Request-ID": "not-a-uuid\r\nInjected: yes"}
    )

    assert "injected" not in {key.lower() for key in response.headers}
    UUID(response.headers["x-request-id"])


async def test_correlation_id_defaults_to_the_request_id(client: httpx.AsyncClient) -> None:
    """The first hop in a chain becomes its anchor."""
    response = await client.get("/health/live")

    assert response.headers["x-correlation-id"] == response.headers["x-request-id"]


async def test_correlation_id_is_preserved_across_a_hop(client: httpx.AsyncClient) -> None:
    correlation = str(uuid4())

    response = await client.get("/health/live", headers={"X-Correlation-ID": correlation})

    assert response.headers["x-correlation-id"] == correlation
    assert response.headers["x-request-id"] != correlation


async def test_contract_version_is_advertised(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.headers["x-contract-version"] == "1.0.0"


async def test_oversized_body_is_refused_before_the_handler_runs(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    handled = False

    @app.post("/_test/sink")
    async def sink(payload: dict[str, str]) -> dict[str, bool]:
        nonlocal handled
        handled = True
        return {"ok": True}

    limit = app.state.settings.max_request_body_bytes
    response = await client.post("/_test/sink", json={"blob": "x" * (limit + 1024)})

    assert response.status_code == 413
    assert handled is False, "the body was parsed despite exceeding the limit"
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_a_body_within_the_limit_is_accepted(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.post("/_test/small")
    async def small(payload: dict[str, str]) -> dict[str, int]:
        return {"length": len(payload["blob"])}

    response = await client.post("/_test/small", json={"blob": "x" * 1024})

    assert response.status_code == 200
    assert response.json()["length"] == 1024


@pytest.mark.parametrize(
    ("header", "hops", "expected"),
    [
        # No trusted proxy: the header is ignored entirely, or a client could pick its own
        # rate-limit bucket by sending it.
        ("203.0.113.9", 0, "10.0.0.1"),
        (None, 0, "10.0.0.1"),
        # One trusted proxy: the rightmost entry is the one our proxy appended.
        ("203.0.113.9, 198.51.100.7", 1, "198.51.100.7"),
        ("203.0.113.9", 1, "203.0.113.9"),
        # More hops claimed than present: fall back rather than index out of the list.
        ("203.0.113.9", 3, "203.0.113.9"),
    ],
)
def test_client_address_ignores_untrusted_forwarding(
    header: str | None, hops: int, expected: str
) -> None:
    headers: list[tuple[bytes, bytes]] = []
    if header is not None:
        headers.append((b"x-forwarded-for", header.encode()))

    scope = {"type": "http", "headers": headers, "client": ("10.0.0.1", 51234)}

    assert resolve_client_address(scope, hops) == expected  # type: ignore[arg-type]


async def test_security_headers_are_present_on_every_response(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health/live")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "geolocation=()" in response.headers["permissions-policy"]


async def test_responses_are_not_cacheable_by_default(client: httpx.AsyncClient) -> None:
    """Everything here is scoped to one signed-in user; a shared cache must not hold it."""
    response = await client.get("/health/live")

    assert response.headers["cache-control"] == "private, no-store"


async def test_security_headers_survive_an_error(client: httpx.AsyncClient) -> None:
    """The outermost layer applies them, so a request rejected early is still covered."""
    response = await client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_cors_allows_the_configured_origin_only(client: httpx.AsyncClient) -> None:
    allowed = await client.get("/health/live", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"

    other = await client.get("/health/live", headers={"Origin": "https://evil.invalid"})
    assert other.headers.get("access-control-allow-origin") is None


async def test_correlation_headers_are_readable_by_the_browser(
    client: httpx.AsyncClient,
) -> None:
    """Without expose-headers the web app cannot read the id it needs for a support report."""
    response = await client.get("/health/live", headers={"Origin": "http://localhost:3000"})

    exposed = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-request-id" in exposed
    assert "etag" in exposed
