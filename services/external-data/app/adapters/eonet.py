"""NASA EONET v3 adapter.

Mapping verified against `tests/fixtures/real-sanitized/eonet/`. Four traps this
adapter absorbs:

1. `geometry` is a **list of observations over time**, oldest first - a track,
   not a location. Typhoon Dujuan in the captured feed has 11 entries whose
   first and last points are **1,480 km apart**, with intensity rising from 35
   to 65 kts. Reading `geometry[0]` reports where the storm was three days ago,
   at the strength it had then, and nothing about it looks wrong.
2. `closed` is `null` while an event is ongoing. Treating the key's presence as
   "this ended" closes every live hazard.
3. `magnitudeValue` / `magnitudeUnit` are **per category** - acres for a
   wildfire, knots for a storm. They are not comparable across event types and
   must never be ranked against each other.
4. A geometry entry may be a **Polygon**, not a Point. The canonical record
   holds a point, so a polygon is reduced to its centroid and flagged, rather
   than being dropped or silently truncated to its first vertex.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality
from app.domain.enums import EventType, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import DisasterQuery
from app.domain.records import DisasterEvent, GeoPoint
from app.transport.http import ProviderResponse

# EONET is curated and slower to publish than USGS or GDACS, so it corroborates
# rather than leads. Freshness still follows the disaster default of 10 minutes.
FRESH_WITHIN_SECONDS = 600

MAX_EVENTS = 200

CATEGORIES: dict[str, EventType] = {
    "wildfires": EventType.WILDFIRE,
    "severeStorms": EventType.STORM,
    "volcanoes": EventType.VOLCANO,
    "floods": EventType.FLOOD,
    "earthquakes": EventType.EARTHQUAKE,
    "landslides": EventType.LANDSLIDE,
    "tempExtremes": EventType.EXTREME_TEMPERATURE,
    "drought": EventType.OTHER,
    "dustHaze": EventType.OTHER,
    "manmade": EventType.OTHER,
    "seaLakeIce": EventType.OTHER,
    "snow": EventType.OTHER,
    "waterColor": EventType.OTHER,
}

REVERSE_CATEGORIES: dict[EventType, list[str]] = {
    EventType.WILDFIRE: ["wildfires"],
    EventType.STORM: ["severeStorms"],
    EventType.CYCLONE: ["severeStorms"],
    EventType.VOLCANO: ["volcanoes"],
    EventType.FLOOD: ["floods"],
    EventType.EARTHQUAKE: ["earthquakes"],
    EventType.LANDSLIDE: ["landslides"],
    EventType.EXTREME_TEMPERATURE: ["tempExtremes"],
}


class EonetGeometry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str
    type: str
    coordinates: Any
    magnitudeValue: float | None = None  # provider spelling
    magnitudeUnit: str | None = None  # provider spelling


class EonetCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str | None = None


class EonetSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    url: str | None = None


class EonetEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    description: str | None = None
    link: str | None = None
    # null while the event is ongoing.
    closed: str | None = None
    categories: list[EonetCategory] = []
    sources: list[EonetSource] = []
    geometry: list[EonetGeometry] = []


class EonetFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    events: list[EonetEvent] = []


class EonetAdapter(ProviderAdapter[DisasterQuery, DisasterEvent]):
    def coverage(self, query: DisasterQuery) -> CoverageDecision:
        if query.event_types and not _requested_categories(query.event_types):
            names = ", ".join(str(t) for t in query.event_types)
            return CoverageDecision(False, f"EONET publishes no equivalent of: {names}")
        if query.bbox is not None:
            min_lon, min_lat, max_lon, max_lat = query.bbox
            if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
                return CoverageDecision(False, "bbox longitude out of range")
            if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
                return CoverageDecision(False, "bbox latitude out of range")
            if min_lat > max_lat:
                return CoverageDecision(False, "bbox latitudes are inverted")
        if query.start and query.end and query.end < query.start:
            return CoverageDecision(False, "time window ends before it starts")
        return CoverageDecision(True)

    def build_request(self, query: DisasterQuery) -> ProviderRequest:
        params: dict[str, Any] = {"limit": MAX_EVENTS}

        categories = _requested_categories(query.event_types)
        if categories:
            params["category"] = ",".join(categories)

        # Unlike USGS and GDACS, this provider does filter by area and date.
        # A box that crosses the antimeridian is not expressible as one range,
        # so that case is filtered here instead - and either way the result is
        # re-checked below, because a silently widened result set is worse than
        # a slow one.
        pushed_bbox = _pushable_bbox(query.bbox)
        if pushed_bbox is not None:
            min_lon, min_lat, max_lon, max_lat = pushed_bbox
            # EONET documents bbox as upper-left then lower-right.
            params["bbox"] = f"{min_lon},{max_lat},{max_lon},{min_lat}"

        if query.start:
            params["start"] = query.start.astimezone(UTC).date().isoformat()
        if query.end:
            params["end"] = query.end.astimezone(UTC).date().isoformat()
        # Asking about a past window means closed events are in scope too.
        params["status"] = "all" if (query.start or query.end) else "open"

        return ProviderRequest(
            path_or_url=self.provider.entry.endpoints["events"],
            params=params,
            cache_key_fields={
                "categories": categories,
                "bbox": list(query.bbox) if query.bbox else None,
                "window": _window_bucket(query),
                "status": params["status"],
            },
        )

    def validate(self, response: ProviderResponse) -> EonetFeed:
        try:
            return EonetFeed.model_validate(response.payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=(
                    "EONET feed did not match the expected shape: " f"{exc.error_count()} errors"
                ),
            ) from exc

    def normalize(
        self, model: EonetFeed, response: ProviderResponse, query: DisasterQuery
    ) -> list[DisasterEvent]:
        fetched_at = datetime.fromtimestamp(response.fetched_at, tz=UTC)
        events: list[DisasterEvent] = []
        dropped = 0

        for raw in model.events:
            track = _sorted_track(raw.geometry)
            if not track:
                dropped += 1
                continue

            first, latest = track[0], track[-1]
            started_at = _parse_iso(first.date)
            if started_at is None:
                dropped += 1
                continue

            point = _to_point(latest)
            if point is None:
                dropped += 1
                continue

            longitude, latitude, from_polygon = point

            # The provider filtered by bbox, but verify rather than trust: a
            # change in its behaviour would otherwise widen every result set
            # silently.
            if not _inside_bbox(longitude, latitude, query.bbox):
                continue
            if not _inside_window(started_at, query):
                continue

            events.append(
                DisasterEvent(
                    event_id=f"{self.provider_id}:{raw.id}",
                    event_type=_event_type(raw.categories),
                    title=raw.title,
                    description=raw.description,
                    geometry=GeoPoint.from_lat_lon(latitude, longitude),
                    # First observation is when the event began; the position
                    # above is where it is now.
                    effective_at=started_at,
                    ends_at=_parse_iso(raw.closed),
                    instruction=None,
                    official=True,
                    # Current intensity, from the latest observation - not the
                    # value it had when it was first seen.
                    magnitude=latest.magnitudeValue,
                    magnitude_unit=latest.magnitudeUnit,
                    depth_km=None,
                    alert_level=None,
                    tsunami=None,
                    # EONET publishes no identifier for this event in another
                    # system, so there is nothing to cross-reference. The
                    # agencies that reported it are a different fact and belong
                    # in their own field: JTWC reports every typhoon, so
                    # matching on it groups every typhoon.
                    cross_reference_ids=[],
                    reporting_networks=[source.id for source in raw.sources if source.id],
                    quality=_quality(
                        track_length=len(track),
                        started_at=started_at,
                        observed_at=_parse_iso(latest.date) or started_at,
                        fetched_at=fetched_at,
                        from_polygon=from_polygon,
                        is_closed=raw.closed is not None,
                        magnitude_unit=latest.magnitudeUnit,
                    ),
                    source=self.provenance(
                        response,
                        provider_record_id=raw.id,
                        # The latest observation is what this record describes.
                        observed_at=_parse_iso(latest.date),
                        published_at=None,
                        source_url=(raw.sources[0].url if raw.sources else raw.link),
                        payload_for_hash=raw.model_dump(mode="json"),
                    ),
                )
            )

        if dropped:
            for event in events:
                event.quality.notes.append(
                    f"{dropped} event(s) in this feed had no usable geometry"
                )
        return events

    def _dehydrate(self, records: list[DisasterEvent]) -> list[dict[str, object]]:
        return [record.model_dump(mode="json") for record in records]

    def _rehydrate(self, payload: object) -> list[DisasterEvent]:
        assert isinstance(payload, list)
        return [DisasterEvent.model_validate(item) for item in payload]


# --------------------------------------------------------------------- helpers


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _sorted_track(geometry: list[EonetGeometry]) -> list[EonetGeometry]:
    """Oldest first. The feed already arrives in order, but a track whose order
    is assumed rather than enforced is one provider change away from reporting a
    storm's position backwards."""
    dated = [(entry, _parse_iso(entry.date)) for entry in geometry]
    usable = [(entry, moment) for entry, moment in dated if moment is not None]
    usable.sort(key=lambda pair: pair[1])
    return [entry for entry, _ in usable]


