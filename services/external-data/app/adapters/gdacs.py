"""GDACS (Global Disaster Alert and Coordination System) adapter.

Mapping verified against `tests/fixtures/real-sanitized/gdacs/`. Five traps this
adapter absorbs, each confirmed against a real response:

1. `fromdate` / `todate` / `datemodified` arrive with **no zone suffix** -
   `"2026-08-28T05:13:35"`. Parsing them as naive local time shifts every event
   by the host offset, seven hours on this team's machines.
2. `iscurrent` and `istemporary` are **strings**, `"false"` not `false`. The
   obvious `bool(value)` reads `"false"` as True, which is how a closed event
   ends up presented as ongoing.
3. `eventname` is **empty on every record** in the captured feed; `name` is the
   field that actually carries a title.
4. `alertlevel` is `Green|Orange|Red` - an alert scale, not the project
   `Severity` enum, and not comparable with an earthquake magnitude.
5. Depth lives inside the free-text `severitytext` ("Magnitude 5M, Depth:10km")
   and nowhere structured, so it is not parsed out. A regex over prose is not
   something a safety decision should rest on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality
from app.domain.enums import EventType, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import DisasterQuery
from app.domain.records import DisasterEvent, GeoPoint
from app.transport.http import ProviderResponse

# Multi-hazard alerts follow the disaster freshness default (shared context
# § 10): 10 minutes. The registry TTL is 300s, so a cache hit stays inside it.
FRESH_WITHIN_SECONDS = 600

# GDACS hazard codes -> canonical event types. The project enum has no drought,
# so DR lands in OTHER rather than being mislabelled as something it is not.
EVENT_TYPES: dict[str, EventType] = {
    "EQ": EventType.EARTHQUAKE,
    "TC": EventType.CYCLONE,
    "FL": EventType.FLOOD,
    "VO": EventType.VOLCANO,
    "WF": EventType.WILDFIRE,
    "DR": EventType.OTHER,
}

# Which codes to ask for when the caller wants a canonical type. Several
# canonical types have no GDACS equivalent and are simply absent here.
REVERSE_EVENT_TYPES: dict[EventType, list[str]] = {
    EventType.EARTHQUAKE: ["EQ"],
    EventType.CYCLONE: ["TC"],
    EventType.STORM: ["TC"],
    EventType.FLOOD: ["FL"],
    EventType.VOLCANO: ["VO"],
    EventType.WILDFIRE: ["WF"],
}

ALL_EVENT_CODES = ["EQ", "TC", "FL", "VO", "WF", "DR"]


class GdacsSeverity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity: float | None = None
    severitytext: str | None = None
    severityunit: str | None = None


class GdacsUrls(BaseModel):
    model_config = ConfigDict(extra="ignore")

    report: str | None = None
    details: str | None = None
    geometry: str | None = None


class GdacsProperties(BaseModel):
    model_config = ConfigDict(extra="ignore")

    eventid: int
    episodeid: int | None = None
    eventtype: str
    eventname: str | None = None
    name: str | None = None
    description: str | None = None
    fromdate: str
    todate: str | None = None
    datemodified: str | None = None
    alertlevel: str | None = None
    alertscore: float | None = None
    # Strings on the wire: "true" / "false".
    iscurrent: str | None = None
    istemporary: str | None = None
    country: str | None = None
    glide: str | None = None
    source: str | None = None
    severitydata: GdacsSeverity | None = None
    url: GdacsUrls | None = None


class GdacsGeometry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    coordinates: list[float]


class GdacsFeature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    properties: GdacsProperties
    geometry: GdacsGeometry | None = None


class GdacsFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    features: list[GdacsFeature] = []


class GdacsAdapter(ProviderAdapter[DisasterQuery, DisasterEvent]):
    def coverage(self, query: DisasterQuery) -> CoverageDecision:
        if query.event_types and not _requested_codes(query.event_types):
            names = ", ".join(str(t) for t in query.event_types)
            return CoverageDecision(
                False, f"GDACS publishes no equivalent of: {names}"
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

    def build_request(self, query: DisasterQuery) -> ProviderRequest:
        codes = _requested_codes(query.event_types) or ALL_EVENT_CODES
        return ProviderRequest(
            path_or_url=self.provider.entry.endpoints["event_list"],
            # `eventlist` is the one filter the endpoint is known to honour, so
            # it is the only one pushed to the provider. Everything else is
            # filtered here and said so in quality.
            params={"eventlist": ",".join(codes)},
            cache_key_fields={
                "eventlist": codes,
                "bbox": list(query.bbox) if query.bbox else None,
                "window": _window_bucket(query),
            },
        )

    def validate(self, response: ProviderResponse) -> GdacsFeed:
        try:
            return GdacsFeed.model_validate(response.payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=(
                    "GDACS feed did not match the expected shape: "
                    f"{exc.error_count()} errors"
                ),
            ) from exc

    def normalize(
        self, model: GdacsFeed, response: ProviderResponse, query: DisasterQuery
    ) -> list[DisasterEvent]:
        fetched_at = datetime.fromtimestamp(response.fetched_at, tz=UTC)
        events: list[DisasterEvent] = []
        dropped = 0

        for feature in model.features:
            properties = feature.properties

            if feature.geometry is None or len(feature.geometry.coordinates) < 2:
                dropped += 1
                continue

            longitude, latitude = feature.geometry.coordinates[:2]
            effective_at = _parse_naive_utc(properties.fromdate)
            if effective_at is None:
                dropped += 1
                continue

            if not _inside_bbox(longitude, latitude, query.bbox):
                continue
            if not _inside_window(effective_at, query):
                continue

            ends_at = _parse_naive_utc(properties.todate)
            # An event whose end equals its start did not "end" - it is
            # instantaneous, the same shape an earthquake has in USGS.
            if ends_at == effective_at:
                ends_at = None

            severity_data = properties.severitydata or GdacsSeverity()
            events.append(
                DisasterEvent(
                    event_id=f"{self.provider_id}:{properties.eventid}"
                    f":{properties.episodeid or 0}",
                    event_type=EVENT_TYPES.get(
                        properties.eventtype.upper(), EventType.OTHER
                    ),
                    title=_title(properties),
                    # Plain text only. `htmldescription` is markup and must not
                    # be handed to a consumer that may render it.
                    description=properties.description,
                    geometry=GeoPoint.from_lat_lon(latitude, longitude),
                    effective_at=effective_at,
                    ends_at=ends_at,
                    instruction=None,
                    official=True,
                    magnitude=severity_data.severity,
                    magnitude_unit=severity_data.severityunit,
                    # Free text, never parsed for a number.
                    depth_km=None,
                    # Raw Green/Orange/Red, deliberately not cast to Severity.
                    alert_level=properties.alertlevel,
                    tsunami=None,
                    cross_reference_ids=_cross_ids(properties),
                    reporting_networks=_reporting_networks(properties),
                    episode_id=(
                        str(properties.episodeid) if properties.episodeid else None
                    ),
                    quality=_quality(
                        properties=properties,
                        effective_at=effective_at,
                        fetched_at=fetched_at,
                        client_side_filtered=query.bbox is not None
                        or query.start is not None
                        or query.end is not None,
                        severity_text=severity_data.severitytext,
                    ),
                    source=self.provenance(
                        response,
                        provider_record_id=str(properties.eventid),
                        observed_at=effective_at,
                        published_at=_parse_naive_utc(properties.datemodified),
                        source_url=(properties.url.report if properties.url else None),
                        payload_for_hash=properties.model_dump(mode="json"),
                    ),
                )
            )

        if dropped:
            for event in events:
                event.quality.notes.append(
                    f"{dropped} event(s) in this feed had no usable geometry or start time"
                )
        return events

    def _dehydrate(self, records: list[DisasterEvent]) -> list[dict[str, object]]:
        return [record.model_dump(mode="json") for record in records]

    def _rehydrate(self, payload: object) -> list[DisasterEvent]:
        assert isinstance(payload, list)
        return [DisasterEvent.model_validate(item) for item in payload]


# --------------------------------------------------------------------- helpers


def _parse_naive_utc(value: str | None) -> datetime | None:
    """GDACS timestamps carry no offset. They are UTC by the provider's own
    documentation, and the assumption is recorded in every record's quality
    notes rather than left implicit."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _wire_bool(value: str | None) -> bool | None:
    """`"false"` is a non-empty string, so `bool(value)` is True. That single
    mistake turns every closed event into an ongoing one."""
    if value is None:
        return None
    return value.strip().lower() == "true"


