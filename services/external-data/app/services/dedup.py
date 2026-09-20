"""Preliminary cross-source duplicate detection.

The same earthquake is published by USGS, GDACS and EONET, each with its own id,
its own timestamp and a slightly different epicentre. Module 05 resolves them.
Module 04's job is to make that resolution possible — which means **grouping**
candidates and **never removing** one, per the module plan.

Two events are grouped when either holds:

- **Shared identifier.** One event's own record id or cross-reference appears in
  the other's. This is strong evidence: a GLIDE number or a network id is meant
  to identify the same real-world event across agencies.
- **Same hazard, same place, same time.** Same `event_type`, epicentres within
  `PROXIMITY_KM`, and start times within `PROXIMITY_MINUTES`. This is weaker —
  two genuinely distinct quakes can occur in a swarm — so the group records
  which rule matched, and the caller decides how much to trust it.

Nothing is merged, scored or dropped here. The output is an annotation over the
events, and every event is emitted whether or not it belongs to a group.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

from app.domain.records import DisasterEvent

# Generous enough to catch the same quake located differently by two networks,
# tight enough not to merge separate events in a swarm. Deliberately not tuned
# against a metric - the group is a hint, not a decision.
PROXIMITY_KM = 100.0
PROXIMITY_MINUTES = 30.0


@dataclass(slots=True)
class DuplicateGroup:
    """Events that may describe the same real-world hazard."""

    event_ids: list[str]
    # "shared_identifier" is strong; "proximity" is a hint.
    basis: str
    providers: list[str] = field(default_factory=list)
    # Authority of each member, so module 05 can prioritise without module 04
    # having decided anything.
    authorities: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "event_ids": self.event_ids,
            "basis": self.basis,
            "providers": self.providers,
            "authorities": self.authorities,
        }


def find_duplicate_groups(events: list[DisasterEvent]) -> list[DuplicateGroup]:
    """Group likely duplicates. The input list is never modified or filtered."""
    if len(events) < 2:
        return []

    parent = list(range(len(events)))
    basis: dict[int, str] = {}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int, rule: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left == root_right:
            # Already grouped: a shared identifier outranks mere proximity.
            if rule == "shared_identifier":
                basis[root_left] = rule
            return
        parent[root_right] = root_left
        existing = basis.get(root_left, ""), basis.get(root_right, "")
        basis[root_left] = (
            "shared_identifier"
            if rule == "shared_identifier" or "shared_identifier" in existing
            else "proximity"
        )

    identifiers = [_identifiers(event) for event in events]

    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            if events[i].source.provider == events[j].source.provider:
                # Two records from one source are that source's own business.
                continue
            if identifiers[i] & identifiers[j]:
                union(i, j, "shared_identifier")
            elif _near_in_space_and_time(events[i], events[j]):
                union(i, j, "proximity")

    grouped: dict[int, list[int]] = {}
    for index in range(len(events)):
        grouped.setdefault(find(index), []).append(index)

    groups: list[DuplicateGroup] = []
    for root, members in grouped.items():
        if len(members) < 2:
            continue
        groups.append(
            DuplicateGroup(
                event_ids=[events[i].event_id for i in members],
                basis=basis.get(root, "proximity"),
                providers=sorted({events[i].source.provider for i in members}),
                authorities=sorted({str(events[i].source.authority) for i in members}),
            )
        )

    groups.sort(key=lambda group: group.event_ids)
    return groups


# A value naming a *category* rather than an event - the agency that reported
# it, the episode index within it. One of these shared between two records says
# nothing about whether they describe the same hazard, and matching on them
# chained seventeen unrelated storms into a single "duplicate" group.
_NOT_AN_EVENT_ID = ("network:", "episode:", "source:", "category:")


def _identifiers(event: DisasterEvent) -> set[str]:
    """Everything that could name this event somewhere else.

    The provider-scoped `event_id` is excluded on purpose: it is unique to one
    source by construction and can never match another's.

    The namespace guard is belt and braces. Adapters now keep reporting
    networks and episode numbers in their own fields, but this is the place
    where a regression there turns into merged hazards, so it refuses them
    here too.
    """
    values = {
        value.strip()
        for value in event.cross_reference_ids
        if value.strip() and not value.strip().startswith(_NOT_AN_EVENT_ID)
    }
    if event.source.provider_record_id:
        values.add(event.source.provider_record_id.strip())
    return {value for value in values if value}


def _near_in_space_and_time(left: DisasterEvent, right: DisasterEvent) -> bool:
    if left.event_type is not right.event_type:
        return False
    minutes = abs((left.effective_at - right.effective_at).total_seconds()) / 60.0
    if minutes > PROXIMITY_MINUTES:
        return False
    return (
        _haversine_km(
            left.geometry.latitude,
            left.geometry.longitude,
            right.geometry.latitude,
            right.geometry.longitude,
        )
        <= PROXIMITY_KM
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * radius_km * asin(sqrt(a))
