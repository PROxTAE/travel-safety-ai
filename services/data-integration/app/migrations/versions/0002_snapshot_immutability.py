"""Protect persisted snapshots from update and deletion."""

from alembic import op

revision = "0002_snapshot_immutability"
down_revision = "0001_integration_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION integration.reject_snapshot_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'integration snapshots are immutable';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER snapshots_immutable BEFORE UPDATE OR DELETE
        ON integration.snapshots FOR EACH ROW
        EXECUTE FUNCTION integration.reject_snapshot_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER snapshots_immutable ON integration.snapshots")
    op.execute("DROP FUNCTION integration.reject_snapshot_mutation()")
