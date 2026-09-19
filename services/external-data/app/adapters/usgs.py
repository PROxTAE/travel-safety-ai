"""USGS Earthquake Hazards Program adapter.

Mapping verified against `tests/fixtures/real-sanitized/usgs/`. Four traps this
adapter absorbs, each confirmed against a real response:

1. `properties.time` and `properties.updated` are **epoch milliseconds**, not
   seconds and not ISO. Off by a factor of 1000 puts every quake in 1970.
2. `geometry.coordinates` carries **three ordinates** - `[lon, lat, depth_km]`.
   Passing it straight through as a canonical Point smuggles a depth in where
   consumers expect two numbers.
3. The summary feeds have **no bbox and no time parameter**. Filtering is ours
   to do, client-side, and the fact that it was done client-side against a
   fixed window is recorded as coverage rather than hidden.
4. `properties.alert` is the PAGER **impact** level and is frequently null;
   `properties.mag` is physical magnitude. They disagree often, so neither is
   cast to `Severity` here - see open question Q3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, ValidationError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality
from app.domain.enums import DataStatus, EventType, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import DisasterQuery
from app.domain.records import DisasterEvent, GeoPoint
from app.transport.http import ProviderResponse

# Earthquakes are FRESH for 10 minutes (shared context § 10). The registry TTL
# is 60s, so a cache hit is always well inside that window.
FRESH_WITHIN_SECONDS = 600

# Summary feed windows the provider publishes, smallest first.
FEED_WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("hour", timedelta(hours=1)),
    ("day", timedelta(days=1)),
    ("week", timedelta(days=7)),
    ("month", timedelta(days=30)),
)

# Magnitude tiers the provider itself publishes. Choosing one is the caller's
# policy decision, not ours - module 04 does not decide which quakes matter.
MAGNITUDE_TIERS: tuple[tuple[float, str], ...] = (
    (4.5, "4.5"),
    (2.5, "2.5"),
    (1.0, "1.0"),
)


class UsgsGeometry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["Point"]
    # [lon, lat] or [lon, lat, depth_km] - the provider sends three.
    coordinates: list[float]


class UsgsProperties(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time: int  # epoch milliseconds
    updated: int | None = None
    place: str | None = None
    title: str | None = None
    url: str | None = None
    mag: float | None = None
    magType: str | None = None  # provider spelling, kept verbatim
    alert: str | None = None
    status: str | None = None
    tsunami: int | None = None
    sig: int | None = None
    ids: str | None = None


class UsgsFeature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    properties: UsgsProperties
    geometry: UsgsGeometry | None = None


class UsgsFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    features: list[UsgsFeature] = []


class UsgsAdapter(ProviderAdapter[DisasterQuery, DisasterEvent]):
    def coverage(self, query: DisasterQuery) -> CoverageDecision:
        if query.event_types and EventType.EARTHQUAKE not in query.event_types:
            return CoverageDecision(
                False, "USGS publishes earthquakes only, and none were requested"
            )
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

    def _feed_url(self, feed: str) -> str:
        """Absolute URL for one summary feed.

        `USGS_FEED_URL` is configured as a complete feed URL rather than an
        origin (that is what `.env.example` hands every module), so joining a
        path onto it duplicates the whole path. Only the origin is taken from
        it; the path comes from the endpoint template in providers.yaml. The
        host still has to match, which the shared transport enforces.
        """
        parts = urlsplit(self.provider.base_url or "https://earthquake.usgs.gov")
        template = self.provider.entry.endpoints.get(
            "summary_feed", "/earthquakes/feed/v1.0/summary/{window}.geojson"
        )
        return urlunsplit(
            (parts.scheme, parts.netloc, template.replace("{window}", feed), "", "")
        )

    def build_request(self, query: DisasterQuery) -> ProviderRequest:
        window = _feed_window(query.start)
        tier = _magnitude_tier(query.min_magnitude)

        return ProviderRequest(
            path_or_url=self._feed_url(f"{tier}_{window}"),
            cache_key_fields={
                "feed": f"{tier}_{window}",
                # The feed is global; the bbox and time filters are applied to
                # the same payload afterwards, so they belong in the key too or
                # a narrower query would be answered from a wider one's result.
                "bbox": list(query.bbox) if query.bbox else None,
                "window": _window_bucket(query),
                "types": sorted(str(t) for t in query.event_types),
            },
        )

    def validate(self, response: ProviderResponse) -> UsgsFeed:
        try:
            return UsgsFeed.model_validate(response.payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=(
                    "USGS feed did not match the expected shape: "
                    f"{exc.error_count()} errors"
                ),
            ) from exc

    def normalize(
        self, model: UsgsFeed, response: ProviderResponse, query: DisasterQuery
    ) -> list[DisasterEvent]:
        fetched_at = datetime.fromtimestamp(response.fetched_at, tz=UTC)
        window = _feed_window(query.start)
        events: list[DisasterEvent] = []
        dropped = 0

        for feature in model.features:
            if feature.geometry is None or len(feature.geometry.coordinates) < 2:
                # A hazard event with no location cannot be intersected with a
                # route, so it is not useful - but it is counted, not ignored.
                dropped += 1
                continue

            longitude, latitude = feature.geometry.coordinates[:2]
            depth_km = (
                feature.geometry.coordinates[2]
                if len(feature.geometry.coordinates) > 2
                else None
            )
            occurred_at = _from_epoch_ms(feature.properties.time)

            if not _inside_bbox(longitude, latitude, query.bbox):
                continue
            if not _inside_window(occurred_at, query):
                continue

            events.append(
                DisasterEvent(
                    event_id=f"{self.provider_id}:{feature.id}",
                    event_type=EventType.EARTHQUAKE,
                    title=feature.properties.title
                    or feature.properties.place
                    or feature.id,
                    description=_describe(feature),
                    # Q2/Q3 unanswered: magnitude and PAGER alert disagree and
                    # neither is cast here.
                    geometry=GeoPoint.from_lat_lon(latitude, longitude),
                    effective_at=occurred_at,
                    # An earthquake is instantaneous; aftershocks are their own
                    # events with their own ids.
                    ends_at=None,
                    instruction=None,
                    official=True,
                    magnitude=feature.properties.mag,
                    magnitude_unit=feature.properties.magType or "M",
                    depth_km=depth_km,
                    alert_level=feature.properties.alert,
                    tsunami=bool(feature.properties.tsunami)
                    if feature.properties.tsunami is not None
                    else None,
                    cross_reference_ids=_cross_ids(feature.properties.ids, feature.id),
                    quality=_quality(
                        feature=feature,
                        occurred_at=occurred_at,
                        fetched_at=fetched_at,
                        window=window,
                        client_side_filtered=query.bbox is not None
                        or query.start is not None
                        or query.end is not None,
                    ),
                    source=self.provenance(
                        response,
                        provider_record_id=feature.id,
                        # A real observation time, unlike the weather adapter.
                        observed_at=occurred_at,
                        published_at=_from_epoch_ms(feature.properties.updated)
                        if feature.properties.updated
                        else None,
                        source_url=feature.properties.url,
                        payload_for_hash=feature.model_dump(mode="json"),
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


def _from_epoch_ms(value: int) -> datetime:
    """USGS timestamps are epoch **milliseconds**. Treating them as seconds
    places every event in January 1970, which reads as very stale rather than
    as an error."""
    return datetime.fromtimestamp(value / 1000.0, tz=UTC)


def _feed_window(start: datetime | None) -> str:
    """Smallest published feed that still covers the requested start."""
    if start is None:
        return "day"
    age = datetime.now(UTC) - start
    for name, span in FEED_WINDOWS:
        if age <= span:
            return name
    return "month"


def _magnitude_tier(min_magnitude: float | None) -> str:
    if min_magnitude is None:
        return "all"
    for threshold, name in MAGNITUDE_TIERS:
        if min_magnitude >= threshold:
            return name
    return "all"


def _window_bucket(query: DisasterQuery) -> str:
    start = (
        query.start.replace(minute=0, second=0, microsecond=0) if query.start else None
    )
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
    # Box crosses the antimeridian: it is the union of two spans, not one.
    return longitude >= min_lon or longitude <= max_lon


def _inside_window(moment: datetime, query: DisasterQuery) -> bool:
    if query.start and moment < query.start:
        return False
    return not (query.end and moment > query.end)


def _describe(feature: UsgsFeature) -> str | None:
    """The feed has no description field; `title` already reads as one."""
    parts: list[str] = []
    if feature.properties.mag is not None:
        parts.append(f"magnitude {feature.properties.mag}")
    if feature.geometry is not None and len(feature.geometry.coordinates) > 2:
        parts.append(f"depth {feature.geometry.coordinates[2]} km")
    if feature.properties.status:
        parts.append(f"status {feature.properties.status}")
    return ", ".join(parts) if parts else None


def _cross_ids(raw: str | None, own_id: str) -> list[str]:
    """`ids` arrives as `",attliih5,aka2026slmipb,us7000ti1p,"` - comma
    delimited with leading and trailing commas. These are the same quake as
    seen by other networks and are what makes cross-source dedup possible."""
    if not raw:
        return []
    return [part for part in raw.split(",") if part and part != own_id]


def _quality(
    *,
    feature: UsgsFeature,
    occurred_at: datetime,
    fetched_at: datetime,
    window: str,
    client_side_filtered: bool,
) -> DataQuality:
    age_seconds = max(0, int((fetched_at - occurred_at).total_seconds()))
    flags: list[QualityFlag] = []
    notes = [f"from the USGS {window} summary feed"]

    if client_side_filtered:
        # The feed has no bbox or time parameter, so anything outside the
        # requested area was removed here rather than by the provider. Saying so
        # is what lets module 05 know the set is complete only for this window.
        notes.append(
            "bbox and time filtering applied client-side; the feed itself is "
            f"global and covers the past {window}"
        )
        flags.append(QualityFlag.OUTSIDE_COVERAGE)

    if feature.properties.status and feature.properties.status != "reviewed":
        flags.append(QualityFlag.INFERRED)
        notes.append(
            f"provider status is '{feature.properties.status}', not human-reviewed"
        )

    if feature.properties.mag is None:
        flags.append(QualityFlag.INCOMPLETE)
        notes.append("provider supplied no magnitude")

    quality = DataQuality.from_age(
        age_seconds=age_seconds,
        fresh_within_seconds=FRESH_WITHIN_SECONDS,
        flags=flags,
        notes=notes,
    )
    # An event from a 30-day feed is old by definition; that is history, not a
    # stale read of the present.
    if quality.status is DataStatus.STALE and window in {"week", "month"}:
        quality.notes.append(
            "age reflects when the earthquake happened, not when the feed was read"
        )
    return quality
