"""Alembic environment for integration-owned schema."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from app.repositories.models import Base
from app.settings import get_settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="integration",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_settings().sync_database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS integration"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="integration",
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
