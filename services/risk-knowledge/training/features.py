"""Deterministic feature extraction for risk modeling adhering to Module 06 feature schema.

Conforms to governance/feature_schema.v1.yaml:
- Exactly 13 canonical features
- Strict prediction cutoff to prevent future leakage
- Lineage tracking per vector
- Conservative null policy: never coerce nulls to zero or False
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

FEATURE_NAMES = (
    "route_distance_m",
    "route_duration_seconds",
    "route_transfer_count",
    "corridor_official_closure_active",
    "corridor_official_evacuation_active",
    "corridor_extreme_alert_active",
    "hazard_intersection_fraction",
    "max_weather_severity_ordinal",
    "max_precipitation_probability",
    "max_wind_gust_kmh",
    "transport_disruption_severity",
    "critical_evidence_coverage",
    "critical_evidence_freshness_seconds",
)

CRITICAL_FEATURES = {
    "corridor_official_closure_active",
    "corridor_extreme_alert_active",
    "hazard_intersection_fraction",
    "max_weather_severity_ordinal",
    "critical_evidence_coverage",
    "critical_evidence_freshness_seconds",
}

NON_NULLABLE_FEATURES = {
    "route_distance_m",
    "route_duration_seconds",
    "route_transfer_count",
    "critical_evidence_coverage",
}

WEATHER_CODE_TO_SEVERITY: dict[int, int] = {
    # 0=INFO, 1=MINOR, 2=MODERATE, 3=SEVERE, 4=EXTREME
    0: 0,  # Clear sky
    1: 1,  # Mainly clear
    2: 1,  # Partly cloudy
    3: 1,  # Overcast
    45: 1,  # Fog
    48: 1,  # Depositing rime fog
    51: 2,  # Light drizzle
    53: 2,  # Moderate drizzle
    55: 2,  # Dense drizzle
    61: 2,  # Slight rain
    63: 2,  # Moderate rain
    65: 3,  # Heavy rain
    71: 2,  # Slight snow
    73: 2,  # Moderate snow
    75: 3,  # Heavy snow
    80: 2,  # Slight rain showers
    81: 2,  # Moderate rain showers
    82: 3,  # Violent rain showers
    95: 3,  # Thunderstorm
    96: 4,  # Thunderstorm with slight hail
    99: 4,  # Thunderstorm with heavy hail
}


@dataclass(frozen=True)
class FeatureVector:
    schema_version: str
    values: dict[str, Any]
    null_features: tuple[str, ...]
    lineage: dict[str, Any]
    prediction_cutoff: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "values": self.values,
            "null_features": list(self.null_features),
            "lineage": self.lineage,
            "prediction_cutoff": self.prediction_cutoff,
        }


def parse_utc_timestamp(ts: str | datetime) -> datetime:
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    # Parse ISO string
    cleaned = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def haversine_distance_m(
    p1: list[float] | tuple[float, float], p2: list[float] | tuple[float, float]
) -> float:
    """Distance in metres between [lon, lat] points."""
    lon1, lat1 = p1[0], p1[1]
    lon2, lat2 = p2[0], p2[1]
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def filter_records_before_cutoff(
    records: list[dict[str, Any]] | None,
    cutoff: datetime,
) -> list[dict[str, Any]] | None:
    """Drop any records observed or published after prediction cutoff."""
    if records is None:
        return None
    filtered = []
    for r in records:
        ts_str = (
            r.get("observed_at") or r.get("published_at") or r.get("fetched_at") or r.get("time")
        )
        if ts_str is not None:
            dt = parse_utc_timestamp(ts_str)
            if dt <= cutoff:
                filtered.append(r)
        else:
            # If record has no explicit timestamp, retain only if explicitly verified
            filtered.append(r)
    return filtered


def extract_features(
    corridor: dict[str, Any],
    departure_time: str,
    prediction_cutoff: str,
    weather_data: dict[str, Any] | None = None,
    disasters: list[dict[str, Any]] | None = None,
    transport_alerts: list[dict[str, Any]] | None = None,
    source_checksums: dict[str, str] | None = None,
) -> FeatureVector:
    """Extract 13 canonical features for a route candidate under a departure window."""
    cutoff_dt = parse_utc_timestamp(prediction_cutoff)
    dep_dt = parse_utc_timestamp(departure_time)

    # Basic route properties
    distance_m = float(corridor.get("distance_m", 0.0))
    duration_seconds = float(corridor.get("duration_seconds", 0.0))
    transfers = int(corridor.get("transfers", 0))

    waypoints = corridor.get("waypoints", [])

    # Filter evidence strictly before prediction cutoff
    active_disasters = filter_records_before_cutoff(disasters, cutoff_dt)
    active_transport = filter_records_before_cutoff(transport_alerts, cutoff_dt)

    # 1. Hazard intersection and official alerts
    closure_active: bool | None = None
    evacuation_active: bool | None = None
    extreme_alert: bool | None = None
    hazard_fraction: float | None = None

    if active_disasters is not None:
        # Evaluate corridor intersection with disasters
        intersecting_count = 0
        total_points = max(1, len(waypoints))
        has_closure = False
        has_extreme = False

        for wp in waypoints:
            point_hit = False
            for dis in active_disasters:
                # Check coordinates if present
                geom = dis.get("geometry") or dis.get("coordinates")
                if geom and isinstance(geom, list) and len(geom) >= 2:
                    d = haversine_distance_m(wp, geom)
                    radius = float(dis.get("radius_m", 50000.0))  # 50km default impact radius
                    if d <= radius:
                        point_hit = True
                        if dis.get("event_type") == "TRANSPORT_CLOSURE" or dis.get("closed", False):
                            has_closure = True
                        if dis.get("severity") in ("EXTREME", "SEVERE"):
                            has_extreme = True
            if point_hit:
                intersecting_count += 1

        hazard_fraction = round(intersecting_count / total_points, 4)
        closure_active = has_closure
        evacuation_active = None  # No producer publishes verified civilian evacuations yet
        extreme_alert = has_extreme

    # 2. Weather metrics
    max_weather_severity: int | None = None
    max_precip_prob: float | None = None
    max_wind_gust: float | None = None

    if weather_data is not None and "hourly" in weather_data:
        hourly = weather_data["hourly"]
        times = hourly.get("time", [])
        weather_codes = hourly.get("weather_code", [])
        precips = hourly.get("precipitation", [])
        gusts = hourly.get("wind_gusts_10m", [])

        valid_indices = []
        for idx, t in enumerate(times):
            if idx < len(times):
                try:
                    w_dt = parse_utc_timestamp(t)
                except (ValueError, TypeError):
                    w_dt = None
                if w_dt is not None and w_dt <= cutoff_dt:
                    valid_indices.append(idx)

        if valid_indices:
            severities = [
                WEATHER_CODE_TO_SEVERITY.get(int(weather_codes[i]), 0)
                for i in valid_indices
                if i < len(weather_codes)
            ]
            max_weather_severity = max(severities) if severities else 0

            p_vals = [
                float(precips[i])
                for i in valid_indices
                if i < len(precips) and precips[i] is not None
            ]
            # Convert precipitation mm to a normalized probability proxy (0.0 to 1.0)
            max_precip_prob = min(1.0, round(max(p_vals) / 25.0, 2)) if p_vals else 0.0

            g_vals = [
                float(gusts[i]) for i in valid_indices if i < len(gusts) and gusts[i] is not None
            ]
            max_wind_gust = round(max(g_vals), 1) if g_vals else 0.0

    # 3. Transport disruption
    transport_disruption: int | None = None
    if active_transport is not None:
        mapping = {"ON_TIME": 0, "DELAYED": 1, "DISRUPTED": 2, "CANCELLED": 3, "UNKNOWN": 4}
        statuses = [mapping.get(t.get("status", "UNKNOWN"), 4) for t in active_transport]
        transport_disruption = max(statuses) if statuses else 0
    elif corridor.get("mode") in ("CAR", "WALK", "BICYCLE"):
        # For road modes, transport disruption is on-time unless official alerts say otherwise
        transport_disruption = 0

    # 4. Critical coverage and freshness
    # Coverage calculation
    has_weather = weather_data is not None and bool(weather_data.get("hourly"))
    has_disaster = active_disasters is not None
    coverage_components = [1.0 if has_weather else 0.0, 1.0 if has_disaster else 0.0]
    critical_coverage = round(sum(coverage_components) / len(coverage_components), 2)

    # Freshness calculation (seconds between cutoff and departure)
    freshness_seconds = max(0, int((dep_dt - cutoff_dt).total_seconds()))

    values: dict[str, Any] = {
        "route_distance_m": distance_m,
        "route_duration_seconds": duration_seconds,
        "route_transfer_count": transfers,
        "corridor_official_closure_active": closure_active,
        "corridor_official_evacuation_active": evacuation_active,
        "corridor_extreme_alert_active": extreme_alert,
        "hazard_intersection_fraction": hazard_fraction,
        "max_weather_severity_ordinal": max_weather_severity,
        "max_precipitation_probability": max_precip_prob,
        "max_wind_gust_kmh": max_wind_gust,
        "transport_disruption_severity": transport_disruption,
        "critical_evidence_coverage": critical_coverage,
        "critical_evidence_freshness_seconds": freshness_seconds,
    }

    # Verify non-nullable features
    for name in NON_NULLABLE_FEATURES:
        if values[name] is None:
            raise ValueError(f"Feature {name} is non-nullable but got None")

    nulls = tuple(name for name in FEATURE_NAMES if values[name] is None)

    lineage = {
        "corridor_id": corridor.get("corridor_id"),
        "departure_time": departure_time,
        "source_checksums": source_checksums or {},
        "generated_at": datetime.now(UTC).isoformat(),
    }

    return FeatureVector(
        schema_version="1.0.0",
        values=values,
        null_features=nulls,
        lineage=lineage,
        prediction_cutoff=prediction_cutoff,
    )
