"""Deterministic feature values for the module 06 feature schema.

Input lists use ``None`` for an unavailable source and ``[]`` for a source that
answered with nothing. Unknown values stay null; they are never converted to
zero or to ``False``.
"""

from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any, TypeVar

import yaml

from app.domain.canonical import (
    DataQuality,
    DisasterEvent,
    GeoPoint,
    RouteCandidate,
    SourceProvenance,
    TransportStatus,
    WeatherForecastPoint,
)
from app.pipeline.alignment import align_transport, align_weather
from app.pipeline.area import point_in_area
from app.pipeline.corridor import RouteSample, geodesic_distance_m

SCHEMA_PATH = Path(__file__).with_name("feature_schema.yaml")
TRANSIT_MODES = {"FLIGHT", "TRAIN", "BUS", "MULTIMODAL"}
UNUSABLE = {"STALE", "UNAVAILABLE"}
OFFICIAL_ALERT_FEATURES = (
    "corridor_official_closure_active",
    "corridor_official_evacuation_active",
    "corridor_extreme_alert_active",
)

FeatureValue = float | int | bool | None
Record = TypeVar("Record", WeatherForecastPoint, DisasterEvent, TransportStatus)


@dataclass(frozen=True)
class FeaturePolicy:
    weather_radius_m: float
    weather_time_tolerance_seconds: float
    transport_time_tolerance_seconds: float


@dataclass(frozen=True)
class FeatureInputs:
    route: RouteCandidate
    samples: list[RouteSample]
    recommendation_at: datetime
    weather: list[WeatherForecastPoint] | None
    disasters_in_corridor: list[DisasterEvent] | None
    transport: list[TransportStatus] | None
    sources: dict[str, DataQuality]


@dataclass(frozen=True)
class FeatureVector:
    schema_version: str
    values: dict[str, FeatureValue]
    null_features: tuple[str, ...]


@cache
def feature_schema() -> dict[str, Any]:
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


def _mapping(name: str) -> dict[str, int]:
    return next(f for f in feature_schema()["features"] if f["name"] == name)["enum_mapping"]


def _known_at(source: SourceProvenance, cutoff: datetime) -> bool:
    times = (source.fetched_at, source.published_at, source.observed_at)
    return all(time is None or time <= cutoff for time in times)


def before_cutoff(records: list[Record] | None, cutoff: datetime) -> list[Record] | None:
    """Drop evidence learned after the recommendation; nothing left means unavailable."""
    if records is None:
        return None
    known = [record for record in records if _known_at(record.source, cutoff)]
    return known if known or not records else None


def _covers(sample: RouteSample, record: WeatherForecastPoint, policy: FeaturePolicy) -> bool:
    return (
        record.quality.status not in UNUSABLE
        and geodesic_distance_m((sample.longitude, sample.latitude), record.location.coordinates)
        <= policy.weather_radius_m
        and abs((record.valid_at - sample.eta).total_seconds())
        <= policy.weather_time_tolerance_seconds
    )


def _weather(inputs: FeatureInputs, policy: FeaturePolicy) -> dict[str, FeatureValue]:
    records = before_cutoff(inputs.weather, inputs.recommendation_at)
    matched = [
        record
        for record in records or []
        if align_weather(
            inputs.samples,
            record,
            radius_m=policy.weather_radius_m,
            time_tolerance_seconds=policy.weather_time_tolerance_seconds,
        ).status
        == "MATCHED"
    ]
    severity = _mapping("max_weather_severity_ordinal")
    chances = [
        r.precipitation_probability for r in matched if r.precipitation_probability is not None
    ]
    gusts = [r.wind_gust_kmh for r in matched if r.wind_gust_kmh is not None]
    return {
        "max_weather_severity_ordinal": max((severity[r.severity] for r in matched), default=None),
        "max_precipitation_probability": max(chances) / 100 if chances else None,
        "max_wind_gust_kmh": max(gusts, default=None),
    }


def _in_area(point: tuple[float, float], event: DisasterEvent) -> bool:
    geometry = event.geometry
    return not isinstance(geometry, GeoPoint) and point_in_area(point, geometry)


def _active_at(event: DisasterEvent, at: datetime) -> bool:
    return event.effective_at <= at and (event.ends_at is None or at <= event.ends_at)


