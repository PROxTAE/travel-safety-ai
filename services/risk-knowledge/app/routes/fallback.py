from __future__ import annotations

from typing import cast
from uuid import UUID

from app.contracts import RouteCandidate

FALLBACK_ROUTE_POLICY_VERSION = "1.0.0-hard-constraints-only"


def enforce_hard_constraints_without_ranking(
    routes: list[RouteCandidate], route_ids: list[UUID]
) -> tuple[list[RouteCandidate], list[UUID]]:
    """Remove explicitly unusable routes without claiming that remaining routes are safer."""

    requested = set(route_ids)
    usable: list[RouteCandidate] = []
    unusable: list[UUID] = []
    for route in routes:
        if route.route_id not in requested:
            continue
        if route.exposure is not None and (
            route.exposure.closed or route.exposure.hard_constraint_codes
        ):
            unusable.append(cast(UUID, route.route_id))
            continue
        label = route.label
        if label in {"RECOMMENDED", "FASTEST", "LOWEST_RISK"}:
            label = "ALTERNATIVE"
        usable.append(route.model_copy(update={"label": label}))
    return usable, unusable
