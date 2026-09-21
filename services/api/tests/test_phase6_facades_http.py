"""HTTP integration tests for Phase 6 public facades.

Tests:
1. GET /api/v1/recommendations/{recommendation_id} (revalidation, ownership, 404).
2. POST /api/v1/trips/{trip_id}/apply-route (optimistic concurrency, route validation, 202).
3. GET /api/v1/conversations & POST /api/v1/conversations/{id}/messages.
4. GET /api/v1/safety/events (bbox validation, layer filtering).
5. GET /api/v1/emergency/contacts (reviewed directory, coordinate bounds).
6. GET /api/v1/emergency/nearby (location consent check, 403 vs 200).
7. POST /api/v1/feedback (redaction, ownership, idempotency).
8. POST /api/v1/alert-subscriptions & DELETE /api/v1/alert-subscriptions/{id} (consent gating).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import Consent
from app.db.models.travel import AssessmentRequest, Trip
from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
def authed_app(live_app: FastAPI, key: SigningKeyPair) -> FastAPI:
    live_app.state.jwks = StubJwks.containing(key)
    return live_app


@pytest.fixture
async def client(authed_app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=authed_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def token(key: SigningKeyPair) -> str:
    return key.sign({"sub": f"phase6-user-{uuid.uuid4()}", "scope": "travel"})


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_trip(session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    trip_id = uuid.uuid4()
    now = datetime.now(UTC)
    stmt = insert(Trip).values(
        id=trip_id,
        user_id=user_id,
        status="PLANNED",
        origin={
            "display_name": "Bangkok, Thailand",
            "coordinates": {"type": "Point", "coordinates": [100.5018, 13.7563]},
            "provider": "nominatim",
            "confirmed_by_user": True,
        },
        destination={
            "display_name": "Chiang Mai, Thailand",
            "coordinates": {"type": "Point", "coordinates": [98.9853, 18.7883]},
            "provider": "nominatim",
            "confirmed_by_user": True,
        },
        departure_time=now,
        return_time=None,
        timezone="Asia/Bangkok",
        travel_modes=["CAR"],
        preferences={},
        selected_route_id=None,
        previous_selected_route_id=None,
        latest_request_id=None,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    await session.execute(stmt)
    await session.commit()
    return trip_id


@respx.mock
async def test_get_recommendation_by_id_owner(
    client: httpx.AsyncClient, token: str, db_session: AsyncSession
) -> None:
    # Resolve user
    me_resp = await client.get("/api/v1/me", headers=auth(token))
    assert me_resp.status_code == 200
    user_id = uuid.UUID(me_resp.json()["data"]["user_id"])

    trip_id = await _create_trip(db_session, user_id)
    rec_id = uuid.uuid4()
    run_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Insert assessment request
    stmt = insert(AssessmentRequest).values(
        id=run_id,
        user_id=user_id,
        trip_id=trip_id,
        status="COMPLETED",
        recommendation_id=rec_id,
        input_digest="digest-123",
        contract_version="1.0.0",
        locale="en-US",
        timezone="UTC",
        created_at=now,
        updated_at=now,
    )
    await db_session.execute(stmt)
    await db_session.commit()

    # Mock module 08 response
    respx.get(f"http://recommendation:8006/internal/v1/recommendations/{rec_id}").respond(
        status_code=200,
        json={
            "data": {
                "recommendation_id": str(rec_id),
                "request_id": str(run_id),
                "trip_id": str(trip_id),
                "status": "COMPLETED",
                "action_code": "NORMAL",
                "risk_level": "LOW",
                "confidence": 0.95,
                "short_summary": "Weather conditions are clear.",
                "immediate_actions": [],
                "reasons": [{"code": "CLEAR_WEATHER", "message": "No hazards detected"}],
                "primary_route": None,
                "alternatives": [],
                "alerts": [],
                "emergency_instructions": [],
                "official_contacts": [],
                "sources": [{"provider": "TMD", "retrieved_at": now.isoformat()}],
                "freshness": {
                    "observed_at": now.isoformat(),
                    "fetched_at": now.isoformat(),
                    "expires_at": None,
                },
                "limitations": [],
                "degraded_services": [],
                "versions": {
                    "contract": "1.0.0",
                },
                "expires_at": None,
                "created_at": now.isoformat(),
            },
            "meta": {
                "request_id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "contract_version": "1.0.0",
                "generated_at": now.isoformat(),
                "degraded_services": [],
            },
        },
    )

    resp = await client.get(f"/api/v1/recommendations/{rec_id}", headers=auth(token))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["recommendation_id"] == str(rec_id)
    assert data["action_code"] == "NORMAL"


async def test_get_recommendation_unowned_returns_404(
    client: httpx.AsyncClient, token: str
) -> None:
    # Resolve user
    me_resp = await client.get("/api/v1/me", headers=auth(token))
    assert me_resp.status_code == 200

    unknown_rec = uuid.uuid4()
    resp = await client.get(f"/api/v1/recommendations/{unknown_rec}", headers=auth(token))
    assert resp.status_code == 404


@respx.mock
async def test_apply_route_lifecycle(
    client: httpx.AsyncClient, token: str, db_session: AsyncSession
) -> None:
    me_resp = await client.get("/api/v1/me", headers=auth(token))
    assert me_resp.status_code == 200
    user_id = uuid.UUID(me_resp.json()["data"]["user_id"])
    trip_id = await _create_trip(db_session, user_id)
    rec_id = uuid.uuid4()
    run_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Insert assessment
    stmt = insert(AssessmentRequest).values(
        id=run_id,
        user_id=user_id,
        trip_id=trip_id,
        status="COMPLETED",
        recommendation_id=rec_id,
        input_digest="digest-123",
        contract_version="1.0.0",
        locale="en-US",
        timezone="UTC",
        created_at=now,
        updated_at=now,
    )
    await db_session.execute(stmt)
    await db_session.commit()

    # 1. Medium risk without acknowledgement -> 422
    payload = {
        "recommendation_id": str(rec_id),
        "route_id": "route-medium-1",
        "risk_acknowledged": False,
    }
    # Mock recommendation response from module 08
    respx.get(f"http://recommendation:8006/internal/v1/recommendations/{rec_id}").respond(
        status_code=200,
        json={
            "data": {
                "recommendation_id": str(rec_id),
                "request_id": str(run_id),
                "trip_id": str(trip_id),
                "status": "COMPLETED",
                "action_code": "CHANGE_ROUTE",
                "risk_level": "MEDIUM",
                "confidence": 0.9,
                "short_summary": "Heavy rain on route.",
                "immediate_actions": [],
                "reasons": [],
                "primary_route": None,
                "alternatives": [
                    {
                        "route_id": "route-medium-1",
                        "risk_level": "MEDIUM",
                        "distance_m": 50000,
                        "duration_s": 3600,
                        "travel_mode": "CAR",
                    }
                ],
                "alerts": [],
                "emergency_instructions": [],
                "official_contacts": [],
                "sources": [{"provider": "TMD", "retrieved_at": now.isoformat()}],
                "freshness": {
                    "observed_at": now.isoformat(),
                    "fetched_at": now.isoformat(),
                    "expires_at": None,
                },
                "limitations": [],
                "degraded_services": [],
                "versions": {
                    "contract": "1.0.0",
                },
                "expires_at": None,
                "created_at": now.isoformat(),
            },
            "meta": {
                "request_id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "contract_version": "1.0.0",
                "generated_at": now.isoformat(),
                "degraded_services": [],
            },
        },
    )

    resp_fail = await client.post(
        f"/api/v1/trips/{trip_id}/apply-route",
        headers={**auth(token), "If-Match": '"1"'},
        json=payload,
    )
    assert resp_fail.status_code == 422

    # 2. Concurrency check: wrong If-Match -> 412
    resp_412 = await client.post(
        f"/api/v1/trips/{trip_id}/apply-route",
        headers={**auth(token), "If-Match": '"99"'},
        json={**payload, "risk_acknowledged": True},
    )
    assert resp_412.status_code == 412

    # Mock agent start for accepted apply-route
    respx.post("http://agent:8001/internal/v1/runs").respond(
        status_code=202,
        json={
            "data": {
                "request_id": str(uuid.uuid4()),
                "status": "QUEUED",
                "submitted_at": now.isoformat(),
            },
            "meta": {
                "request_id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "contract_version": "1.0.0",
                "generated_at": now.isoformat(),
                "degraded_services": [],
            },
        },
    )

    # 3. Successful apply -> 202
    resp_ok = await client.post(
        f"/api/v1/trips/{trip_id}/apply-route",
        headers={**auth(token), "If-Match": '"1"'},
        json={**payload, "risk_acknowledged": True},
    )
    assert resp_ok.status_code == 202
    res_data = resp_ok.json()["data"]
    assert res_data["trip"]["revision"] == 2


@respx.mock
async def test_list_conversations_and_post_message(
    client: httpx.AsyncClient, token: str, db_session: AsyncSession
) -> None:
    me_resp = await client.get("/api/v1/me", headers=auth(token))
    assert me_resp.status_code == 200
    user_id = uuid.UUID(me_resp.json()["data"]["user_id"])
    trip_id = await _create_trip(db_session, user_id)
    conv_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Insert a conversation turn
    stmt = insert(AssessmentRequest).values(
        id=uuid.uuid4(),
        user_id=user_id,
        trip_id=trip_id,
        conversation_id=conv_id,
        status="COMPLETED",
        input_digest="digest-123",
        contract_version="1.0.0",
        locale="en-US",
        timezone="UTC",
        created_at=now,
        updated_at=now,
    )
    await db_session.execute(stmt)
    await db_session.commit()

    # 1. List conversations
    resp = await client.get("/api/v1/conversations", headers=auth(token))
    assert resp.status_code == 200
    convs = resp.json()["data"]
    assert len(convs) >= 1
    assert any(c["conversation_id"] == str(conv_id) for c in convs)

    # Mock agent start
    respx.post("http://agent:8001/internal/v1/runs").respond(
        status_code=202,
        json={
            "data": {
                "request_id": str(uuid.uuid4()),
                "status": "QUEUED",
                "submitted_at": now.isoformat(),
            },
            "meta": {
                "request_id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "contract_version": "1.0.0",
                "generated_at": now.isoformat(),
                "degraded_services": [],
            },
        },
    )

    # 2. Post follow-up question
    msg_resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=auth(token),
        json={"question": "What about the alternative route?"},
    )
    assert msg_resp.status_code == 202
    run_ref = msg_resp.json()["data"]
    assert run_ref["status"] in ("QUEUED", "RUNNING")


@respx.mock
async def test_safety_events_viewport(client: httpx.AsyncClient, token: str) -> None:
    now = datetime.now(UTC)
    respx.post("http://external-data:8002/internal/v1/disasters/query").respond(
        status_code=200,
        json={
            "data": {
                "events": [
                    {
                        "event_id": "flood-101",
                        "event_type": "FLOOD",
                        "title": "Flash Flood Warning",
                        "severity": "MODERATE",
                        "geometry": {"type": "Point", "coordinates": [100.5, 13.7]},
                        "effective_at": now.isoformat(),
                        "expires_at": None,
                        "quality": {
                            "freshness": "FRESH",
                            "completeness": 1.0,
                            "provider_count": 1,
                            "authoritative_ratio": 1.0,
                            "degraded": False,
                            "flags": [],
                            "oldest_observed_at": now.isoformat(),
                        },
                        "source": {
                            "provider": "GDACS",
                            "authority": "INTERGOVERNMENTAL",
                            "published_at": now.isoformat(),
                            "attribution": "GDACS",
                        },
                    }
                ],
                "attribution": [],
            },
            "meta": {
                "request_id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "contract_version": "1.0.0",
                "generated_at": now.isoformat(),
                "degraded_services": [],
            },
        },
    )

    # 1. Invalid bbox -> 400
    bad_resp = await client.get("/api/v1/safety/events?bbox=abc,def", headers=auth(token))
    assert bad_resp.status_code == 400

    # 2. Valid bbox -> 200
    resp = await client.get("/api/v1/safety/events?bbox=98.0,5.0,105.0,20.0", headers=auth(token))
    assert resp.status_code == 200
    events = resp.json()["data"]
    assert len(events) == 1
    assert events[0]["event_id"] == "flood-101"
    assert events[0]["layer"] == "DISASTER"


async def test_emergency_contacts_directory(client: httpx.AsyncClient, token: str) -> None:
    # Bangkok coordinates -> TH emergency numbers
    resp = await client.get(
        "/api/v1/emergency/contacts?latitude=13.7563&longitude=100.5018", headers=auth(token)
    )
    assert resp.status_code == 200
    contacts = resp.json()["data"]
    assert len(contacts) >= 4
    police = next(c for c in contacts if c["service_type"] == "POLICE")
    assert police["phone"] == "191"

    # Middle of ocean -> empty list (unavailable state)
    resp_empty = await client.get(
        "/api/v1/emergency/contacts?latitude=0.0&longitude=0.0",
        headers=auth(token),
    )
    assert resp_empty.status_code == 200
    assert resp_empty.json()["data"] == []


@respx.mock
async def test_emergency_nearby_consent_gating(
    client: httpx.AsyncClient, token: str, db_session: AsyncSession
) -> None:
    me_resp = await client.get("/api/v1/me", headers=auth(token))
    assert me_resp.status_code == 200
    user_id = uuid.UUID(me_resp.json()["data"]["user_id"])

    # 1. Without location consent -> 403
    resp_403 = await client.get(
        "/api/v1/emergency/nearby?latitude=13.7563&longitude=100.5018&type=HOSPITAL",
        headers=auth(token),
    )
    assert resp_403.status_code == 403

    # 2. Grant LOCATION_ONCE consent
    now = datetime.now(UTC)
    consent_id = uuid.uuid4()
    stmt = insert(Consent).values(
        id=consent_id,
        user_id=user_id,
        type="LOCATION_ONCE",
        granted=True,
        policy_version="1.0.0",
        granted_at=now,
        revoked_at=None,
        expires_at=None,
    )
    await db_session.execute(stmt)
    await db_session.commit()

    try:
        # Mock module 04 places nearby
        respx.post("http://external-data:8002/internal/v1/places/nearby").respond(
            status_code=200,
            json={
                "data": {
                    "results": [
                        {
                            "poi_id": "hospital-1",
                            "poi_type": "HOSPITAL",
                            "name": "Bangkok General Hospital",
                            "location": {"type": "Point", "coordinates": [100.583, 13.748]},
                            "address": "2 Soi Soonvijai 7, New Phetchaburi Rd",
                            "phone": "+6623103000",
                            "distance_m": 1200.0,
                            "open_now": True,
                            "quality": {
                                "freshness": "FRESH",
                                "completeness": 1.0,
                                "provider_count": 1,
                                "authoritative_ratio": 1.0,
                                "degraded": False,
                                "flags": [],
                                "oldest_observed_at": now.isoformat(),
                            },
                            "source": {
                                "provider": "OpenStreetMap",
                                "authority": "COMMUNITY",
                                "published_at": now.isoformat(),
                                "attribution": "OSM",
                            },
                        }
                    ],
                    "attribution": [],
                },
                "meta": {
                    "request_id": str(uuid.uuid4()),
                    "correlation_id": str(uuid.uuid4()),
                    "contract_version": "1.0.0",
                    "generated_at": now.isoformat(),
                    "degraded_services": [],
                },
            },
        )

        resp_ok = await client.get(
            "/api/v1/emergency/nearby?latitude=13.7563&longitude=100.5018&type=HOSPITAL",
            headers=auth(token),
        )
        assert resp_ok.status_code == 200
        pois = resp_ok.json()["data"]
        assert len(pois) == 1
        assert pois[0]["name"] == "Bangkok General Hospital"
    finally:
        from sqlalchemy import delete

        await db_session.execute(delete(Consent).where(Consent.id == consent_id))
        await db_session.commit()


@respx.mock
async def test_feedback_and_redaction(
    client: httpx.AsyncClient, token: str, db_session: AsyncSession
) -> None:
    me_resp = await client.get("/api/v1/me", headers=auth(token))
    assert me_resp.status_code == 200
    user_id = uuid.UUID(me_resp.json()["data"]["user_id"])
    trip_id = await _create_trip(db_session, user_id)
    rec_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Insert assessment request
    stmt = insert(AssessmentRequest).values(
        id=uuid.uuid4(),
        user_id=user_id,
        trip_id=trip_id,
        status="COMPLETED",
        recommendation_id=rec_id,
        input_digest="digest-123",
        contract_version="1.0.0",
        locale="en-US",
        timezone="UTC",
        created_at=now,
        updated_at=now,
    )
    await db_session.execute(stmt)
    await db_session.commit()

    # Mock module 08 feedback
    respx.post("http://recommendation:8006/internal/v1/feedback").respond(
        status_code=201, json={"status": "ok"}
    )

    payload = {
        "recommendation_id": str(rec_id),
        "category": "UNSAFE",
        "text": "Road is flooded near test@example.com or call 081-234-5678",
    }
    idem_key = f"fb-{uuid.uuid4()}"

    resp = await client.post(
        "/api/v1/feedback",
        headers={**auth(token), "Idempotency-Key": idem_key},
        json=payload,
    )
    assert resp.status_code == 201
    fb_data = resp.json()["data"]
    assert fb_data["category"] == "UNSAFE"
    # Ensure sensitive info was redacted
    assert "test@example.com" not in fb_data["text_redacted"]
    assert "[REDACTED" in fb_data["text_redacted"]

    # Idempotency replay
    replay = await client.post(
        "/api/v1/feedback",
        headers={**auth(token), "Idempotency-Key": idem_key},
        json=payload,
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["feedback_id"] == fb_data["feedback_id"]


@respx.mock
async def test_alert_subscription_lifecycle(
    client: httpx.AsyncClient, token: str, db_session: AsyncSession
) -> None:
    me_resp = await client.get("/api/v1/me", headers=auth(token))
    assert me_resp.status_code == 200
    user_id = uuid.UUID(me_resp.json()["data"]["user_id"])
    trip_id = await _create_trip(db_session, user_id)
    consent_id = uuid.uuid4()
    now = datetime.now(UTC)

    payload = {
        "trip_id": str(trip_id),
        "channel": "PUSH",
        "consent_id": str(consent_id),
        "min_severity": "MODERATE",
    }

    # 1. Missing ALERT_NOTIFICATION consent -> 403
    resp_403 = await client.post("/api/v1/alert-subscriptions", headers=auth(token), json=payload)
    assert resp_403.status_code == 403

    # 2. Grant consent
    stmt = insert(Consent).values(
        id=consent_id,
        user_id=user_id,
        type="ALERT_NOTIFICATION",
        granted=True,
        policy_version="1.0.0",
        granted_at=now,
        revoked_at=None,
        expires_at=None,
    )
    await db_session.execute(stmt)
    await db_session.commit()

    try:
        # Mock module 08 create/delete alert subscription
        respx.post("http://recommendation:8006/internal/v1/alert-subscriptions").respond(
            status_code=201, json={"status": "ok"}
        )
        delete_url_re = re.compile(
            r"^http://recommendation:8006/internal/v1/alert-subscriptions/.*"
        )
        respx.delete(url=delete_url_re).respond(status_code=204)

        # 3. Create subscription -> 201
        resp_201 = await client.post(
            "/api/v1/alert-subscriptions", headers=auth(token), json=payload
        )
        assert resp_201.status_code == 201
        sub_data = resp_201.json()["data"]
        assert sub_data["status"] == "ACTIVE"
        sub_id = sub_data["subscription_id"]

        # 4. Delete subscription -> 204
        del_resp = await client.delete(f"/api/v1/alert-subscriptions/{sub_id}", headers=auth(token))
        assert del_resp.status_code == 204
    finally:
        from sqlalchemy import delete

        await db_session.execute(delete(Consent).where(Consent.id == consent_id))
        await db_session.commit()
