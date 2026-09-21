"""Deterministic candidate matching without discarding source evidence."""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any

from app.repositories.snapshot_repo import canonical_hash

MATCH_VERSION = "1.0.0"


@dataclass(frozen=True)
class Match:
    left: int
    right: int
    reason: str
    confidence: float
    mergeable: bool


@dataclass(frozen=True)
class Cluster:
    members: tuple[int, ...]
    source_ids: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ValueEvidence:
    source_id: str
    value: Any
    authority: str
    fetched_at: str


@dataclass(frozen=True)
class Resolution:
    field_path: str
    selected_value: Any
    selected_source_id: str | None
    status: str
    reason: str
    evidence: tuple[ValueEvidence, ...]


AUTHORITY_ORDER = {
    "OFFICIAL": 4,
    "INTERGOVERNMENTAL": 3,
    "LICENSED_PROVIDER": 2,
    "COMMUNITY": 1,
    "UNKNOWN": 0,
}
SAFETY_CRITICAL_FIELDS = frozenset({"severity", "closed", "status"})


def _instant(record: dict) -> datetime | None:
    value = record.get("effective_at") or record.get("valid_at")
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("candidate timestamp must include timezone")
    return parsed


def _point(record: dict) -> tuple[float, float] | None:
    geometry = record.get("canonical_geometry") or record.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    lon, lat = geometry["coordinates"]
    return float(lon), float(lat)


def _distance_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    lon1, lat1 = left
    lon2, lat2 = right
    dlat = radians(lat2 - lat1)
    dlon = radians((lon2 - lon1 + 180) % 360 - 180)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6_371_008.8 * asin(min(1.0, sqrt(value)))


def _event_ids(record: dict) -> set[str]:
    return {
        value for value in [record.get("event_id"), *record.get("cross_reference_ids", [])] if value
    }


def candidate_links(
    records: list[dict], *, max_distance_m: float, max_time_seconds: float
) -> list[Match]:
    """Return evidence links; similarity alone is never an automatic dedup."""
    if max_distance_m < 0 or max_time_seconds < 0:
        raise ValueError("candidate thresholds must be nonnegative")
    links: list[Match] = []
    for left_index, left in enumerate(records):
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            left_source, right_source = left["source"], right["source"]
            same_provider_record = (
                left_source["provider"] == right_source["provider"]
                and left_source.get("provider_record_id") is not None
                and left_source["provider_record_id"] == right_source.get("provider_record_id")
            )
            if same_provider_record:
                same_update = left_source.get("published_at") == right_source.get("published_at")
                links.append(
                    Match(
                        left_index,
                        right_index,
                        "PROVIDER_VERSION" if same_update else "PROVIDER_UPDATE",
                        1.0 if same_update else 0.9,
                        same_update,
                    )
                )
                continue
            if _event_ids(left) & _event_ids(right):
                links.append(Match(left_index, right_index, "CROSS_REFERENCE", 1.0, True))
                continue
            if canonical_hash(left) == canonical_hash(right):
                links.append(Match(left_index, right_index, "EXACT_CONTENT", 1.0, True))
                continue
            left_time, right_time = _instant(left), _instant(right)
            left_point, right_point = _point(left), _point(right)
            if None in (left_time, right_time, left_point, right_point):
                continue
            if abs((left_time - right_time).total_seconds()) > max_time_seconds:
                continue
            if _distance_m(left_point, right_point) > max_distance_m:
                continue
            links.append(Match(left_index, right_index, "SPATIAL_TEMPORAL", 0.5, False))
    return links


def exact_clusters(records: list[dict], links: list[Match]) -> list[Cluster]:
    """Group only proven identities; keep all member indices and source IDs."""
    parent = list(range(len(records)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for link in links:
        if link.mergeable:
            parent[root(link.right)] = root(link.left)
    groups: dict[int, list[int]] = {}
    for index in range(len(records)):
        groups.setdefault(root(index), []).append(index)
    return [
        Cluster(
            members=tuple(members),
            source_ids=tuple(records[index]["source"]["source_id"] for index in members),
            reasons=tuple(
                sorted(
                    {
                        link.reason
                        for link in links
                        if link.mergeable and link.left in members and link.right in members
                    }
                )
            ),
        )
        for members in groups.values()
    ]


def candidate_groups(record_count: int, links: list[Match]) -> list[tuple[int, ...]]:
    """Group similarity candidates for review without declaring them duplicates."""
    parent = list(range(record_count))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for link in links:
        if link.reason == "SPATIAL_TEMPORAL":
            parent[root(link.right)] = root(link.left)
    groups: dict[int, list[int]] = {}
    for index in range(record_count):
        groups.setdefault(root(index), []).append(index)
    return [tuple(members) for members in groups.values() if len(members) > 1]


def _field(record: dict, path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _rank(record: dict, provider_health: dict[str, bool]) -> tuple:
    source = record["source"]
    quality = record.get("quality") or {}
    fetched = datetime.fromisoformat(source["fetched_at"].replace("Z", "+00:00"))
    if fetched.utcoffset() is None:
        raise ValueError("fetched_at must include timezone")
    source_id = source["source_id"]
    return (
        int(record.get("official") is True),
        AUTHORITY_ORDER.get(source.get("authority", "UNKNOWN"), 0),
        int(provider_health.get(source_id, False)),
        int(quality.get("status") == "FRESH"),
        quality.get("coverage") if quality.get("coverage") is not None else -1,
        quality.get("completeness") if quality.get("completeness") is not None else -1,
        fetched.astimezone(UTC).timestamp(),
    )


def resolve_field(
    records: list[dict], field_path: str, *, provider_health: dict[str, bool] | None = None
) -> Resolution:
    """Select deterministically while exposing every source and unresolved conflict."""
    if not records:
        return Resolution(field_path, None, None, "UNAVAILABLE", "NO_EVIDENCE", ())
    health = provider_health or {}
    evidence = tuple(
        ValueEvidence(
            record["source"]["source_id"],
            _field(record, field_path),
            record["source"].get("authority", "UNKNOWN"),
            record["source"]["fetched_at"],
        )
        for record in records
    )
    populated = [record for record in records if _field(record, field_path) is not None]
    if not populated:
        return Resolution(field_path, None, None, "UNAVAILABLE", "MISSING_VALUE", evidence)
    selected = sorted(
        populated,
        key=lambda record: (
            tuple(-value for value in _rank(record, health)),
            record["source"]["source_id"],
        ),
    )[0]
    values = {canonical_hash({"value": _field(record, field_path)}) for record in populated}
    disputed = len(values) > 1
    critical = field_path.rsplit(".", 1)[-1] in SAFETY_CRITICAL_FIELDS
    status = (
        "CONFLICTING"
        if disputed and critical
        else ("PARTIAL" if disputed else selected.get("quality", {}).get("status", "PARTIAL"))
    )
    reason = (
        "UNRESOLVED_SAFETY_CONFLICT"
        if disputed and critical
        else ("AUTHORITY_RANK" if disputed else "SOURCE_AGREEMENT")
    )
    return Resolution(
        field_path,
        _field(selected, field_path),
        selected["source"]["source_id"],
        status,
        reason,
        evidence,
    )
