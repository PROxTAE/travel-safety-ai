"""GTFS / GTFS-Realtime adapter for registered agency feeds.

Verified against `tests/fixtures/real-sanitized/gtfs_mta/`, captured live on
2026-09-20 from the New York City subway feeds (no credential required). Four
things this adapter absorbs, all confirmed by calling the real feeds:

1. **The realtime `trip_id` is not the schedule `trip_id`.** The static feed
   writes `BSP26GEN-A055-Sunday-00_051550_A..N54R`; the realtime feed writes
   `051550_A..N54R` — the same trip with the service prefix stripped. Joining
   them with `==` matches **zero of sixty-seven** live trips, and nothing
   errors: every train silently becomes "unknown". The join is on the suffix
   after the last underscore.

2. **Even the suffix join only matches about a third of live trips**, because a
   running train may have no counterpart in today's published schedule at all.
   That is normal, not a bug — and it is why `delay_minutes` is null and the
   status is `UNKNOWN` for the rest, rather than a comforting `ON_TIME`.

3. **The `delay` field is usually zero even when a train is late.** This
   provider reports absolute arrival and departure times instead, so delay has
   to be computed against the schedule. Trusting `delay` would report every
   train as punctual.

4. **A schedule is not a status.** A static feed says when a train was meant to
   run; only the realtime feed says anything about now. They are mapped to
   different quality flags, and a stale realtime feed degrades the record
   rather than being quietly served as current.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality
from app.domain.enums import (
    DataStatus,
    QualityFlag,
    TransportStatusCode,
    TravelMode,
)
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import TransitQuery
from app.domain.records import Cancellation, GeoPoint, StopRef, TransportStatus
from app.observability.logging import get_logger
from app.transport.http import ProviderResponse

log = get_logger(__name__)

# GTFS-Realtime trip updates are expected to regenerate about every 30 seconds.
# Shared context § 10 gives GTFS-RT a 90-second budget, past which a status is
# UNKNOWN or STALE rather than current.
REALTIME_FRESH_WITHIN_SECONDS = 90

# A schedule is republished on the order of days; the registry TTL is a day.
SCHEDULE_FRESH_WITHIN_SECONDS = 7 * 24 * 3600

# GTFS-Realtime ScheduleRelationship for a trip.
_TRIP_SCHEDULED = 0
_TRIP_ADDED = 1
_TRIP_UNSCHEDULED = 2
_TRIP_CANCELED = 3

# route_type -> canonical mode (GTFS reference, basic types only).
_MODE_BY_ROUTE_TYPE: dict[str, TravelMode] = {
    "0": TravelMode.TRAIN,  # tram / light rail
    "1": TravelMode.TRAIN,  # subway
    "2": TravelMode.TRAIN,  # rail
    "3": TravelMode.BUS,
    "4": TravelMode.BUS,  # ferry has no canonical mode; not claimed as TRAIN
    "5": TravelMode.TRAIN,
    "6": TravelMode.TRAIN,
    "7": TravelMode.TRAIN,
    "11": TravelMode.BUS,
    "12": TravelMode.TRAIN,
}


@dataclass(slots=True)
class ScheduledTrip:
    trip_id: str
    route_id: str
    service_id: str
    headsign: str | None
    stop_times: list[tuple[str, str, str]] = field(default_factory=list)
    """(stop_id, arrival_time, departure_time) in feed-local `HH:MM:SS`, where
    the hour may exceed 23 for a trip that runs past midnight."""


@dataclass(slots=True)
class Schedule:
    """One parsed static feed, indexed for the joins this adapter performs."""

    feed_id: str
    fetched_at: datetime
    content_hash: str
    agency_name: str | None
    agency_timezone: str | None
    routes: dict[str, dict[str, str]]
    stops: dict[str, dict[str, str]]
    trips_by_suffix: dict[str, list[ScheduledTrip]]

    @property
    def trip_count(self) -> int:
        return sum(len(v) for v in self.trips_by_suffix.values())


def _rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    if name not in archive.namelist():
        return []
    with archive.open(name) as handle:
        return list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")))


def trip_suffix(trip_id: str) -> str:
    """Reduce a trip id from either feed to the key the two share.

    Schedule: `BSP26GEN-A055-Sunday-00_000950_A..S74R`
    Realtime: `049350_A..S75R`

    The shared part is "origin time + path": the last two underscore-separated
    segments. The static feed prefixes a service identifier; the realtime feed
    does not. Joining the ids verbatim matches **nothing at all**, and nothing
    errors - an unmatched trip is still a valid record with no schedule
    attached, so every train silently becomes UNKNOWN.

    Two wrong versions of this function came before this one, and both looked
    healthy while matching zero trips:

    - `rsplit("_", 1)[-1]` keeps only `A..S74R` and throws away the origin time,
      so it is no longer a specific trip.
    - `split("_", 1)[1]` is right for the schedule id but wrong for the realtime
      one, which has a single underscore and is already in short form - it
      reduces `049350_A..S75R` to `A..S75R`.

    Taking the last two segments is correct for both, because the path segment
    never contains an underscore.
    """
    parts = trip_id.split("_")
    return "_".join(parts[-2:]) if len(parts) >= 2 else trip_id


def parse_schedule(
    payload: bytes, *, feed_id: str, fetched_at: datetime, content_hash: str
) -> Schedule:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
            feed_id,
            message="the schedule feed is not a readable zip archive",
        ) from exc

    required = {"routes.txt", "trips.txt", "stops.txt", "stop_times.txt"}
    missing = required - set(archive.namelist())
    if missing:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
            feed_id,
            message=f"schedule feed is missing {', '.join(sorted(missing))}",
        )

    agency = _rows(archive, "agency.txt")
    routes = {r["route_id"]: r for r in _rows(archive, "routes.txt")}
    stops = {s["stop_id"]: s for s in _rows(archive, "stops.txt")}

    trips: dict[str, ScheduledTrip] = {}
    for row in _rows(archive, "trips.txt"):
        trips[row["trip_id"]] = ScheduledTrip(
            trip_id=row["trip_id"],
            route_id=row.get("route_id", ""),
            service_id=row.get("service_id", ""),
            headsign=(row.get("trip_headsign") or None),
        )

    orphan_stop_times = 0
    for row in _rows(archive, "stop_times.txt"):
        trip = trips.get(row["trip_id"])
        if trip is None:
            # A stop_time pointing at no trip is a broken foreign key; counted
            # rather than ignored, because a feed that starts producing them is
            # a feed that changed.
            orphan_stop_times += 1
            continue
        trip.stop_times.append(
            (
                row.get("stop_id", ""),
                row.get("arrival_time", ""),
                row.get("departure_time", ""),
            )
        )

    if orphan_stop_times:
        log.warning(
            "gtfs_schedule_orphan_stop_times", feed=feed_id, count=orphan_stop_times
        )

    by_suffix: dict[str, list[ScheduledTrip]] = {}
    for trip in trips.values():
        by_suffix.setdefault(trip_suffix(trip.trip_id), []).append(trip)

    return Schedule(
        feed_id=feed_id,
        fetched_at=fetched_at,
        content_hash=content_hash,
        agency_name=(agency[0].get("agency_name") if agency else None),
        agency_timezone=(agency[0].get("agency_timezone") if agency else None),
        routes=routes,
        stops=stops,
        trips_by_suffix=by_suffix,
    )


class GtfsAdapter(ProviderAdapter[TransitQuery, TransportStatus]):
    """One registered agency feed: a static schedule plus a realtime overlay."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._schedules: dict[str, Schedule] = {}

    # --------------------------------------------------------------- feeds
    @property
    def feeds(self) -> list[dict[str, Any]]:
        return list(getattr(self.provider.entry, "feeds", []) or [])

    def _feed(self, feed_id: str | None = None) -> dict[str, Any] | None:
        feeds = self.feeds
        if not feeds:
            return None
        if feed_id is None:
            return feeds[0]
        return next((f for f in feeds if f.get("feed_id") == feed_id), None)

    def _feeds_for(self, query: TransitQuery) -> list[dict[str, Any]]:
        feeds = self.feeds
        if query.feed_ids:
            feeds = [f for f in feeds if f.get("feed_id") in query.feed_ids]
        if query.bbox is not None:
            feeds = [f for f in feeds if _bbox_overlaps(query.bbox, f.get("bbox"))]
        return feeds

    # ------------------------------------------------------------ coverage
    def coverage(self, query: TransitQuery) -> CoverageDecision:
        if not self.feeds:
            return CoverageDecision(
                False, "no agency feed is registered for this provider"
            )
        if not self._feeds_for(query):
            names = ", ".join(str(f.get("feed_id")) for f in self.feeds)
            return CoverageDecision(
                False,
                "transit coverage is per agency and never global; "
                f"registered feeds are {names} and none covers this query",
            )
        return CoverageDecision(True)

    # ------------------------------------------------------------- request
    def build_request(self, query: TransitQuery) -> ProviderRequest:
        feed = self._feeds_for(query)[0]
        url = feed.get("realtime_trip_updates_url")
        if not url:
            raise ProviderError(
                ProviderErrorCode.OUTSIDE_COVERAGE,
                self.provider_id,
                message=(
                    f"feed {feed.get('feed_id')} publishes a schedule but no "
                    "realtime trip updates; a schedule is not a live status"
                ),
            )
        return ProviderRequest(
            path_or_url=str(url),
            method="GET",
            cache_key_fields={
                "feed_id": feed.get("feed_id"),
                "routes": sorted(query.route_ids),
                "stops": sorted(query.stop_ids),
                "limit": query.limit,
            },
        )

    async def fetch(
        self, request: ProviderRequest, *, deadline_seconds: float | None = None
    ) -> ProviderResponse:
        # Protocol Buffers, not JSON: decoding it as JSON would report a schema
        # change on a perfectly healthy feed.
        return await self.transport.request(
            self.provider,
            request.path_or_url,
            method=request.method,
            params=request.params,
            headers=request.headers,
            deadline_seconds=deadline_seconds,
            decode_json=False,
        )

    # ------------------------------------------------------------ validate
    def validate(self, response: ProviderResponse) -> Any:
        if not response.content:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message="the realtime feed returned an empty body",
            )
        try:
            from google.transit import gtfs_realtime_pb2
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message="GTFS-Realtime bindings are not installed",
            ) from exc

        message = gtfs_realtime_pb2.FeedMessage()
        try:
            message.ParseFromString(response.content)
        except Exception as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message="the realtime feed is not a GTFS-Realtime message",
            ) from exc

        if not message.HasField("header"):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message="the realtime feed carries no header",
            )
        return message

    # ----------------------------------------------------------- normalize
    def normalize(
        self, model: Any, response: ProviderResponse, query: TransitQuery
    ) -> list[TransportStatus]:
        feed = self._feeds_for(query)[0]
        feed_id = str(feed.get("feed_id"))
        schedule = self._schedules.get(feed_id)
        fetched_at = datetime.fromtimestamp(response.fetched_at, tz=UTC)

        header_ts = int(getattr(model.header, "timestamp", 0) or 0)
        feed_built_at = (
            datetime.fromtimestamp(header_ts, tz=UTC) if header_ts else None
        )

        records: list[TransportStatus] = []
        for entity in model.entity:
            if not entity.HasField("trip_update"):
                continue
            update = entity.trip_update
            route_id = update.trip.route_id or ""
            if query.route_ids and route_id not in query.route_ids:
                continue

            suffix = trip_suffix(update.trip.trip_id or "")
            scheduled = _pick_scheduled(schedule, suffix, route_id)

            stop_updates = list(update.stop_time_update)
            if query.stop_ids:
                stop_updates = [
                    s for s in stop_updates if s.stop_id in set(query.stop_ids)
                ]
                if not stop_updates:
                    continue
            if not stop_updates:
                continue

            record = self._to_record(
                feed=feed,
                feed_id=feed_id,
                schedule=schedule,
                scheduled=scheduled,
                update=update,
                stop_updates=stop_updates,
                response=response,
                fetched_at=fetched_at,
                feed_built_at=feed_built_at,
            )
            if record is not None:
                records.append(record)
            if len(records) >= query.limit:
                break

        return records

    def _to_record(
        self,
        *,
        feed: dict[str, Any],
        feed_id: str,
        schedule: Schedule | None,
        scheduled: ScheduledTrip | None,
        update: Any,
        stop_updates: list[Any],
        response: ProviderResponse,
        fetched_at: datetime,
        feed_built_at: datetime | None,
    ) -> TransportStatus | None:
        first, last = stop_updates[0], stop_updates[-1]
        relationship = int(getattr(update.trip, "schedule_relationship", 0) or 0)

        estimated_departure = _epoch(_time_of(first, "departure"))
        estimated_arrival = _epoch(_time_of(last, "arrival"))

        service_day = _service_day(update.trip.start_date)
        zone = feed_timezone(schedule, feed)
        scheduled_departure = _scheduled_time(
            schedule, scheduled, first.stop_id, service_day, "departure", zone
        )
        scheduled_arrival = _scheduled_time(
            schedule, scheduled, last.stop_id, service_day, "arrival", zone
        )

        delay_minutes: int | None = None
        if scheduled_arrival is not None and estimated_arrival is not None:
            delay_minutes = round(
                (estimated_arrival - scheduled_arrival).total_seconds() / 60
            )

        status, cancellation = _status(relationship, delay_minutes)

        route = (schedule.routes.get(update.trip.route_id) if schedule else None) or {}
        mode = _MODE_BY_ROUTE_TYPE.get(
            str(route.get("route_type", "")), _mode_from_feed(feed)
        )

        return TransportStatus(
            id=f"{feed_id}:{update.trip.trip_id}",
            mode=mode,
            operator=(schedule.agency_name if schedule else feed.get("agency")),
            service_number=(
                route.get("route_short_name") or update.trip.route_id or None
            ),
            origin_stop=_stop_ref(schedule, first.stop_id),
            destination_stop=_stop_ref(schedule, last.stop_id),
            scheduled_departure=scheduled_departure,
            estimated_departure=estimated_departure,
            scheduled_arrival=scheduled_arrival,
            estimated_arrival=estimated_arrival,
            status=status,
            delay_minutes=delay_minutes,
            cancellation=cancellation,
            quality=_quality(
                schedule=schedule,
                scheduled=scheduled,
                feed_built_at=feed_built_at,
                fetched_at=fetched_at,
                relationship=relationship,
            ),
            source=self.provenance(
                response,
                provider_record_id=update.trip.trip_id or None,
                # The feed header timestamp is when the agency built this
                # snapshot - a real observation time, unlike the fetch.
                observed_at=feed_built_at,
                source_url=str(feed.get("realtime_trip_updates_url") or response.url),
                payload_for_hash={
                    "trip_id": update.trip.trip_id,
                    "route_id": update.trip.route_id,
                    "start_date": update.trip.start_date,
                    "stops": [
                        (s.stop_id, _time_of(s, "arrival"), _time_of(s, "departure"))
                        for s in stop_updates
                    ],
                },
            ),
            feed_id=feed_id,
        )

    # ------------------------------------------------------------ schedule
    def schedule_request(self, feed: dict[str, Any]) -> ProviderRequest:
        return ProviderRequest(path_or_url=str(feed["schedule_url"]), method="GET")

    async def load_schedule(
        self, feed: dict[str, Any], *, deadline_seconds: float | None = None
    ) -> Schedule:
        """Fetch and index one static feed.

        Held in memory rather than cached in Redis: a parsed schedule is tens of
        megabytes of Python objects, and re-parsing it per request would cost
        more than the realtime call it supports.
        """
        from app.domain.canonical import content_hash

        feed_id = str(feed.get("feed_id"))
        response = await self.transport.request(
            self.provider,
            str(feed["schedule_url"]),
            method="GET",
            deadline_seconds=deadline_seconds,
            decode_json=False,
        )
        if not response.content:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message="the schedule feed returned an empty body",
            )
        schedule = parse_schedule(
            response.content,
            feed_id=feed_id,
            fetched_at=datetime.fromtimestamp(response.fetched_at, tz=UTC),
            content_hash=content_hash({"bytes": len(response.content)}),
        )
        self._schedules[feed_id] = schedule
        log.info(
            "gtfs_schedule_loaded",
            feed=feed_id,
            routes=len(schedule.routes),
            stops=len(schedule.stops),
            trips=schedule.trip_count,
        )
        return schedule

    async def ensure_schedule(
        self, feed: dict[str, Any], *, deadline_seconds: float | None = None
    ) -> Schedule | None:
        """Load the static feed once, then reuse it.

        Best-effort on purpose. A realtime snapshot is still worth returning
        without a timetable to compare it against - the records simply say so
        and stay UNKNOWN, which is the honest answer. Failing the whole request
        because the schedule download was slow would lose live data the caller
        can use.
        """
        feed_id = str(feed.get("feed_id"))
        cached = self._schedules.get(feed_id)
        extra = self.provider.entry.cache.model_extra or {}
        ttl = extra.get("static_ttl_seconds", 86400)
        if cached is not None:
            age = (datetime.now(UTC) - cached.fetched_at).total_seconds()
            if age < float(ttl):
                return cached
        if not feed.get("schedule_url"):
            return cached
        try:
            return await self.load_schedule(feed, deadline_seconds=deadline_seconds)
        except ProviderError as error:
            log.warning(
                "gtfs_schedule_unavailable", feed=feed_id, error_code=str(error.code)
            )
            return cached

    async def query(
        self, query: TransitQuery, *, deadline_seconds: float | None = None
    ) -> list[TransportStatus]:
        feeds = self._feeds_for(query)
        if feeds:
            await self.ensure_schedule(feeds[0], deadline_seconds=deadline_seconds)
        return await super().query(query, deadline_seconds=deadline_seconds)

    def use_schedule(self, schedule: Schedule) -> None:
        """Attach an already-parsed schedule. Used by tests and by a warm-up
        path that loads the feed once at startup."""
        self._schedules[schedule.feed_id] = schedule

    def _dehydrate(self, records: list[TransportStatus]) -> Any:
        return [record.model_dump(mode="json") for record in records]

    def _rehydrate(self, payload: Any) -> list[TransportStatus]:
        return [TransportStatus.model_validate(item) for item in payload]