def _to_point(entry: EonetGeometry) -> tuple[float, float, bool] | None:
    """(longitude, latitude, came_from_polygon).

    A Polygon is reduced to the mean of its outer ring. That is an
    approximation, so it is flagged - but dropping the event entirely would
    lose a real hazard, and taking the first vertex would place it on an edge.
    """
    coordinates = entry.coordinates
    if entry.type == "Point":
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            return float(coordinates[0]), float(coordinates[1]), False
        return None

    ring = coordinates
    # Polygon -> [ring][vertex][xy]; MultiPolygon -> [poly][ring][vertex][xy].
    while isinstance(ring, list) and ring and isinstance(ring[0], list):
        if len(ring[0]) == 2 and all(isinstance(v, int | float) for v in ring[0]):
            break
        ring = ring[0]

    if not isinstance(ring, list) or not ring:
        return None
    points = [p for p in ring if isinstance(p, list) and len(p) >= 2]
    if not points:
        return None
    return (
        sum(float(p[0]) for p in points) / len(points),
        sum(float(p[1]) for p in points) / len(points),
        True,
    )


def _event_type(categories: list[EonetCategory]) -> EventType:
    for category in categories:
        mapped = CATEGORIES.get(category.id)
        if mapped is not None and mapped is not EventType.OTHER:
            return mapped
    return EventType.OTHER


