"""Health and authentication behavior without a test double for storage."""

import secrets

import httpx
import pytest
from sqlalchemy import text

from app.main import create_app
from app.settings import get_settings


@pytest.mark.asyncio
async def test_liveness_and_fail_closed_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
    get_settings.cache_clear()
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health/live")).status_code == 200
        response = await client.get("/internal/v1/storage/status")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_readiness_checks_real_database(
    isolated_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.engine import make_url

    url = make_url(isolated_database)
    monkeypatch.setenv("POSTGRES_DB", url.database or "")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", secrets.token_urlsafe(32))
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/ready")).status_code == 200
            assert (await client.get("/internal/v1/storage/status")).status_code == 401
            token = get_settings().internal_service_token
            assert token is not None
            result = await client.get(
                "/internal/v1/storage/status",
                headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            )
            assert result.status_code == 200
            # The session database is shared, so compare with the table rather than assume empty.
            async with app.state.engine.connect() as connection:
                stored = (
                    await connection.execute(text("SELECT count(*) FROM integration.snapshots"))
                ).scalar_one()
            assert result.json()["data"]["snapshot_count"] == stored
    get_settings.cache_clear()