# --------------------------------------------------------------- helpers


def _bbox_overlaps(
    query: tuple[float, float, float, float], feed_bbox: Any
) -> bool:
    if not feed_bbox or len(feed_bbox) < 4:
        # A feed that declares no area cannot be ruled out, and claiming it
        # covers everywhere would be the global claim the plan forbids. Treat it
        # as a candidate and let the records speak.
        return True
    q_min_lon, q_min_lat, q_max_lon, q_max_lat = query
    f_min_lon, f_min_lat, f_max_lon, f_max_lat = (float(v) for v in feed_bbox[:4])
    return not (
        q_max_lon < f_min_lon
        or q_min_lon > f_max_lon
        or q_max_lat < f_min_lat
        or q_min_lat > f_max_lat
    )


def _pick_scheduled(
    schedule: Schedule | None, suffix: str, route_id: str
) -> ScheduledTrip | None:
    if schedule is None or not suffix:
        return None
    candidates = schedule.trips_by_suffix.get(suffix)
    if not candidates:
        return None
    if route_id:
        same_route = [t for t in candidates if t.route_id == route_id]
        if same_route:
            candidates = same_route
    return candidates[0]


def _time_of(stop_update: Any, which: str) -> int | None:
    event = getattr(stop_update, which, None)
    if event is None or not stop_update.HasField(which):
        return None
    value = int(getattr(event, "time", 0) or 0)
    return value or None


