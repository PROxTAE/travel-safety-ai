"""Keep the create request with each snapshot so it can be rebuilt and verified."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_snapshot_request"
down_revision = "0005_canonical_geography_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snapshots", sa.Column("request_json", JSONB, nullable=True), schema="integration"
    )


def downgrade() -> None:
    op.drop_column("snapshots", "request_json", schema="integration")
