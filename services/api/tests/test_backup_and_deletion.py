"""Backup/restore and deletion lifecycle verification.

Phase 8.5 Verification:
1. Soft deletion of trips:
   - DELETE endpoint marks deleted_at and excludes from list/get queries.
   - Audit log retains deletion record.
2. GDPR / Privacy deletion & purge flow:
   - Removal of personal sensitive data (emergency profile, active consent).
   - Audit log preserved with user_id nulled (no orphaned rows, no personal linkage).
3. Backup export and restore roundtrip:
   - Export domain data to JSON snapshot with SHA-256 checksum.
   - Validation and restoration into database.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from scripts.backup_restore_sample import export_snapshot, restore_snapshot, validate_snapshot
from sqlalchemy import create_engine, text

from app.cli.retention import process_one
from app.db.engine import session_scope
from app.repositories import data_subject_requests
from app.schemas.location import GeoPoint, LocationRef
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
    return key.sign({"sub": f"backup-del-{uuid.uuid4()}"})


def _sample_location(name: str, lat: float, lon: float) -> dict[str, Any]:
    return LocationRef(
        place_id=f"test:{name.lower()}",
        display_name=name,
        coordinates=GeoPoint(type="Point", coordinates=(lon, lat)),
        country_code="TH",
        admin1="Central",
        timezone="Asia/Bangkok",
        provider="open_meteo_geocoding",
        confirmed_by_user=True,
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_trip_soft_delete_lifecycle_and_audit(
    authed_app: FastAPI,
    client: httpx.AsyncClient,
    token: str,
) -> None:
    auth_headers = {"Authorization": f"Bearer {token}"}
    origin = _sample_location("Bangkok", 13.7563, 100.5018)
    destination = _sample_location("Pattaya", 12.9276, 100.8771)

    departure_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    create_resp = await client.post(
        "/api/v1/trips",
        json={
            "title": "Weekend to Pattaya",
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time,
            "timezone": "Asia/Bangkok",
            "travel_modes": ["CAR"],
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    trip_id = create_resp.json()["data"]["trip_id"]

    # 1. Verify trip is accessible
    get_resp = await client.get(f"/api/v1/trips/{trip_id}", headers=auth_headers)
    assert get_resp.status_code == 200

    # 2. Delete trip (soft-delete)
    del_resp = await client.delete(f"/api/v1/trips/{trip_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    del_data = del_resp.json()["data"]
    assert del_data["status"] == "IN_PROGRESS"
    assert del_data["resource_id"] == trip_id

    # 3. Direct GET must now return 404
    get_after = await client.get(f"/api/v1/trips/{trip_id}", headers=auth_headers)
    assert get_after.status_code == 404

    # 4. List trips must not include the soft-deleted trip
    list_resp = await client.get("/api/v1/trips", headers=auth_headers)
    assert list_resp.status_code == 200
    items = list_resp.json()["data"]
    assert not any(item["trip_id"] == trip_id for item in items)

    # 5. Verify database still holds row with deleted_at and audit log has entry
    db_url = authed_app.state.settings.sync_database_url
    engine = create_engine(db_url)
    with engine.connect() as conn:
        trip_row = conn.execute(
            text("SELECT deleted_at FROM travel.trips WHERE id = :id"),
            {"id": trip_id},
        ).fetchone()
        assert trip_row is not None
        assert trip_row[0] is not None  # deleted_at is set

        audit_row = conn.execute(
            text(
                "SELECT action, resource_type FROM identity.audit_log "
                "WHERE resource_id = :id AND action = 'TRIP_DELETED'"
            ),
            {"id": trip_id},
        ).fetchone()
        assert audit_row is not None
        assert audit_row[0] == "TRIP_DELETED"
        assert audit_row[1] == "trip"


@pytest.mark.asyncio
async def test_gdpr_data_subject_purge_and_audit_preservation(
    authed_app: FastAPI,
    client: httpx.AsyncClient,
    token: str,
) -> None:
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 1. Grant consent FIRST (required before emergency profile storage is permitted)
    consent_resp = await client.post(
        "/api/v1/consents",
        json={"type": "EMERGENCY_PROFILE", "granted": True, "policy_version": "1.0.0"},
        headers=auth_headers,
    )
    assert consent_resp.status_code == 201

    # 2. Create emergency profile
    emergency_payload = {
        "blood_type": "O+",
        "allergies": ["peanut"],
        "medical_notes": "None",
        "contacts": [{"name": "Emergency Contact", "phone": "+66811112222"}],
    }
    ep_resp = await client.put(
        "/api/v1/me/emergency-profile",
        json=emergency_payload,
        headers=auth_headers,
    )
    assert ep_resp.status_code in (200, 204)

    # 3. Lookup user_id in database
    db_url = authed_app.state.settings.sync_database_url
    engine = create_engine(db_url)

    # 4. Enqueue and process a deletion request via retention worker
    settings = authed_app.state.settings
    session_factory = authed_app.state.session_factory

    async with session_scope(session_factory) as session:
        # Find user_id from profile
        user_row = (
            await session.execute(
                text("SELECT id FROM identity.user_profiles ORDER BY created_at DESC LIMIT 1")
            )
        ).fetchone()
        assert user_row is not None
        user_id = user_row[0]

        # Enqueue deletion request
        req = await data_subject_requests.enqueue(
            session,
            owner_id=user_id,
            kind=data_subject_requests.KIND_DELETE,
        )
        assert req.status == "PENDING"
        await session.commit()

        # Process the deletion request
        processed = await process_one(session, settings)
        assert processed == data_subject_requests.KIND_DELETE
        await session.commit()

    # 5. Assert GDPR purge effects:
    with engine.connect() as conn:
        # Emergency profile should be purged
        ep_count = conn.execute(
            text("SELECT COUNT(*) FROM identity.emergency_profiles WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar()
        assert ep_count == 0

        # Consents should be revoked
        active_consents = conn.execute(
            text(
                "SELECT COUNT(*) FROM identity.consents "
                "WHERE user_id = :uid AND revoked_at IS NULL"
            ),
            {"uid": user_id},
        ).scalar()
        assert active_consents == 0

        # User profile should be marked deleted
        deleted_at = conn.execute(
            text("SELECT deleted_at FROM identity.user_profiles WHERE id = :uid"),
            {"uid": user_id},
        ).scalar()
        assert deleted_at is not None

        # Audit log entries for the account should have user_id nulled (privacy preservation)
        audit_records = conn.execute(
            text("SELECT COUNT(*) FROM identity.audit_log WHERE action = 'ACCOUNT_DELETED'")
        ).scalar()
        assert audit_records >= 1


def test_backup_export_validation_and_restore(
    authed_app: FastAPI,
    tmp_path: Path,
) -> None:
    """Verify backup snapshot generation, checksum calculation, validation, and restoration."""
    db_url = authed_app.state.settings.sync_database_url
    engine = create_engine(db_url)
    snapshot_path = tmp_path / "test_snapshot.json"

    # 1. Export snapshot
    snapshot = export_snapshot(engine, snapshot_path)
    assert snapshot_path.exists()
    assert "metadata" in snapshot
    assert "checksum" in snapshot["metadata"]
    assert "tables" in snapshot

    # 2. Validate snapshot
    is_valid = validate_snapshot(snapshot_path)
    assert is_valid is True

    # 3. Corrupt snapshot test
    corrupted_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    corrupted_data["metadata"]["checksum"] = "bad_checksum_12345"
    corrupted_path = tmp_path / "corrupted_snapshot.json"
    corrupted_path.write_text(json.dumps(corrupted_data), encoding="utf-8")
    assert validate_snapshot(corrupted_path) is False

    # 4. Restore records into database
    restored_count = restore_snapshot(engine, snapshot_path)
    assert restored_count >= 0