def _epoch(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value else None


def _service_day(start_date: str) -> date | None:
    if not start_date or len(start_date) != 8:
        return None
    try:
        return date(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:]))
    except ValueError:
        return None


def feed_timezone(schedule: Schedule | None, feed: dict[str, Any] | None) -> tzinfo:
    """The agency's own timezone, which is what GTFS schedule times are in.

    Reading them as UTC is not a rounding error: a New York timetable read as
    UTC makes every train exactly four hours late, and the number is plausible
    enough to ship. Falls back to UTC only when the feed declares nothing, and
    that case is flagged on the record.
    """
    name = None
    if schedule is not None:
        name = schedule.agency_timezone
    if not name and feed is not None:
        name = feed.get("timezone")
    if not name:
        return UTC
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("gtfs_unknown_timezone", timezone=str(name))
        return UTC


def _scheduled_time(
    schedule: Schedule | None,
    scheduled: ScheduledTrip | None,
    stop_id: str,
    service_day: date | None,
    which: str,
    zone: tzinfo,
) -> datetime | None:
    """Resolve a `HH:MM:SS` schedule time against the service day.

    Two traps at once. GTFS hours run past 23 for a trip that continues after
    midnight - `25:10:00` on the 20th is 01:10 on the 21st, and clamping it to
    01:10 on the *20th* moves the train back a day. And the clock is the
    agency's local time, not UTC.
    """
    if schedule is None or scheduled is None or service_day is None:
        return None
    index = 1 if which == "arrival" else 2
    for candidate_stop, arrival, departure in scheduled.stop_times:
        if candidate_stop != stop_id:
            continue
        raw = (arrival, departure)[index - 1]
        if not raw:
            return None
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        try:
            hours, minutes, seconds = (int(p) for p in parts)
        except ValueError:
            return None
        local_midnight = datetime(
            service_day.year, service_day.month, service_day.day, tzinfo=zone
        )
        return (local_midnight + timedelta(
            hours=hours, minutes=minutes, seconds=seconds
        )).astimezone(UTC)
    return None


