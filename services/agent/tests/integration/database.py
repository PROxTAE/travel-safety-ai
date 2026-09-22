"""Real PostgreSQL for integration tests.

Same two-path pattern as `services/api/tests/database.py`, adapted to this service's driver
(psycopg, not SQLAlchemy):

* **Inside compose** there is already a PostgreSQL next door and no Docker socket, so
  Testcontainers cannot work — `TEST_DATABASE_URL` points at the maintenance database and each run
  creates and drops its own throwaway database.
* **On a laptop** there is a Docker socket but no running stack, so Testcontainers starts one.

Either way the tests get a database nobody else is using.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest

#: Set by compose.dev.yaml (mirroring services/api). Points at the maintenance database, not at
#: the one under test.
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"


def docker_available() -> bool:
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

    `CREATE DATABASE` cannot run inside a transaction, hence `autocommit=True`. The name is random
    so two concurrent runs cannot collide.
    """
    name = f"sta_test_{secrets.token_hex(6)}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')

    parsed = psycopg.conninfo.conninfo_to_dict(admin_url)
    parsed["dbname"] = name
    try:
        yield psycopg.conninfo.make_conninfo(**parsed)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            # Terminate stragglers first: a connection pool that has not closed yet would make
            # DROP block, and the test session would hang instead of failing.
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@contextmanager
def provision_database() -> Iterator[str]:
    """A psycopg-ready DSN for a database that belongs to this test session alone."""
    configured = os.environ.get(TEST_DATABASE_URL_ENV)
    if configured:
        with _throwaway_database(configured) as url:
            yield url
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "postgis/postgis:16-3.4",
        username="agent_test",
        # Throwaway container, torn down with the session; the value never leaves this process.
        password="agent_test",
        dbname="smart_travel_test",
        driver=None,
    ) as container:
        yield container.get_connection_url(driver=None)