def _title(properties: GdacsProperties) -> str:
    """`eventname` is empty on every record in the captured feed, so `name` is
    the field that actually carries a title."""
    for candidate in (properties.eventname, properties.name, properties.description):
        if candidate and candidate.strip():
            return candidate.strip()
    return f"{properties.eventtype} {properties.eventid}"


def _requested_codes(event_types: list[EventType]) -> list[str]:
    if not event_types:
        return []
    codes: list[str] = []
    for event_type in event_types:
        for code in REVERSE_EVENT_TYPES.get(event_type, []):
            if code not in codes:
                codes.append(code)
    return codes


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
    return longitude >= min_lon or longitude <= max_lon


def _inside_window(moment: datetime, query: DisasterQuery) -> bool:
    if query.start and moment < query.start:
        return False
    return not (query.end and moment > query.end)


def _cross_ids(properties: GdacsProperties) -> list[str]:
    """Identifiers of *this event* elsewhere.

    GLIDE is an international disaster identifier shared across agencies, so it
    is the strongest dedup key GDACS offers - and the only value here that names
    one specific event. The reporting network and the episode number used to sit
    in this list too, which is how every storm JTWC ever reported ended up
    matching every other one.
    """
    if properties.glide and properties.glide.strip():
        return [properties.glide.strip()]
    return []