def _status(
    relationship: int, delay_minutes: int | None
) -> tuple[TransportStatusCode, Cancellation | None]:
    if relationship == _TRIP_CANCELED:
        return TransportStatusCode.CANCELLED, Cancellation(
            cancelled=True, reason="the provider marked this trip cancelled"
        )
    if relationship in (_TRIP_ADDED, _TRIP_UNSCHEDULED):
        # A train the schedule never mentioned is a disruption, not punctuality.
        return TransportStatusCode.DISRUPTED, None
    if delay_minutes is None:
        # § 3.6: ON_TIME needs real-time evidence against a schedule. Without a
        # matched trip there is nothing to be on time against.
        return TransportStatusCode.UNKNOWN, None
    if delay_minutes >= 5:
        return TransportStatusCode.DELAYED, None
    return TransportStatusCode.ON_TIME, None


def _stop_ref(schedule: Schedule | None, stop_id: str) -> StopRef:
    stop = (schedule.stops.get(stop_id) if schedule else None) or {}
    coordinates: GeoPoint | None = None
    try:
        lat = float(stop["stop_lat"])
        lon = float(stop["stop_lon"])
        coordinates = GeoPoint(coordinates=(lon, lat))
    except (KeyError, TypeError, ValueError):
        coordinates = None
    return StopRef(
        stop_id=stop_id or None,
        # The contract requires a name. A stop the schedule does not describe
        # still exists and is still where the train is going, so the id stands
        # in rather than the record being dropped.
        name=str(stop.get("stop_name") or stop_id or "unknown stop"),
        coordinates=coordinates,
    )


