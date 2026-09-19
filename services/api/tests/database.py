"""Getting a real PostgreSQL to test against.

Two ways in, because the suite has to run in two places.

* **Inside compose** (`docker compose run --rm api uv run pytest`) there is already a PostgreSQL
  next door and no Docker socket, so Testcontainers cannot work. `TEST_DATABASE_URL` points at the
  maintenance database and each run creates and drops its own throwaway database.
* **On a laptop** there is a Docker socket but no running stack, so Testcontainers starts one.

Either way the tests get a database nobody else is using. Sharing one would make a migration test
that drops a schema delete another test's tables.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

#: Set by compose.dev.yaml. Points at the maintenance database, not at the one under test.
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


def docker_available() -> bool:
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


def database_available() -> bool:
    return bool(os.environ.get(TEST_DATABASE_URL_ENV)) or docker_available()


requires_database = pytest.mark.skipif(
    not database_available(),
    reason="no TEST_DATABASE_URL and no Docker; a real PostgreSQL is required",
)


@contextmanager
def _throwaway_database(admin_url: str) -> Iterator[str]:
    """Create a database for one test session and drop it afterwards.

    `CREATE DATABASE` cannot run inside a transaction, hence AUTOCOMMIT. The name is random so two
    concurrent runs — CI and a developer, or two pytest-xdist workers — cannot collide.
    """
    name = f"sta_test_{secrets.token_hex(6)}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        # render_as_string(hide_password=False), not str(): SQLAlchemy's __str__ masks the password
        # as "***", and the result is a URL that parses cleanly and then fails to authenticate.
        yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            # Terminate stragglers first: an engine that has not disposed yet would make DROP
            # block, and the test session would hang instead of failing.
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@contextmanager
def provision_database() -> Iterator[str]:
    """A synchronous (psycopg) URL for a database that belongs to this test session alone."""
    configured = os.environ.get(TEST_DATABASE_URL_ENV)
    if configured:
        with _throwaway_database(configured) as url:
            yield url
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "postgis/postgis:16-3.4",
        username="api_test",
        # Throwaway container, torn down with the session; the value never leaves this process.
        password="api_test",
        dbname="smart_travel_test",
        driver="psycopg",
    ) as container:
        yield container.get_connection_url()
