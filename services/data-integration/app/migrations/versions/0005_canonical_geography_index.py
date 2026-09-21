"""Index metric geography searches on canonical geometries."""

from alembic import op

revision = "0005_canonical_geography_index"
down_revision = "0004_dedup_clusters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX ix_canonical_geography
        ON integration.canonical_records USING gist ((geometry::geography))
        WHERE geometry IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX integration.ix_canonical_geography")