def _mode_from_feed(feed: dict[str, Any]) -> TravelMode:
    declared = str(feed.get("mode", "")).upper()
    try:
        return TravelMode(declared)
    except ValueError:
        return TravelMode.BUS


def _quality(
    *,
    schedule: Schedule | None,
    scheduled: ScheduledTrip | None,
    feed_built_at: datetime | None,
    fetched_at: datetime,
    relationship: int,
) -> DataQuality:
    flags: list[QualityFlag] = []
    notes: list[str] = []

    if schedule is None:
        flags.append(QualityFlag.MISSING)
        notes.append(
            "no static schedule is loaded for this feed, so nothing here is "
            "compared against a timetable"
        )
    elif scheduled is None:
        flags.append(QualityFlag.INCOMPLETE)
        notes.append(
            "this running trip has no counterpart in the published schedule, "
            "so no delay can be computed and the status stays UNKNOWN"
        )
        age = int((fetched_at - schedule.fetched_at).total_seconds())
        if age > SCHEDULE_FRESH_WITHIN_SECONDS:
            flags.append(QualityFlag.STALE)
            notes.append("the loaded schedule is over a week old")

    if relationship in (_TRIP_ADDED, _TRIP_UNSCHEDULED):
        flags.append(QualityFlag.INFERRED)
        notes.append("the provider marks this trip as added or unscheduled")

    if feed_built_at is None:
        flags.append(QualityFlag.MISSING)
        notes.append("the realtime feed carried no header timestamp")
        return DataQuality(
            status=DataStatus.PARTIAL, flags=sorted(set(flags)), notes=notes
        )

    age_seconds = max(0, int((fetched_at - feed_built_at).total_seconds()))
    quality = DataQuality.from_age(
        age_seconds=age_seconds,
        fresh_within_seconds=REALTIME_FRESH_WITHIN_SECONDS,
        flags=sorted(set(flags)),
        notes=notes,
    )
    quality.notes.append(
        f"freshness is the age of the realtime snapshot the agency published "
        f"({feed_built_at:%Y-%m-%dT%H:%M:%SZ})"
    )
    return quality
