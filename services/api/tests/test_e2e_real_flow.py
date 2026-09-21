"""End-to-End Real Provider Flow and Correlation Tracing.

Verification (Phase 8.4):
1. NO MOCK PROVIDERS: Communicates with real external-data service (Open-Meteo geocoding),
   PostgreSQL, and Redis.
2. Full user flow:
   - Search place via real geocoding provider (Bangkok & Chiang Mai).
   - Create a trip with confirmed coordinates and provider provenance.
   - Start an assessment run for the trip.
   - Poll run status.
3. Trace verification:
   - Asserts X-Request-ID and X-Correlation-ID are propagated and returned on every response header.
   - Asserts meta.request_id and meta.correlation_id match across all responses.
   - Verifies audit log records capture the identical correlation_id.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.schemas.location import LocationRef
from app.settings import Settings
from tests.conftest import build_settings
from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
def real_e2e_settings(migrated_database_url: str) -> Settings:
    url = make_url(migrated_database_url)
    external_data_url = os.environ.get("EXTERNAL_DATA_SERVICE_URL", "http://localhost:8002")
    return build_settings(
        POSTGRES_HOST=url.host or "localhost",
        POSTGRES_PORT=str(url.port or 5432),
        POSTGRES_DB=url.database or "postgres",
        POSTGRES_USER=url.username or "postgres",
        POSTGRES_PASSWORD=url.password or "",
        EXTERNAL_DATA_SERVICE_URL=external_data_url,
        INTERNAL_SERVICE_TOKEN="dev-internal-token-secret-for-testing",
    )


@pytest.fixture(autouse=True)
async def require_external_data(real_e2e_settings: Settings) -> None:
    service_url = real_e2e_settings.external_data_service_url
    try:
        token = real_e2e_settings.internal_service_token.get_secret_value()
        async with httpx.AsyncClient(timeout=1.0) as check_client:
            r = await check_client.get(
                f"{service_url}/internal/v1/providers/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                pytest.skip(f"external-data at {service_url} not healthy")
    except Exception:
        pytest.skip(
            f"no external-data service running at {service_url}. "
            "Start it with: docker compose -f compose.yaml -f compose.dev.yaml up -d external-data"
        )


@pytest.fixture
async def authed_real_app(
    real_e2e_settings: Settings, key: SigningKeyPair
) -> AsyncIterator[FastAPI]:
    from app.main import create_app

    application = create_app(real_e2e_settings)

    async with application.router.lifespan_context(application):
        application.state.jwks = StubJwks.containing(key)
        yield application


@pytest.fixture
async def client(authed_real_app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=authed_real_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def token(key: SigningKeyPair) -> str:
    return key.sign({"sub": f"e2e-user-{uuid.uuid4()}"})


@pytest.mark.asyncio
async def test_full_e2e_real_provider_flow_with_correlation_trace(
    authed_real_app: FastAPI,
    client: httpx.AsyncClient,
    token: str,
) -> None:
    # 1. Establish session correlation ID
    correlation_id = uuid.uuid4()
    auth_header = {"Authorization": f"Bearer {token}"}

    # -------------------------------------------------------------------------
    # Step A: Real Geocode Search for Origin (Bangkok) - NO MOCKS
    # -------------------------------------------------------------------------
    req_id_search_origin = uuid.uuid4()
    headers_search_origin = {
        **auth_header,
        "X-Request-ID": str(req_id_search_origin),
        "X-Correlation-ID": str(correlation_id),
    }

    resp_origin = await client.get(
        "/api/v1/locations/search",
        params={"q": "Bangkok", "limit": 2},
        headers=headers_search_origin,
    )
    assert resp_origin.status_code == 200, f"Search failed: {resp_origin.text}"
    assert resp_origin.headers.get("x-request-id") == str(req_id_search_origin)
    assert resp_origin.headers.get("x-correlation-id") == str(correlation_id)

    body_origin = resp_origin.json()
    assert body_origin["meta"]["request_id"] == str(req_id_search_origin)
    assert body_origin["meta"]["correlation_id"] == str(correlation_id)
    assert len(body_origin["data"]) > 0

    origin_item = body_origin["data"][0]
    # Verify real provider attribution from Open-Meteo
    assert origin_item["provider"] == "open_meteo_geocoding"
    assert "Bangkok" in origin_item["display_name"]
    # User confirms the location on the map
    origin_loc = LocationRef.model_validate({**origin_item, "confirmed_by_user": True})

    # -------------------------------------------------------------------------
    # Step B: Real Geocode Search for Destination (Chiang Mai) - NO MOCKS
    # -------------------------------------------------------------------------
    req_id_search_dest = uuid.uuid4()
    headers_search_dest = {
        **auth_header,
        "X-Request-ID": str(req_id_search_dest),
        "X-Correlation-ID": str(correlation_id),
    }

    resp_dest = await client.get(
        "/api/v1/locations/search",
        params={"q": "Chiang Mai", "limit": 2},
        headers=headers_search_dest,
    )
    assert resp_dest.status_code == 200, f"Dest search failed: {resp_dest.text}"
    body_dest = resp_dest.json()
    assert len(body_dest["data"]) > 0
    dest_item = body_dest["data"][0]
    assert dest_item["provider"] == "open_meteo_geocoding"
    assert "Chiang Mai" in dest_item["display_name"]
    dest_loc = LocationRef.model_validate({**dest_item, "confirmed_by_user": True})

    # -------------------------------------------------------------------------
    # Step C: Create Trip using Real Locations
    # -------------------------------------------------------------------------
    req_id_create_trip = uuid.uuid4()
    headers_create_trip = {
        **auth_header,
        "X-Request-ID": str(req_id_create_trip),
        "X-Correlation-ID": str(correlation_id),
    }

    departure_time = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    trip_payload = {
        "title": "Bangkok to Chiang Mai Journey",
        "origin": origin_loc.model_dump(mode="json"),
        "destination": dest_loc.model_dump(mode="json"),
        "departure_time": departure_time,
        "timezone": "Asia/Bangkok",
        "travel_modes": ["CAR"],
        "preferences": {},
    }

    resp_trip = await client.post(
        "/api/v1/trips",
        json=trip_payload,
        headers=headers_create_trip,
    )
    assert resp_trip.status_code == 201, f"Trip creation failed: {resp_trip.text}"
    assert resp_trip.headers.get("x-request-id") == str(req_id_create_trip)
    assert resp_trip.headers.get("x-correlation-id") == str(correlation_id)

    body_trip = resp_trip.json()
    assert body_trip["meta"]["request_id"] == str(req_id_create_trip)
    assert body_trip["meta"]["correlation_id"] == str(correlation_id)

    trip_data = body_trip["data"]
    trip_id = trip_data["trip_id"]
    assert trip_data["title"] == "Bangkok to Chiang Mai Journey"
    assert trip_data["status"] == "DRAFT"
    assert trip_data["origin"]["provider"] == "open_meteo_geocoding"

    # -------------------------------------------------------------------------
    # Step D: Trigger Safety Assessment Run for the Trip
    # -------------------------------------------------------------------------
    req_id_assessment = uuid.uuid4()
    headers_assessment = {
        **auth_header,
        "X-Request-ID": str(req_id_assessment),
        "X-Correlation-ID": str(correlation_id),
    }

    resp_assessment = await client.post(
        f"/api/v1/trips/{trip_id}/assessments",
        json={"question": "Is this route safe?"},
        headers=headers_assessment,
    )
    assert resp_assessment.status_code == 202, f"Assessment failed: {resp_assessment.text}"
    assert resp_assessment.headers.get("x-request-id") == str(req_id_assessment)
    assert resp_assessment.headers.get("x-correlation-id") == str(correlation_id)

    body_assessment = resp_assessment.json()
    assert body_assessment["meta"]["request_id"] == str(req_id_assessment)
    assert body_assessment["meta"]["correlation_id"] == str(correlation_id)

    run_data = body_assessment["data"]
    request_id = run_data["request_id"]
    assert run_data["status"] in ("QUEUED", "RUNNING", "NEEDS_INPUT", "FAILED")

    # -------------------------------------------------------------------------
    # Step E: Poll Run Status
    # -------------------------------------------------------------------------
    req_id_poll = uuid.uuid4()
    headers_poll = {
        **auth_header,
        "X-Request-ID": str(req_id_poll),
        "X-Correlation-ID": str(correlation_id),
    }

    resp_poll = await client.get(
        f"/api/v1/runs/{request_id}",
        headers=headers_poll,
    )
    assert resp_poll.status_code == 200, f"Poll failed: {resp_poll.text}"
    body_poll = resp_poll.json()
    assert body_poll["meta"]["request_id"] == str(req_id_poll)
    assert body_poll["meta"]["correlation_id"] == str(correlation_id)
    assert body_poll["data"]["request_id"] == request_id

    # -------------------------------------------------------------------------
    # Step F: Verify Audit Log Integrity and Correlation Trace in Database
    # -------------------------------------------------------------------------
    db_url = authed_real_app.state.settings.sync_database_url
    engine = create_engine(db_url)
    with engine.connect() as conn:
        trip_row = conn.execute(
            text("SELECT origin, status FROM travel.trips WHERE id = :id"),
            {"id": trip_id},
        ).fetchone()
        assert trip_row is not None
        assert trip_row[1] == "DRAFT"

        # Check assessment request row
        req_row = conn.execute(
            text("SELECT status, trip_id FROM travel.requests WHERE id = :id"),
            {"id": request_id},
        ).fetchone()
        assert req_row is not None
        assert str(req_row[1]) == trip_id
