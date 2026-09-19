"""Migrations against a real PostgreSQL.

What is verified here cannot be verified against a fake: that an empty database reaches head, that
the version table does not collide with the six other services sharing the instance, and that a
downgrade refuses to take user data with it.

The database comes from `tests/database.py`, which uses the PostgreSQL next door when running
inside compose and starts a throwaway container otherwise. These tests take their own database
rather than the session-wide one, because they drop and recreate schemas.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.settings import get_settings
from tests.database import provision_database, requires_database

SERVICE_ROOT = Path(__file__).resolve().parents[1]

pytestmark = [pytest.mark.integration, requires_database]


@pytest.fixture(scope="module")
def migration_database_url() -> Iterator[str]:
    """A database used by this module alone: these tests drop schemas."""
    with provision_database() as url:
        yield url


@pytest.fixture
def alembic_config(
    migration_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Config]:
    """Alembic reads its URL from Settings, so the database details go via the environment."""
    url = make_url(migration_database_url)
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


def schemas_in(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return {
                row[0]
                for row in connection.execute(
                    text("SELECT schema_name FROM information_schema.schemata")
                )
            }
    finally:
        engine.dispose()


def tables_in(url: str, schema: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema"
                    ),
                    {"schema": schema},
                )
            }
    finally:
        engine.dispose()


def test_empty_database_reaches_head(alembic_config: Config, migration_database_url: str) -> None:
    """The check the acceptance runbook runs before anything else."""
    command.upgrade(alembic_config, "head")

    assert {"identity", "travel"} <= schemas_in(migration_database_url)
    assert "user_profiles" in tables_in(migration_database_url, "identity")


def test_version_table_is_isolated_from_other_services_and_from_user_data(
    alembic_config: Config, migration_database_url: str
) -> None:
    """Two failures at once are being prevented here.

    A version table in `public` would be shared with the six other services on this instance, and
    each would read the others' revisions as unknown heads. A version table inside `identity` would
    make that schema undroppable, so the first migration could never be downgraded.
    """
    command.upgrade(alembic_config, "head")

    assert "alembic_version" in tables_in(migration_database_url, "api")
    assert "alembic_version" not in tables_in(migration_database_url, "public")
    assert "alembic_version" not in tables_in(migration_database_url, "identity")


def test_upgrade_is_idempotent(alembic_config: Config) -> None:
    """Running it twice is what happens when a container restarts mid-deploy."""
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")


def test_downgrade_then_upgrade_returns_to_head(
    alembic_config: Config, migration_database_url: str
) -> None:
    """A rollback has to be exercised before it is needed, not during an incident."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    assert "travel" not in schemas_in(migration_database_url)

    command.upgrade(alembic_config, "head")


def test_each_revision_reverses_on_its_own(
    alembic_config: Config, migration_database_url: str
) -> None:
    """Stepping down one revision at a time has to work, not only dropping the whole stack.

    Targets are named rather than counted: `-1` moves with every new revision, so a relative test
    quietly starts checking something else the next time one is added.
    """
    command.upgrade(alembic_config, "head")

    # 0003 down: the phase 3 tables go, the phase 2 one stays.
    command.downgrade(alembic_config, "0002")
    identity_tables = tables_in(migration_database_url, "identity")
    assert "user_profiles" in identity_tables
    assert identity_tables & {"consents", "emergency_profiles", "audit_log"} == set()

    # 0002 down: the table goes, the schemas stay.
    command.downgrade(alembic_config, "0001")
    assert "user_profiles" not in tables_in(migration_database_url, "identity")
    assert {"identity", "travel"} <= schemas_in(migration_database_url)

    command.upgrade(alembic_config, "head")
    assert {"consents", "emergency_profiles", "audit_log", "data_subject_requests"} <= tables_in(
        migration_database_url, "identity"
    )


def test_downgrade_refuses_to_drop_a_schema_that_still_holds_data(
    alembic_config: Config, migration_database_url: str
) -> None:
    """`DROP SCHEMA` without CASCADE is the safety net: a downgrade run one step too far must not
    take a user's trips with it."""
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE travel.placeholder (id integer primary key)"))

    with pytest.raises(Exception, match="(?i)cannot drop|dependent objects"):
        command.downgrade(alembic_config, "base")

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE travel.placeholder"))
    engine.dispose()

    command.upgrade(alembic_config, "head")
