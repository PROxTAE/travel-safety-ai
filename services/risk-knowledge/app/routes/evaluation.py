"""Full-corridor exposure, hard constraints, and deterministic ranking for Phase 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shapely.geometry import shape

from app.contracts import IntegratedTravelContext, RiskLevel, RouteCandidate, RouteExposure


@dataclass(frozen=True)
class EvaluatedRoute:
    route: RouteCandidate
    usable: bool
    tradeoffs: tuple[str, ...]


def evaluate_exposure(
    route: RouteCandidate,
    hazards: list[dict[str, Any]],
    severity_weights: dict[str, float] | None,
    *,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> RouteCandidate:
    line = shape(route.geometry)
    hard: list[str] = []
    event_ids: list[str] = []
    weighted = 0.0
    for hazard in hazards:
        if starts_at and ends_at and not _overlaps_window(hazard, starts_at, ends_at):
            continue
        geometry = hazard.get("geometry")
        if not geometry or not line.intersects(shape(geometry)):
            continue
        event_ids.append(str(hazard.get("event_id", "UNKNOWN")))
        if hazard.get("official") and hazard.get("closure"):
            hard.append("OFFICIAL_CLOSURE")
        if hazard.get("official") and hazard.get("no_go"):
            hard.append("OFFICIAL_NO_GO")
        if severity_weights is not None:
            intersection = line.intersection(shape(geometry))
            ratio = min(1.0, intersection.length / max(line.length, 1e-12))
            weighted += severity_weights.get(str(hazard.get("severity", "UNKNOWN")), 0.0) * ratio
    score = min(1.0, weighted) if severity_weights is not None else None
    exposure = RouteExposure(
        score=score,
        hazard_event_ids=event_ids,
        weather_window_ids=[],
        closed=bool(hard),
        hard_constraint_codes=list(dict.fromkeys(hard)),
    )
    risk = (
        RiskLevel.HIGH
        if hard
        else (
            RiskLevel.UNKNOWN
            if score is None
            else (
                RiskLevel.HIGH
                if score >= 0.7
                else RiskLevel.MEDIUM
                if score >= 0.3
                else RiskLevel.LOW
            )
        )
    )
    return route.model_copy(update={"exposure": exposure, "risk_level": risk})


def _overlaps_window(hazard: dict[str, Any], starts_at: datetime, ends_at: datetime) -> bool:
    start_value = hazard.get("effective_at") or hazard.get("starts_at")
    end_value = hazard.get("ends_at") or hazard.get("expires_at")
    if start_value is None and end_value is None:
        return True
    try:
        hazard_start = datetime.fromisoformat(str(start_value).replace("Z", "+00:00"))
        hazard_end = (
            datetime.fromisoformat(str(end_value).replace("Z", "+00:00"))
            if end_value is not None
            else ends_at
        )
    except ValueError:
        return False
    return hazard_start <= ends_at and hazard_end >= starts_at


def evaluate_snapshot_routes(
    snapshot: IntegratedTravelContext,
    route_ids: list[Any],
    severity_weights: dict[str, float] | None,
) -> list[EvaluatedRoute]:
    selected = [route for route in snapshot.route_candidates if route.route_id in set(route_ids)]
    hazards = list(snapshot.disaster_events)
    for alert in snapshot.official_alerts:
        hazards.append(
            {
                "event_id": alert.event_id,
                "official": True,
                "closure": alert.closure,
                "no_go": alert.evacuation,
                "severity": alert.severity.value,
                "effective_at": alert.effective_at.isoformat(),
                "ends_at": alert.ends_at.isoformat() if alert.ends_at else None,
                "geometry": snapshot.route_corridor_geojson,
            }
        )
    evaluated = [
        evaluate_exposure(
            route,
            hazards,
            severity_weights,
            starts_at=snapshot.travel_window.starts_at,
            ends_at=snapshot.travel_window.ends_at,
        )
        for route in selected
    ]
    return rank_routes(evaluated)


def rank_routes(routes: list[RouteCandidate]) -> list[EvaluatedRoute]:
    usable = [
        route
        for route in routes
        if route.exposure is not None
        and not route.exposure.closed
        and not route.exposure.hard_constraint_codes
    ]
    if any(route.exposure is None or route.exposure.score is None for route in usable):
        return [
            EvaluatedRoute(
                route.model_copy(
                    update={"label": "ALTERNATIVE" if route.label != "ORIGINAL" else "ORIGINAL"}
                ),
                route in usable,
                ("RANKING_UNAVAILABLE_PENDING_APPROVED_COEFFICIENTS",),
            )
            for route in routes
        ]

    def exposure_score(route: RouteCandidate) -> float:
        if route.exposure is None or route.exposure.score is None:
            raise ValueError("Exposure must be available before ranking")
        return route.exposure.score

    ordered = sorted(
        usable,
        key=lambda route: (
            exposure_score(route),
            route.duration_seconds,
            route.distance_m,
            str(route.route_id),
        ),
    )
    fastest = (
        min(usable, key=lambda route: (route.duration_seconds, str(route.route_id)))
        if usable
        else None
    )
    lowest = ordered[0] if ordered else None
    output: list[EvaluatedRoute] = []
    for route in routes:
        is_usable = route in usable
        label = route.label
        if not is_usable:
            label = "ALTERNATIVE"
        elif route is lowest:
            label = "RECOMMENDED"
        elif route is fastest:
            label = "FASTEST"
        else:
            label = "ALTERNATIVE"
        output.append(
            EvaluatedRoute(
                route.model_copy(update={"label": label}),
                is_usable,
                ("Safety ordered before duration and distance.",),
            )
        )
    return output
