"""Real isolated PostgreSQL test database for storage tests."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.settings import get_settings


@pytest.fixture(scope="session")
def isolated_database() -> Iterator[str]:
    maintenance = os.environ.get("TEST_DATABASE_URL")
    if not maintenance:
        pytest.fail("TEST_DATABASE_URL must point to a real PostgreSQL maintenance database")
    database = f"integration_test_{uuid4().hex}"
    admin = create_engine(maintenance, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    test_url = make_url(maintenance).set(database=database)
    old_db = os.environ.get("POSTGRES_DB")
    os.environ["POSTGRES_DB"] = database
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        yield test_url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    finally:
        if old_db is None:
            os.environ.pop("POSTGRES_DB", None)
        else:
            os.environ["POSTGRES_DB"] = old_db
        get_settings.cache_clear()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()
