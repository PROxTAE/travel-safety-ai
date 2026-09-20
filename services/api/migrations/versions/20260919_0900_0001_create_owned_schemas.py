"""Create the identity and travel schemas this service owns.

Revision ID: 0001
Revises:
Create date: 2026-09-19

Why:
    Section 9 of the shared project context gives module 02 two schemas, `identity` and `travel`.
    They are created here rather than in `infra/postgres/init/00-schemas.sql` for two reasons: that
    script runs only when the PostgreSQL volume is created for the first time, so an existing
    development database would never get them; and it is a shared surface owned by the lead, while
    this migration belongs to the service that needs the schemas.

    The bootstrap script creates a single `api` schema for this module rather than these two. The
    two are reconciled rather than duplicated: `api` holds this service's Alembic version table, and
    `identity` and `travel` hold the user data the contract document assigns to them. Nothing the
    lead owns is changed by this migration.

Data impact:
    None. Creates two empty schemas and grants the service role usage on them. `IF NOT EXISTS`
    makes it safe to run against a database where the schemas were already created by hand.

Downgrade:
    Drops both schemas, but only when they are empty — `DROP SCHEMA` without `CASCADE` refuses to
    delete tables. Dropping user data on a downgrade is never something a migration should decide.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("identity", "travel")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # The role running the migration owns the schemas it just created; the grant is explicit so
    # that the intent survives a change of database owner.
    connection = op.get_bind()
    role = connection.exec_driver_sql("SELECT current_user").scalar_one()
    for schema in SCHEMAS:
        op.execute(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO "{role}"')


def downgrade() -> None:
    # No CASCADE on purpose. If a table exists, this fails loudly rather than deleting a user's
    # trips because someone ran one downgrade too many.
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
