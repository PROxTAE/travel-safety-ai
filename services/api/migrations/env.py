"""Alembic environment for the public API service.

Two decisions differ from the generated default and both matter:

**The version table lives in this service's own schema.** Seven services share one PostgreSQL
instance in local development. With the default `public.alembic_version`, they would all write to
one table and each would see the others' revisions as unknown heads.

**Autogenerate only ever looks at the schemas this service owns.** Without the filter it would
notice `integration`, `knowledge` and the rest and helpfully offer to drop them.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.base import BOOKKEEPING_SCHEMA, OWNED_SCHEMAS, Base
from app.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

#: Alembic's bookkeeping. Kept out of the schemas that hold user data so that those stay
#: droppable on a downgrade; see app/db/base.py for the full reasoning.
VERSION_TABLE = "alembic_version"
VERSION_TABLE_SCHEMA = BOOKKEEPING_SCHEMA


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Ignore anything outside `identity` and `travel`."""
    schema = getattr(obj, "schema", None)
    if type_ == "table" and schema is not None:
        return schema in OWNED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Emit SQL without connecting, for review before applying to a shared environment."""
    context.configure(
        url=get_settings().sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_TABLE_SCHEMA,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database."""
    settings = get_settings()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.sync_database_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # a migration run is one short-lived connection
    )

    with connectable.connect() as connection:
        # Alembic creates its version table before it runs the first revision, so the schema that
        # holds it has to exist beforehand — the revision that creates it has not run yet. This is
        # the one piece of DDL that cannot live in a migration; it is idempotent, and revision 0001
        # still declares both schemas so the intent is recorded where a reviewer looks for it.
        connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{VERSION_TABLE_SCHEMA}"')
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            version_table=VERSION_TABLE,
            version_table_schema=VERSION_TABLE_SCHEMA,
            compare_type=True,
            compare_server_default=True,
            # One transaction per migration, so a failure halfway leaves the database on a
            # revision that exists rather than in a state no revision describes.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
