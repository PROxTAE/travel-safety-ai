"""Alembic environment - async, schema-scoped to `provider`.

The version table lives inside the module's own schema so each service keeps an
independent migration history (delivery rules § 10).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy.engine import Connection

from app.repositories.db import build_engine
from app.repositories.models import SCHEMA, Base
from app.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="alembic_version",
        version_table_schema=SCHEMA,
        include_schemas=True,
        # Only ever touch our own schema, even if autogenerate sees others.
        include_object=lambda obj, name, type_, reflected, compare_to: (
            getattr(obj, "schema", SCHEMA) in (SCHEMA, None)
        ),
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    # Alembic creates its own version table before the first migration runs, so
    # the schema has to exist by now - a CREATE SCHEMA inside revision 0001 is
    # already too late on an empty database.
    connection.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    connection.commit()
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = build_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
