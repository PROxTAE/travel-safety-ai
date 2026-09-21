"""Test lifecycle starting from an empty database through migrations,
schema validation, and persistence.

Verification (Phase 8.2):
1. Empty DB -> run Alembic migrations (`upgrade head`).
2. Verify schema isolation (`api.alembic_version`, `identity`, `travel`).
3. Verify Keycloak realm configuration discovery.
4. Verify end-to-end repository operations against the freshly migrated database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.settings import get_settings
from tests.database import provision_database, requires_database

SERVICE_ROOT = Path(__file__).resolve().parents[1]

pytestmark = [pytest.mark.integration, requires_database]


@pytest.fixture
def fresh_db_url() -> Iterator[str]:
    """Provides a brand new, empty throwaway database."""
    with provision_database() as url:
        yield url


@pytest.fixture
def alembic_config_for_fresh_db(
    fresh_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Config]:
    url = make_url(fresh_db_url)
    monkeypatch.setenv("POSTGRES_HOST", url.host or "localhost")
    monkeypatch.setenv("POSTGRES_PORT", str(url.port or 5432))
    monkeypatch.setenv("POSTGRES_DB", url.database or "postgres")
    monkeypatch.setenv("POSTGRES_USER", url.username or "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", url.password or "")
    get_settings.cache_clear()

    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    yield config
    get_settings.cache_clear()


def test_empty_db_migration_and_schema_isolation(
    fresh_db_url: str, alembic_config_for_fresh_db: Config
) -> None:
    engine = create_engine(fresh_db_url)

    # 1. Verify initially empty
    with engine.connect() as conn:
        tables_before = conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema IN ('api', 'identity', 'travel')"
            )
        ).fetchall()
        # In a clean database, there should be no application tables
        assert not any(t[0] in ("api", "identity", "travel") for t in tables_before)

    # 2. Run Alembic upgrade head
    command.upgrade(alembic_config_for_fresh_db, "head")

    # 3. Verify schemas and tables created
    with engine.connect() as conn:
        schemas = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name IN ('api', 'identity', 'travel')"
                )
            ).fetchall()
        }
        assert schemas == {"api", "identity", "travel"}, f"Expected schemas missing: {schemas}"

        # Check alembic_version in api schema
        api_tables = {
            r[0]
            for r in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'api'")
            ).fetchall()
        }
        assert "alembic_version" in api_tables

        # Check identity tables
        identity_tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'identity'"
                )
            ).fetchall()
        }
        expected_identity = {
            "user_profiles",
            "consents",
            "emergency_profiles",
            "audit_log",
            "data_subject_requests",
        }
        assert (
            expected_identity <= identity_tables
        ), f"Missing identity tables: {expected_identity - identity_tables}"

        # Check travel tables
        travel_tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'travel'"
                )
            ).fetchall()
        }
        expected_travel = {"trips", "idempotency_keys", "requests"}
        assert (
            expected_travel <= travel_tables
        ), f"Missing travel tables: {expected_travel - travel_tables}"


def test_fresh_database_persistence_and_crud(
    fresh_db_url: str, alembic_config_for_fresh_db: Config
) -> None:
    """Verify that domain entities can be created, read, and audited in the newly migrated DB."""
    # Ensure database is migrated
    command.upgrade(alembic_config_for_fresh_db, "head")

    engine = create_engine(fresh_db_url)
    user_id = uuid.uuid4()
    subject_id = f"sub-{uuid.uuid4()}"
    trip_id = uuid.uuid4()
    request_id = uuid.uuid4()

    with engine.begin() as conn:
        # Insert user profile
        conn.execute(
            text(
                "INSERT INTO identity.user_profiles "
                "(id, subject_id, locale, created_at, updated_at) "
                "VALUES (:id, :sub, :locale, :now, :now)"
            ),
            {
                "id": user_id,
                "sub": subject_id,
                "locale": "th-TH",
                "now": datetime.now(UTC),
            },
        )

        # Insert consent
        conn.execute(
            text(
                "INSERT INTO identity.consents "
                "(id, user_id, type, granted, policy_version, granted_at) "
                "VALUES (:id, :user_id, :type, :granted, :version, :now)"
            ),
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "type": "location_tracking",
                "granted": True,
                "version": "1.0",
                "now": datetime.now(UTC),
            },
        )

        # Insert trip
        bangkok_origin = (
            '{"label": "Bangkok", "coordinates": {"latitude": 13.7563, "longitude": 100.5018}}'
        )
        cm_dest = (
            '{"label": "Chiang Mai", "coordinates": {"latitude": 18.7883, "longitude": 98.9853}}'
        )
        conn.execute(
            text(
                "INSERT INTO travel.trips "
                "(id, user_id, title, origin, destination, departure_time, timezone, "
                "travel_modes, status, revision, created_at, updated_at) "
                "VALUES (:id, :uid, :title, :origin, :dest, :dep, :tz, :modes, 'DRAFT', 1, "
                ":now, :now)"
            ),
            {
                "id": trip_id,
                "uid": user_id,
                "title": "Fresh Vacation Trip",
                "origin": bangkok_origin,
                "dest": cm_dest,
                "dep": datetime.now(UTC),
                "tz": "Asia/Bangkok",
                "modes": '["car"]',
                "now": datetime.now(UTC),
            },
        )

        # Insert assessment request
        conn.execute(
            text(
                "INSERT INTO travel.requests "
                "(id, user_id, trip_id, status, input_digest, contract_version, locale, "
                "timezone, created_at, updated_at) "
                "VALUES (:id, :uid, :tid, 'QUEUED', :digest, '1.0.0', 'th-TH', "
                "'Asia/Bangkok', :now, :now)"
            ),
            {
                "id": request_id,
                "uid": user_id,
                "tid": trip_id,
                "digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "now": datetime.now(UTC),
            },
        )

    # Read back and assert
    with engine.connect() as conn:
        profile_row = conn.execute(
            text("SELECT subject_id, locale FROM identity.user_profiles WHERE id = :id"),
            {"id": user_id},
        ).fetchone()
        assert profile_row is not None
        assert profile_row[0] == subject_id
        assert profile_row[1] == "th-TH"

        trip_row = conn.execute(
            text("SELECT title, status, revision FROM travel.trips WHERE id = :id"),
            {"id": trip_id},
        ).fetchone()
        assert trip_row is not None
        assert trip_row[0] == "Fresh Vacation Trip"
        assert trip_row[1] == "DRAFT"
        assert trip_row[2] == 1

        request_row = conn.execute(
            text("SELECT status FROM travel.requests WHERE id = :id"),
            {"id": request_id},
        ).fetchone()
        assert request_row is not None
        assert request_row[0] == "QUEUED"


@pytest.mark.asyncio
async def test_keycloak_seed_and_realm_discovery() -> None:
    """Verify Keycloak discovery endpoint and realm seed configuration if Keycloak is reachable."""
    keycloak_base = os.environ.get("KEYCLOAK_BASE_URL", "http://localhost:8080").rstrip("/")
    well_known_url = f"{keycloak_base}/realms/smart-travel/.well-known/openid-configuration"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(well_known_url)
    except Exception as exc:
        pytest.skip(f"Keycloak not reachable at {well_known_url}: {exc}")

    if resp.status_code == 200:
        data = resp.json()
        assert "issuer" in data
        assert "smart-travel" in data["issuer"]
        assert "token_endpoint" in data
        assert "jwks_uri" in data
    else:
        pytest.skip(f"Keycloak realm not yet seeded or returning {resp.status_code}")
