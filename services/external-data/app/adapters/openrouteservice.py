"""openrouteservice Directions v2 adapter.

Mapping verified against `tests/fixtures/real-sanitized/openrouteservice/`,
captured from the live API on 2026-09-20. Four things this adapter absorbs:

1. **Two provider limits that are not visible in a successful response.** ORS
   refuses `alternative_routes` when there are more than two waypoints, and
   caps `target_count` at 3. Both were confirmed by calling the API, not
   recalled - the rejections are saved as fixtures. They are checked here so a
   caller gets a coverage answer instead of a provider 400 laundered into a 502.
2. **A 404 that is not a missing resource.** Error 2010 - "could not find
   routable point within a radius" - means the coordinate is off the road
   network. That is a coverage fact about the request, not an outage, so it
   must not open the circuit breaker or read as a provider failure.
3. **Freshness is about the road graph, not the call.** A route is computed,
   never observed, so `observed_at` stays null. What can go stale is the OSM
   graph the engine routed on, and ORS reports its build date in
   `metadata.engine.graph_date`. That is what freshness is measured from.
4. **`exposure` and `risk_level` are left empty on purpose.** See the
   `RouteCandidate` docstring: filling them here would let a route across a
   closed road arrive downstream asserting that nothing is wrong.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality, content_hash
from app.domain.enums import DataStatus, QualityFlag, RiskLevel, RouteLabel, TravelMode
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import (
    ALTERNATIVES_MAX_WAYPOINTS,
    MAX_ALTERNATIVE_ROUTES,
    RouteQuery,
)
from app.domain.records import GeoLineString, RouteCandidate, RouteSegment, RouteStep
from app.transport.http import ProviderResponse

# A road graph is rebuilt every week or two; treating one that is a few days old
# as stale would mark every route stale forever. Thirty days is the point at
# which "the roads may have changed since" is worth telling a consumer.
GRAPH_FRESH_WITHIN_SECONDS = 30 * 24 * 3600

# TravelMode -> ORS profile. The modes ORS cannot answer are absent on purpose:
# a flight or a train is not a road-network question, and quietly routing a
# TRAIN request by car would return a plausible, wrong itinerary.
PROFILE_BY_MODE: dict[TravelMode, str] = {
    TravelMode.CAR: "driving-car",
    TravelMode.WALK: "foot-walking",
    TravelMode.BICYCLE: "cycling-regular",
}

PREFERENCES = frozenset({"recommended", "fastest", "shortest"})

# ORS error codes worth naming. Anything else falls through to the generic
# mapping in `_provider_error`.
_NO_ROUTABLE_POINT = 2010
_INVALID_PARAMETER_VALUE = 2003
_ROUTE_NOT_FOUND = 2009


ORS_SUPPORTED_LANGUAGES = frozenset(
    {"en", "de", "cn", "es", "ru", "dk", "fr", "it", "ja", "nl", "pt", "tr", "gr", "zh-cn"}
)


def _haversine_distance_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    lon1, lat1 = p1
    lon2, lat2 = p2
    r = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class OrsSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    distance: float = 0.0
    duration: float = 0.0


class OrsStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    distance: float = 0.0
    duration: float = 0.0
    instruction: str | None = None
    name: str | None = None
    way_points: list[int] | None = None


class OrsSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    distance: float = 0.0
    duration: float = 0.0
    steps: list[OrsStep] = Field(default_factory=list)


class OrsProperties(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: OrsSummary = Field(default_factory=OrsSummary)
    segments: list[OrsSegment] = Field(default_factory=list)
    way_points: list[int] | None = None


class OrsGeometry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["LineString"]
    coordinates: list[list[float]]


class OrsFeature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["Feature"]
    geometry: OrsGeometry
    properties: OrsProperties
    bbox: list[float] | None = None


class OrsEngine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str | None = None
    graph_date: datetime | None = None
    osm_date: datetime | None = None


class OrsMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attribution: str | None = None
    timestamp: int | None = None
    engine: OrsEngine = Field(default_factory=OrsEngine)


class OrsDirections(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["FeatureCollection"]
    features: list[OrsFeature]
    bbox: list[float] | None = None
    metadata: OrsMetadata = Field(default_factory=OrsMetadata)


class OpenRouteServiceAdapter(ProviderAdapter[RouteQuery, RouteCandidate]):
    """Road routing. One request, one to four candidate routes."""

    # ------------------------------------------------------------- coverage
    def coverage(self, query: RouteQuery) -> CoverageDecision:
        if query.mode not in PROFILE_BY_MODE:
            supported = ", ".join(sorted(str(mode) for mode in PROFILE_BY_MODE))
            return CoverageDecision(
                False,
                f"{query.mode} is not a road-network mode; " f"this provider answers {supported}",
            )
        if query.preference not in PREFERENCES:
            return CoverageDecision(False, f"unknown routing preference: {query.preference}")
        if query.alternatives:
            if query.alternatives > MAX_ALTERNATIVE_ROUTES:
                return CoverageDecision(
                    False,
                    "the provider caps alternative routes at "
                    f"{MAX_ALTERNATIVE_ROUTES}, {query.alternatives} requested",
                )
            if len(query.waypoints) > ALTERNATIVES_MAX_WAYPOINTS:
                return CoverageDecision(
                    False,
                    "the provider cannot return alternative routes for a route "
                    f"with via points ({len(query.waypoints)} waypoints given)",
                )
        return CoverageDecision(True)

    # -------------------------------------------------------------- request
    def build_request(self, query: RouteQuery) -> ProviderRequest:
        profile = PROFILE_BY_MODE[query.mode]
        template = self.provider.entry.endpoints.get(
            "directions", "/v2/directions/{profile}/geojson"
        )
        ors_language = (
            query.language
            if query.language in ORS_SUPPORTED_LANGUAGES
            else ("en" if query.language else "en")
        )
        body: dict[str, Any] = {
            "coordinates": [list(point) for point in query.waypoints],
            # Metres and seconds, so nothing downstream has to guess the unit.
            "units": "m",
            "instructions": True,
            "language": ors_language,
            "preference": query.preference,
        }
        if query.alternatives:
            body["alternative_routes"] = {
                "target_count": query.alternatives,
                "share_factor": 0.6,
                "weight_factor": 1.4,
            }
        if query.avoid_polygons is not None:
            body["options"] = {"avoid_polygons": query.avoid_polygons}

        return ProviderRequest(
            path_or_url=template.replace("{profile}", profile),
            method="POST",
            json_body=body,
            headers=self._auth_headers(),
            cache_key_fields={
                "profile": profile,
                "waypoints": [[round(c, 6) for c in point] for point in query.waypoints],
                "alternatives": query.alternatives,
                "preference": query.preference,
                "language": ors_language,
                "avoid_polygons": query.avoid_polygons,
            },
        )

    def _auth_headers(self) -> dict[str, str]:
        """ORS takes the key as a bare Authorization value, not a Bearer token."""
        from app.settings import get_settings

        settings = get_settings()
        for name in self.provider.entry.credential.env_names:
            secret = settings.credential_for(name)
            if secret is not None:
                return {
                    "Authorization": secret.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept": "application/geo+json, application/json",
                }
        raise ProviderError(
            ProviderErrorCode.PROVIDER_AUTH,
            self.provider_id,
            message="routing credential is not configured",
        )

    # ------------------------------------------------------------- validate
    def validate(self, response: ProviderResponse) -> OrsDirections:
        payload = response.payload
        if isinstance(payload, dict) and "error" in payload:
            raise self._provider_error(payload["error"])
        try:
            return OrsDirections.model_validate(payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=f"unexpected directions payload: {exc.error_count()} problems",
            ) from exc

    def _provider_error(self, error: Any) -> ProviderError:
        """Turn an ORS error object into the right kind of failure.

        The distinction that matters: 2010 means the caller asked about a place
        with no road near it. That is a true statement about coverage, and
        reporting it as an outage would both mislead the caller and, after a few
        such requests, open the circuit breaker against a healthy provider.
        """
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error)
        if code in (_NO_ROUTABLE_POINT, _ROUTE_NOT_FOUND, 2004):
            return ProviderError(
                ProviderErrorCode.OUTSIDE_COVERAGE,
                self.provider_id,
                message=str(message),
            )
        if code == _INVALID_PARAMETER_VALUE:
            # A limit `coverage` failed to catch. Report it as coverage so the
            # caller learns what is unsupported rather than seeing an outage.
            return ProviderError(
                ProviderErrorCode.OUTSIDE_COVERAGE,
                self.provider_id,
                message=f"provider rejected a parameter: {message}",
            )
        return ProviderError(
            ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
            self.provider_id,
            message=f"provider error {code}: {message}",
        )

    # ------------------------------------------------------------ normalize
    def normalize(
        self, model: OrsDirections, response: ProviderResponse, query: RouteQuery
    ) -> list[RouteCandidate]:
        graph_date = model.metadata.engine.graph_date
        fetched_at = datetime.fromtimestamp(response.fetched_at, tz=UTC)
        routes: list[RouteCandidate] = []

        for index, feature in enumerate(model.features):
            coordinates = _line_coordinates(feature.geometry.coordinates)
            if len(coordinates) < 2:
                # A LineString needs two positions; one is not a route.
                continue

            # The provider gives its routes no id of their own, only a position
            # in the response. Using that bare index as the provenance record id
            # makes `source_id` "openrouteservice:0" for the first route of
            # every query ever made - so two unrelated routes would claim to be
            # the same source record. The request fingerprint keeps it unique
            # and still deterministic.
            fingerprint = _route_fingerprint(query, index)
            provider_route_id = f"{index}@{fingerprint}"
            summary = feature.properties.summary
            geometry = GeoLineString(coordinates=coordinates)

            routes.append(
                RouteCandidate(
                    route_id=f"{self.provider_id}:{fingerprint}",
                    provider_route_id=provider_route_id,
                    # The provider ranks its own output: index 0 is the route it
                    # considers best for the requested profile. Calling that
                    # RECOMMENDED would claim a risk judgement we have not made.
                    label=RouteLabel.ORIGINAL if index == 0 else RouteLabel.ALTERNATIVE,
                    mode=query.mode,
                    geometry=geometry,
                    segments=_segments(feature, query, geometry),
                    distance_m=summary.distance,
                    duration_seconds=summary.duration,
                    transfers=0,
                    exposure=None,
                    risk_level=RiskLevel.UNKNOWN,
                    quality=_quality(graph_date, fetched_at, feature),
                    sources=[
                        self.provenance(
                            response,
                            provider_record_id=provider_route_id,
                            observed_at=None,
                            published_at=graph_date,
                            payload_for_hash=feature.model_dump(mode="json"),
                        )
                    ],
                    bbox=_bbox(feature.bbox or model.bbox),
                )
            )
        return routes

    # Records are Pydantic, so the cache round-trip needs a real constructor.
    def _dehydrate(self, records: list[RouteCandidate]) -> Any:
        return [record.model_dump(mode="json") for record in records]

    def _rehydrate(self, payload: Any) -> list[RouteCandidate]:
        return [RouteCandidate.model_validate(item) for item in payload]


def _line_coordinates(raw: list[list[float]]) -> list[tuple[float, float]]:
    """ORS sends [lon, lat] and may append an elevation ordinate.

    Passing a three-element position through as a canonical coordinate smuggles
    a height into a field consumers read as a pair - the same trap the USGS feed
    sets with depth.
    """
    return [(float(point[0]), float(point[1])) for point in raw if len(point) >= 2]


def _route_fingerprint(query: RouteQuery, index: int) -> str:
    """A stable id for this route.

    Deterministic on purpose: the same request must produce the same `route_id`
    on every call, or a cached answer and a fresh one would look like two
    different routes to anything matching on id.
    """
    digest = content_hash(
        {
            "waypoints": [[round(c, 6) for c in point] for point in query.waypoints],
            "mode": str(query.mode),
            "preference": query.preference,
            "index": index,
        }
    )
    return digest.split(":", 1)[1][:16]


def _segments(
    feature: OrsFeature, query: RouteQuery, geometry: GeoLineString
) -> list[RouteSegment]:
    only_segment = len(feature.properties.segments) == 1
    segments: list[RouteSegment] = []
    for position, segment in enumerate(feature.properties.segments):
        segments.append(
            RouteSegment(
                segment_id=str(position),
                mode=query.mode,
                distance_m=segment.distance,
                duration_seconds=segment.duration,
                # A single-provider road leg has no schedule, so no departure or
                # arrival time is known. Deriving one from "now" would invent a
                # timetable the provider never gave.
                departure_time=None,
                arrival_time=None,
                geometry=geometry if only_segment else None,
                steps=[_step(step) for step in segment.steps],
            )
        )
    return segments


def _step(step: OrsStep) -> RouteStep:
    way_points: tuple[int, int] | None = None
    if step.way_points is not None and len(step.way_points) >= 2:
        way_points = (step.way_points[0], step.way_points[1])
    return RouteStep(
        distance_m=step.distance,
        duration_seconds=step.duration,
        instruction=step.instruction,
        # ORS writes "-" for an unnamed road; carrying that through would put a
        # dash on a map label.
        street_name=step.name if step.name not in (None, "", "-") else None,
        way_points=way_points,
    )


def _bbox(raw: list[float] | None) -> tuple[float, float, float, float] | None:
    if raw is None or len(raw) < 4:
        return None
    return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))


def _quality(graph_date: datetime | None, fetched_at: datetime, feature: OrsFeature) -> DataQuality:
    flags: list[QualityFlag] = [QualityFlag.INCOMPLETE]
    notes: list[str] = [
        "exposure and risk_level are not set by module 04 - a routing provider "
        "has no view on hazards; they are filled by /internal/v1/routes/evaluate"
    ]

    if not feature.properties.segments:
        flags.append(QualityFlag.MISSING)
        notes.append("provider returned no turn-by-turn segments")

    if graph_date is None:
        flags.append(QualityFlag.MISSING)
        notes.append("provider did not report the road graph build date")
        return DataQuality(status=DataStatus.PARTIAL, flags=flags, notes=notes)

    age_seconds = max(0, int((fetched_at - graph_date).total_seconds()))
    quality = DataQuality.from_age(
        age_seconds=age_seconds,
        fresh_within_seconds=GRAPH_FRESH_WITHIN_SECONDS,
        flags=flags,
        notes=notes,
    )
    quality.notes.append(
        f"freshness is the age of the road graph (built {graph_date:%Y-%m-%d}), "
        "not the age of this request"
    )
    return quality
