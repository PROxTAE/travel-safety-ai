"""Widen the applied-route columns from UUID to RecordId.

Revision ID: 0006
Revises: 0005
Create date: 2026-09-20

Why:
    `travel.trips.selected_route_id` holds a `RouteCandidate.route_id`, and that identifier stopped
    being a UUID. Module 04 mints it reproducibly from the provider key and a fingerprint of the
    question — `openrouteservice:3ca4459b8d41b503` — so that asking for the same route twice yields
    the same id, and a route served from cache is recognisably the same route as one fetched fresh.
    A random UUID per fetch would make those two look like different routes.

    The canonical schema was corrected to `RecordId` for `route_id` and `segment_id`; these two
    columns store that value, so they have to follow. Leaving them as UUID would mean apply-route,
    which lands in phase 6, could not write the id of the route the traveller actually picked.

Data impact:
    `ALTER TYPE` on two nullable columns of `travel.trips`, cast through text. Both are NULL
    everywhere today — apply-route does not exist yet, and nothing else writes them — so no value
    is rewritten and the cast cannot fail on existing data.

    PostgreSQL takes an ACCESS EXCLUSIVE lock for the table rewrite. `trips` is small and the lock
    is brief, but this is not a zero-downtime migration; run it in a maintenance window if the
    table has grown by the time it is applied somewhere real.

Downgrade:
    Casts back to UUID. That succeeds only while every value is NULL or a canonical UUID string.
    Once a provider-minted id has been written, the downgrade will fail loudly rather than silently
    discarding which route a traveller applied — which is the correct outcome: the value cannot be
    represented in the old type, and dropping it would lose a safety-relevant choice.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("selected_route_id", "previous_selected_route_id")


def upgrade() -> None:
    for column in COLUMNS:
        op.alter_column(
            "trips",
            column,
            existing_type=sa.UUID(),
            type_=sa.String(length=256),
            existing_nullable=True,
            postgresql_using=f"{column}::text",
            schema="travel",
        )

    op.alter_column(
        "trips",
        "selected_route_id",
        existing_type=sa.String(length=256),
        existing_nullable=True,
        comment=(
            "RouteCandidate.route_id of the applied route. A string, not a UUID: a routing "
            "provider mints these reproducibly (openrouteservice:3ca4459b8d41b503) so the same "
            "question yields the same route. Set only by apply-route, after the server has "
            "checked the route is not closed."
        ),
        existing_comment=(
            "Set only by apply-route, after the server has checked the route is not closed."
        ),
        schema="travel",
    )


def downgrade() -> None:
    op.alter_column(
        "trips",
        "selected_route_id",
        existing_type=sa.String(length=256),
        existing_nullable=True,
        comment="Set only by apply-route, after the server has checked the route is not closed.",
        schema="travel",
    )

    for column in COLUMNS:
        op.alter_column(
            "trips",
            column,
            existing_type=sa.String(length=256),
            type_=sa.UUID(),
            existing_nullable=True,
            postgresql_using=f"{column}::uuid",
            schema="travel",
        )