def _disasters(inputs: FeatureInputs) -> dict[str, FeatureValue]:
    events = before_cutoff(inputs.disasters_in_corridor, inputs.recommendation_at)
    if events is None:
        return dict.fromkeys([*OFFICIAL_ALERT_FEATURES, "hazard_intersection_fraction"])
    start, end = inputs.samples[0].eta, inputs.samples[-1].eta
    official = [
        e
        for e in events
        if e.official and e.effective_at <= end and (e.ends_at is None or e.ends_at >= start)
    ]
    severities = {e.severity for e in official}
    extreme = True if "EXTREME" in severities else None if "UNKNOWN" in severities else False
    inside = total = 0.0
    for a, b in zip(inputs.samples, inputs.samples[1:], strict=False):
        length = b.distance_m - a.distance_m
        total += length
        if any(_active_at(e, a.eta) and _in_area((a.longitude, a.latitude), e) for e in events):
            inside += length
    return {
        "corridor_official_closure_active": any(
            e.event_type == "TRANSPORT_CLOSURE" for e in official
        ),
        # No producer publishes evacuation orders, so their absence cannot be proven.
        "corridor_official_evacuation_active": None,
        "corridor_extreme_alert_active": extreme,
        "hazard_intersection_fraction": inside / total if total else None,
    }


def _transport(inputs: FeatureInputs, policy: FeaturePolicy) -> tuple[int | None, float | None]:
    """Return the disruption ordinal and the share of transit segments with usable status."""
    relevant = [s for s in inputs.route.segments if s.transport_status_id]
    records = before_cutoff(inputs.transport, inputs.recommendation_at)
    if not relevant or records is None:
        return None, None
    mapping = _mapping("transport_disruption_severity")
    by_id = {record.id: record for record in records}
    ordinals: list[int] = []
    for segment in relevant:
        record = by_id.get(segment.transport_status_id or "")
        status = (
            align_transport(
                segment, record, time_tolerance_seconds=policy.transport_time_tolerance_seconds
            ).status
            if record
            else "UNAVAILABLE"
        )
        ordinals.append(mapping[record.status if record and status == "MATCHED" else "UNKNOWN"])
    usable = sum(ordinal != mapping["UNKNOWN"] for ordinal in ordinals)
    return max(ordinals), usable / len(relevant)


def _critical_sources(inputs: FeatureInputs) -> tuple[str, ...]:
    if inputs.route.mode in TRANSIT_MODES:
        return ("weather", "disaster", "transport")
    return ("weather", "disaster")


def _coverage(
    inputs: FeatureInputs, policy: FeaturePolicy, transport_coverage: float | None
) -> float:
    """Minimum over required evidence; an unavailable source covers nothing."""
    weather = before_cutoff(inputs.weather, inputs.recommendation_at) or []
    covered = sum(any(_covers(s, r, policy) for r in weather) for s in inputs.samples)
    parts = [
        covered / len(inputs.samples),
        0.0 if inputs.disasters_in_corridor is None else 1.0,
    ]
    if inputs.route.mode in TRANSIT_MODES:
        parts.append(transport_coverage or 0.0)
    return min(parts)


def _freshness(inputs: FeatureInputs) -> int | None:
    """Oldest critical source age; one unknown age leaves the whole value unknown."""
    ages: list[int] = []
    for name in _critical_sources(inputs):
        quality = inputs.sources.get(name)
        if quality is None or quality.freshness_seconds is None:
            return None
        ages.append(quality.freshness_seconds)
    return max(ages)


def build_features(inputs: FeatureInputs, policy: FeaturePolicy) -> FeatureVector:
    """Return every schema feature in schema order and list the null ones."""
    if len(inputs.samples) < 2:
        raise ValueError("route needs at least two samples")
    if inputs.recommendation_at.utcoffset() is None:
        raise ValueError("recommendation time must be timezone-aware")
    disruption, transport_coverage = _transport(inputs, policy)
    computed: dict[str, FeatureValue] = {
        "route_distance_m": inputs.route.distance_m,
        "route_duration_seconds": inputs.route.duration_seconds,
        "route_transfer_count": inputs.route.transfers,
        **_disasters(inputs),
        **_weather(inputs, policy),
        "transport_disruption_severity": disruption,
        "critical_evidence_coverage": _coverage(inputs, policy, transport_coverage),
        "critical_evidence_freshness_seconds": _freshness(inputs),
    }
    schema = feature_schema()
    values: dict[str, FeatureValue] = {}
    for feature in schema["features"]:
        name = feature["name"]
        value = computed.pop(name)
        if value is None and not feature["nullable"]:
            raise ValueError(f"{name} is not nullable")
        values[name] = value
    if computed:
        raise ValueError(f"features missing from schema: {sorted(computed)}")
    nulls = tuple(name for name, value in values.items() if value is None)
    return FeatureVector(schema["schema_version"], values, nulls)