def _reporting_networks(properties: GdacsProperties) -> list[str]:
    """Who reported it - a different question from which event it is."""
    if properties.source and properties.source.strip():
        return [properties.source.strip()]
    return []


def _quality(
    *,
    properties: GdacsProperties,
    effective_at: datetime,
    fetched_at: datetime,
    client_side_filtered: bool,
    severity_text: str | None,
) -> DataQuality:
    # The age of our copy of the data, not the age of the disaster. Shared
    # context section 10 gives a disaster event a ten-minute budget and says
    # "fetch again" past it, which is only a coherent instruction about a stale
    # read - re-fetching cannot make an old cyclone younger. Measuring event age
    # here marked every record STALE regardless of when it was read.
    #
    # Unlike the USGS feed, GDACS publishes no feed generation time, so the
    # provider's own lag between an event occurring and appearing here is not
    # measurable. This says so rather than implying it is zero.
    age_seconds = 0
    flags: list[QualityFlag] = [QualityFlag.INFERRED]
    notes = [
        "provider timestamps carry no timezone offset and are read as UTC",
        "the feed carries no generation time, so freshness is the age of this "
        "read; any delay between the event and its publication here is not "
        "visible to us",
    ]

    revised_at = _parse_naive_utc(properties.datemodified)
    if revised_at is not None:
        stale_for = max(0, int((fetched_at - revised_at).total_seconds()))
        notes.append(
            f"provider last revised this record {revised_at:%Y-%m-%dT%H:%M:%SZ}"
        )
        # A record the provider has not touched in a day while still calling the
        # event current is worth flagging on its own - but as a flag, not as the
        # freshness of the read, which is a different question.
        if _wire_bool(properties.iscurrent) and stale_for > 24 * 3600:
            flags.append(QualityFlag.STALE)
            notes.append(
                "the provider still marks this event current but has not "
                f"revised the record in {stale_for // 3600} hours"
            )

    if client_side_filtered:
        notes.append(
            "bbox and time filtering applied client-side; the provider filters "
            "by hazard type only"
        )
        flags.append(QualityFlag.OUTSIDE_COVERAGE)

    if severity_text:
        # Depth and other detail live in here as prose. Passing it through lets
        # a human read it without anyone parsing a number out of it.
        notes.append(f"provider severity text: {severity_text}")

    is_current = _wire_bool(properties.iscurrent)
    if is_current is False:
        notes.append("provider marks this event as no longer current")
    if _wire_bool(properties.istemporary):
        flags.append(QualityFlag.INFERRED)
        notes.append("provider marks this event as temporary and subject to revision")

    if properties.severitydata is None or properties.severitydata.severity is None:
        flags.append(QualityFlag.INCOMPLETE)
        notes.append("provider supplied no severity value")

    return DataQuality.from_age(
        age_seconds=age_seconds,
        fresh_within_seconds=FRESH_WITHIN_SECONDS,
        flags=flags,
        notes=notes,
    )
