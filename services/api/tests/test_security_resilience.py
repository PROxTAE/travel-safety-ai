"""Security and resilience tests.

Covers request size limits, decompression bomb protection, malformed compression handling,
security headers with HSTS, and outbound URL allowlisting (SSRF protection).
"""

from __future__ import annotations

import gzip

import httpx
import pytest
from fastapi import FastAPI

from app.security.outbound import (
    OutboundTargetForbidden,
    validate_outbound_url,
)
from app.settings import Settings


async def test_decompression_bomb_is_rejected_with_413(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """A tiny compressed payload that decompresses into an oversized body must be refused."""
    limit = app.state.settings.max_request_body_bytes
    decompressed_data = b"A" * (limit + 4096)
    compressed = gzip.compress(decompressed_data)

    # The compressed payload itself is small and passes content-length check,
    # but decompression exceeds max_body_bytes.
    assert len(compressed) < limit

    @app.post("/_test/decompress_sink")
    async def sink(payload: dict[str, str]) -> dict[str, bool]:
        return {"ok": True}

    response = await client.post(
        "/_test/decompress_sink",
        content=compressed,
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "larger than" in body["error"]["message"]


async def test_valid_gzip_within_limit_is_accepted(app: FastAPI, client: httpx.AsyncClient) -> None:
    @app.post("/_test/decompress_ok")
    async def ok_sink(payload: dict[str, str]) -> dict[str, str]:
        return payload

    import orjson

    raw = orjson.dumps({"msg": "hello from gzip"})
    compressed = gzip.compress(raw)

    response = await client.post(
        "/_test/decompress_ok",
        content=compressed,
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["msg"] == "hello from gzip"


async def test_malformed_compressed_data_returns_400(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    @app.post("/_test/decompress_bad")
    async def bad_sink(payload: dict[str, str]) -> dict[str, bool]:
        return {"ok": True}

    response = await client.post(
        "/_test/decompress_bad",
        content=b"not-valid-gzip-stream",
        headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


async def test_unsupported_content_encoding_returns_415(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    @app.post("/_test/unsupported_enc")
    async def enc_sink(payload: dict[str, str]) -> dict[str, bool]:
        return {"ok": True}

    response = await client.post(
        "/_test/unsupported_enc",
        content=b"payload",
        headers={"Content-Encoding": "brotli", "Content-Type": "application/json"},
    )

    assert response.status_code == 415


async def test_security_headers_includes_hsts_when_https(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Forwarded-Proto": "https"})

    assert "strict-transport-security" in response.headers
    assert "max-age=31536000" in response.headers["strict-transport-security"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-permitted-cross-domain-policies"] == "none"


def test_outbound_allowlist_permits_configured_services(settings: Settings) -> None:
    agent_url = f"{settings.agent_service_url.rstrip('/')}/internal/v1/runs"
    ext_url = f"{settings.external_data_service_url.rstrip('/')}/internal/v1/geocode/search"
    rec_url = f"{settings.recommendation_service_url.rstrip('/')}/internal/v1/recommendations/123"
    oidc_url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"

    assert validate_outbound_url(agent_url, settings) == agent_url
    assert validate_outbound_url(ext_url, settings) == ext_url
    assert validate_outbound_url(rec_url, settings) == rec_url
    assert validate_outbound_url(oidc_url, settings) == oidc_url


def test_outbound_allowlist_blocks_unauthorized_urls(settings: Settings) -> None:
    evil_urls = [
        "http://evil.attacker.com/internal/v1/runs",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:9000/admin",
        "https://google.com",
    ]

    for url in evil_urls:
        with pytest.raises(OutboundTargetForbidden):
            validate_outbound_url(url, settings)