def _requested_categories(event_types: list[EventType]) -> list[str]:
    if not event_types:
        return []
    categories: list[str] = []
    for event_type in event_types:
        for name in REVERSE_CATEGORIES.get(event_type, []):
            if name not in categories:
                categories.append(name)
    return categories


def _pushable_bbox(
    bbox: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    min_lon, _, max_lon, _ = bbox
    # A wrapping box is two spans; the provider takes one.
    return None if min_lon > max_lon else bbox


def _window_bucket(query: DisasterQuery) -> str:
    start = query.start.replace(minute=0, second=0, microsecond=0) if query.start else None
    end = query.end.replace(minute=0, second=0, microsecond=0) if query.end else None
    return f"{start.isoformat() if start else '*'}/{end.isoformat() if end else '*'}"


def _inside_bbox(
    longitude: float, latitude: float, bbox: tuple[float, float, float, float] | None
) -> bool:
    if bbox is None:
        return True
    min_lon, min_lat, max_lon, max_lat = bbox
    if not min_lat <= latitude <= max_lat:
        return False
    if min_lon <= max_lon:
        return min_lon <= longitude <= max_lon
    return longitude >= min_lon or longitude <= max_lon


def _inside_window(moment: datetime, query: DisasterQuery) -> bool:
    if query.start and moment < query.start:
        return False
    return not (query.end and moment > query.end)


def _quality(
    *,
    track_length: int,
    started_at: datetime,
    observed_at: datetime,
    fetched_at: datetime,
    from_polygon: bool,
    is_closed: bool,
    magnitude_unit: str | None,
) -> DataQuality:
    # The age of our copy of the feed, not the age of the event. Shared context
    # section 10 gives a disaster event a ten-minute budget and says "fetch
    # again" past it, which only makes sense about a stale read - re-fetching
    # cannot make an old wildfire younger. Measuring from the last observation
    # marked every EONET record STALE, because a curated source that publishes
    # once or twice a day can never be ten minutes old by that measure.
    #
    # EONET, like GDACS and unlike USGS, publishes no feed generation time, so
    # the provider's own publication lag is not measurable here. The note says
    # so instead of implying it is zero.
    age_seconds = 0
    flags: list[QualityFlag] = []
    notes = [
        "EONET is curated and publishes more slowly than USGS or GDACS; treat as "
        "corroboration, not as the first alert",
        "the feed carries no generation time, so freshness is the age of this "
        "read; the provider's publication lag is not visible to us",
        f"the provider last observed this event {observed_at:%Y-%m-%dT%H:%M:%SZ}",
    ]

    if track_length > 1:
        notes.append(
            f"position is the latest of {track_length} observations, recorded "
            f"{observed_at.isoformat()}; the event began {started_at.isoformat()}"
        )

    if from_polygon:
        flags.append(QualityFlag.INFERRED)
        notes.append("provider gave an area; the point is its centroid")

    if is_closed:
        notes.append("provider has marked this event closed")

    if magnitude_unit:
        # acres for a fire, knots for a storm. Saying so stops anyone ranking
        # one against the other.
        notes.append(
            f"magnitude is in {magnitude_unit} and is only comparable within " "this event type"
        )

    return DataQuality.from_age(
        age_seconds=age_seconds,
        fresh_within_seconds=FRESH_WITHIN_SECONDS,
        flags=flags,
        notes=notes,
    )
