"""Migrations against a real PostgreSQL.

Marked `integration` and skipped without Docker, because the fast suite has to stay fast. What is
verified here cannot be verified against a fake: that an empty database reaches head, that the
version table lands in this service's own schema instead of colliding with the six other services
sharing the instance, and that a downgrade refuses to take user data with it.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

SERVICE_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    """Ask the daemon rather than guessing from a socket path.

    Docker Desktop on Windows listens on a named pipe, a remote engine on a TCP endpoint, and
    rootless Docker on a socket under the user's runtime directory. Probing paths gets at least one
    of those wrong and silently skips the tests that matter most.
    """
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, resolved binary
            [docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


requires_docker = pytest.mark.skipif(
    not _docker_available(), reason="Docker is not available; integration tests are skipped"
)


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """A throwaway PostgreSQL with PostGIS, matching the image compose runs."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "postgis/postgis:16-3.4",
        username="migration_test",
        # Throwaway container, torn down with the test; the value never leaves this process.
        password="migration_test",
        dbname="smart_travel_test",
        driver="psycopg",
    ) as container:
        yield container.get_connection_url()


@pytest.fixture
def alembic_config(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic reads its URL from Settings, so the container credentials go via the environment."""
    from sqlalchemy.engine import make_url

    from app.settings import get_settings

    url = make_url(postgres_url)
    monkeypatch.setenv("POSTGRES_HOST", url.host or "localhost")
    monkeypatch.setenv("POSTGRES_PORT", str(url.port))
    monkeypatch.setenv("POSTGRES_DB", url.database or "smart_travel_test")
    monkeypatch.setenv("POSTGRES_USER", url.username or "migration_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", url.password or "migration_test")
    get_settings.cache_clear()

    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    yield config
    get_settings.cache_clear()


@requires_docker
def test_empty_database_reaches_head(alembic_config: Config, postgres_url: str) -> None:
    """The check the acceptance runbook runs before anything else."""
    command.upgrade(alembic_config, "head")

    engine = create_engine(postgres_url)
    with engine.connect() as connection:
        schemas = {
            row[0]
            for row in connection.execute(
                text("SELECT schema_name FROM information_schema.schemata")
            )
        }
    engine.dispose()

    assert {"identity", "travel"} <= schemas


@requires_docker
def test_version_table_is_isolated_from_other_services_and_from_user_data(
    alembic_config: Config, postgres_url: str
) -> None:
    """Two failures at once are being prevented here.

    A version table in `public` would be shared with the six other services on this instance, and
    each would read the others' revisions as unknown heads. A version table inside `identity` would
    make that schema undroppable, so the first migration could never be downgraded.
    """
    command.upgrade(alembic_config, "head")

    def count_in(schema: str) -> int:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_name = 'alembic_version'"
                ),
                {"schema": schema},
            ).scalar_one()

    engine = create_engine(postgres_url)
    try:
        assert count_in("api") == 1
        assert count_in("public") == 0
        assert count_in("identity") == 0
    finally:
        engine.dispose()


@requires_docker
def test_upgrade_is_idempotent(alembic_config: Config) -> None:
    """Running it twice is what happens when a container restarts mid-deploy."""
    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")


@requires_docker
def test_downgrade_then_upgrade_returns_to_head(alembic_config: Config, postgres_url: str) -> None:
    """A rollback has to be exercised before it is needed, not during an incident."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = create_engine(postgres_url)
    with engine.connect() as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                text("SELECT schema_name FROM information_schema.schemata")
            )
        }
    engine.dispose()

    assert "travel" not in remaining

    command.upgrade(alembic_config, "head")


@requires_docker
def test_downgrade_refuses_to_drop_a_schema_that_still_holds_data(
    alembic_config: Config, postgres_url: str
) -> None:
    """`DROP SCHEMA` without CASCADE is the safety net: a downgrade run one step too far must not
    take a user's trips with it."""
    command.upgrade(alembic_config, "head")

    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE travel.placeholder (id integer primary key)"))

    with pytest.raises(Exception, match="(?i)cannot drop|dependent objects"):
        command.downgrade(alembic_config, "base")

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE travel.placeholder"))
    engine.dispose()
