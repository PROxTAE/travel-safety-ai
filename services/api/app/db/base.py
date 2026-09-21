"""Declarative base and the schemas this service owns.

This service owns `identity` and `travel` and writes nowhere else. Other services reach its data
through the public API, never through the tables — a cross-schema read would make a schema change
in one module break another module silently.

The naming convention matters more than it looks: without it, Alembic autogenerate emits
migrations that drop and recreate unnamed constraints because it cannot tell which existing
constraint corresponds to which model.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

#: Schemas owned by module 02, per section 9 of the shared project context.
IDENTITY_SCHEMA = "identity"
TRAVEL_SCHEMA = "travel"
OWNED_SCHEMAS: tuple[str, ...] = (IDENTITY_SCHEMA, TRAVEL_SCHEMA)

#: Where this service's Alembic version table lives — separate from the two schemas that hold user
#: data, and separate from every other service's bookkeeping.
#:
#: Two reasons it is not `identity`. Seven services share one PostgreSQL instance, so a version
#: table in `public` would make each of them read the others' revisions as unknown heads. And a
#: version table inside `identity` would make `identity` undroppable, so the first migration could
#: never be downgraded — PostgreSQL refuses to drop a schema that still contains a table.
#:
#: `api` is the schema `infra/postgres/init/00-schemas.sql` already creates for this module.
BOOKKEEPING_SCHEMA = "api"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base for every ORM model in this service."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
