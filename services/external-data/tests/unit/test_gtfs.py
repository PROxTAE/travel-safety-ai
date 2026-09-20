"""GTFS / GTFS-Realtime adapter.

Every fixture here is real: a trimmed New York City subway schedule and one
untouched realtime protobuf message, both captured on 2026-09-20.

Most of this file exists because of one function. `trip_suffix` had to be
written three times before it matched anything, and **each wrong version failed
silently** — an unmatched trip is a perfectly valid record with no schedule
attached, so a broken join produces sixty-six healthy-looking records that all
say UNKNOWN. Nothing raises, nothing logs, and the endpoint returns 200.
"""

from __future__ import annotations

import time
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import pytest

from app.adapters.gtfs import (
    GtfsAdapter,
    Schedule,
    feed_timezone,
    parse_schedule,
    trip_suffix,
)
from app.domain.enums import (
    DataStatus,
    ProviderStatus,
    QualityFlag,
    TransportStatusCode,
    TravelMode,
)
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import TransitQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import FIXTURE_ROOT, REGISTRY_PATH

FIXTURES = FIXTURE_ROOT / "gtfs_mta"
STATIC = FIXTURES / "mta_subway_ace_static.zip"
REALTIME = FIXTURES / "mta_subway_ace_tripupdates.pb"

NEW_YORK = (-74.1, 40.6, -73.8, 40.9)
BANGKOK = (100.0, 13.0, 101.0, 14.0)


def _adapter(with_schedule: bool = True) -> GtfsAdapter:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == "gtfs_registry")
    provider = ResolvedProvider(entry=entry, effective_status=ProviderStatus.ACTIVE, base_url=None)
    adapter = GtfsAdapter(provider, ProviderTransport(Defaults()), env="test")
    if with_schedule:
        adapter.use_schedule(_schedule())
    return adapter


def _schedule(fetched_at: datetime | None = None) -> Schedule:
    return parse_schedule(
        STATIC.read_bytes(),
        feed_id="mta_nyct_subway",
        fetched_at=fetched_at or datetime.now(UTC),
        content_hash="sha256:" + "0" * 64,
    )


def _response(content: bytes | None = None) -> ProviderResponse:
    return ProviderResponse(
        payload=None,
        status_code=200,
        headers={},
        url="https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
        fetched_at=time.time(),
        elapsed_seconds=0.4,
        content=REALTIME.read_bytes() if content is None else content,
    )


def _records(adapter: GtfsAdapter | None = None, **kw: Any) -> list[Any]:
    adapter = adapter or _adapter()
    response = _response()
    query = TransitQuery(bbox=NEW_YORK, limit=100, **kw)
    return adapter.normalize(adapter.validate(response), response, query)


# ------------------------------------------------- the join that kept failing


def test_the_two_feeds_use_different_trip_id_forms() -> None:
    """The trap, stated as a fact about the data.

    A schedule id carries a service prefix the realtime feed never sends.
    """
    schedule_id = "BSP26GEN-A055-Sunday-00_051550_A..N54R"
    realtime_id = "051550_A..N54R"
    assert schedule_id != realtime_id
    assert trip_suffix(schedule_id) == trip_suffix(realtime_id)


def test_the_suffix_keeps_the_origin_time() -> None:
    """One wrong version took only the last segment, `A..N54R`, which is a path
    and not a trip. It matched nothing, and looked perfectly healthy."""
    assert trip_suffix("BSP26GEN-A055-Sunday-00_051550_A..N54R") == "051550_A..N54R"


def test_the_suffix_of_a_realtime_id_is_itself() -> None:
    """The other wrong version split on the first underscore. Right for the
    schedule id, wrong for the realtime one, which has only one."""
    assert trip_suffix("051550_A..N54R") == "051550_A..N54R"


def test_a_trip_id_with_no_underscore_survives() -> None:
    assert trip_suffix("PLAINTRIP") == "PLAINTRIP"


def test_the_join_actually_matches_live_trips() -> None:
    """The test that would have caught all three wrong versions.

    Not "does it run" but "did it find anything": a broken join returns the
    same number of records, all of them UNKNOWN.
    """
    records = _records()
    matched = [r for r in records if r.scheduled_arrival is not None]
    assert matched, "the schedule join matched nothing at all"
    assert len(matched) >= 10, f"only {len(matched)} of {len(records)} trips joined"


# ----------------------------------------------------------------- timezone


def test_schedule_times_are_read_in_the_agency_timezone() -> None:
    """GTFS clock times are local to the agency.

    Reading a New York timetable as UTC made every train exactly four hours
    late - a plausible-looking number that would have shipped.
    """
    records = [r for r in _records() if r.delay_minutes is not None]
    assert records
    for record in records:
        assert abs(record.delay_minutes) < 120, (
            f"delay of {record.delay_minutes} min looks like a timezone offset, " "not a delay"
        )


def test_the_feed_timezone_comes_from_the_agency() -> None:
    schedule = _schedule()
    zone = feed_timezone(schedule, None)
    assert str(zone) == "America/New_York"


def test_an_unknown_timezone_falls_back_to_utc() -> None:
    zone = feed_timezone(None, {"timezone": "Mars/Olympus_Mons"})
    assert zone is UTC


# ------------------------------------------------------------ safety of status


def test_a_trip_with_no_schedule_is_unknown_not_on_time() -> None:
    """Contract § 3.6: ON_TIME needs real-time evidence against a schedule.

    Two thirds of live trips have no published counterpart. Calling them
    ON_TIME would be inventing punctuality out of an absence.
    """
    unmatched = [r for r in _records() if r.scheduled_arrival is None]
    assert unmatched
    for record in unmatched:
        assert record.status is TransportStatusCode.UNKNOWN
        assert record.delay_minutes is None
        assert QualityFlag.INCOMPLETE in record.quality.flags


def test_on_time_always_carries_a_measured_delay() -> None:
    for record in _records():
        if record.status is TransportStatusCode.ON_TIME:
            assert record.delay_minutes is not None


def test_the_record_refuses_to_be_on_time_without_a_delay() -> None:
    """Belt and braces: the model itself rejects it, so no future adapter can
    quietly produce one."""
    from app.domain.canonical import DataQuality, SourceProvenance
    from app.domain.enums import SourceAuthority
    from app.domain.records import StopRef, TransportStatus

    with pytest.raises(ValueError, match="ON_TIME"):
        TransportStatus(
            id="x",
            mode=TravelMode.TRAIN,
            origin_stop=StopRef(name="A"),
            destination_stop=StopRef(name="B"),
            status=TransportStatusCode.ON_TIME,
            delay_minutes=None,
            quality=DataQuality(status=DataStatus.FRESH),
            source=SourceProvenance(
                source_id="x",
                provider="gtfs_registry",
                authority=SourceAuthority.OFFICIAL,
                observed_at=None,
            ),
        )


def test_a_delayed_trip_is_reported_as_delayed() -> None:
    delayed = [r for r in _records() if r.status is TransportStatusCode.DELAYED]
    assert delayed
    for record in delayed:
        assert record.delay_minutes is not None
        assert record.delay_minutes >= 5


# ------------------------------------------------------------------ coverage


def test_coverage_is_per_agency_and_never_global() -> None:
    decision = _adapter().coverage(TransitQuery(bbox=BANGKOK))
    assert decision.supported is False
    assert "never global" in (decision.reason or "")
    assert "mta_nyct_subway" in (decision.reason or "")


def test_the_registered_region_is_covered() -> None:
    assert _adapter().coverage(TransitQuery(bbox=NEW_YORK)).supported is True


def test_a_query_with_no_box_is_answered_by_the_registered_feed() -> None:
    assert _adapter().coverage(TransitQuery()).supported is True


# ----------------------------------------------------------------- schedule


def test_the_schedule_parses_into_its_indexes() -> None:
    schedule = _schedule()
    assert schedule.routes
    assert schedule.stops
    assert schedule.trip_count > 0
    assert schedule.agency_timezone == "America/New_York"


def test_a_schedule_missing_a_required_table_is_a_schema_change() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("agency.txt", "agency_name,agency_timezone\nx,UTC\n")
    with pytest.raises(ProviderError) as excinfo:
        parse_schedule(
            buffer.getvalue(),
            feed_id="f",
            fetched_at=datetime.now(UTC),
            content_hash="x",
        )
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_something_that_is_not_a_zip_is_a_schema_change() -> None:
    with pytest.raises(ProviderError) as excinfo:
        parse_schedule(b"not a zip", feed_id="f", fetched_at=datetime.now(UTC), content_hash="x")
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_no_schedule_at_all_still_returns_live_records() -> None:
    """A realtime snapshot is worth having without a timetable to compare it
    against. The records say so and stay UNKNOWN."""
    records = _records(_adapter(with_schedule=False))
    assert records
    for record in records:
        assert record.status is TransportStatusCode.UNKNOWN
        assert QualityFlag.MISSING in record.quality.flags


def test_a_week_old_schedule_is_flagged_stale() -> None:
    adapter = _adapter(with_schedule=False)
    adapter.use_schedule(_schedule(fetched_at=datetime.now(UTC) - timedelta(days=30)))
    unmatched = [r for r in _records(adapter) if r.scheduled_arrival is None]
    assert unmatched
    assert any(QualityFlag.STALE in r.quality.flags for r in unmatched)


# ------------------------------------------------------------- realtime feed


def test_a_body_that_is_not_protobuf_is_a_schema_change() -> None:
    adapter = _adapter()
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(_response(content=b"<html>maintenance</html>"))
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_an_empty_body_is_a_schema_change() -> None:
    adapter = _adapter()
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(_response(content=b""))
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_freshness_is_the_age_of_the_agency_snapshot() -> None:
    """Not the age of our fetch: the header timestamp is when the agency built
    the snapshot, which is a real observation time."""
    record = _records()[0]
    assert record.source.observed_at is not None
    assert record.quality.freshness_seconds is not None


def test_a_stale_snapshot_degrades_rather_than_being_served_as_current() -> None:
    """Shared context § 10 gives GTFS-RT ninety seconds. The captured snapshot
    is far older than that by the time any test runs."""
    record = _records()[0]
    assert record.quality.status is DataStatus.STALE


# ------------------------------------------------------------------ filtering


def test_filtering_by_route_returns_only_that_route() -> None:
    records = _records(route_ids=["A"])
    assert records
    assert {r.service_number for r in records} == {"A"}


def test_filtering_by_a_route_nobody_runs_returns_nothing_without_failing() -> None:
    assert _records(route_ids=["ZZZ"]) == []


def test_records_carry_the_feed_that_answered() -> None:
    for record in _records():
        assert record.feed_id == "mta_nyct_subway"


def test_every_record_carries_provenance_and_an_operator() -> None:
    for record in _records():
        assert record.source.provider == "gtfs_registry"
        assert record.source.content_hash is not None
        assert record.operator
        assert record.mode is TravelMode.TRAIN


def test_stops_keep_their_names_and_coordinates() -> None:
    named = [r for r in _records() if r.origin_stop.coordinates is not None]
    assert named
    for record in named:
        longitude, latitude = record.origin_stop.coordinates.coordinates
        assert -75.0 < longitude < -73.0
        assert 40.0 < latitude < 41.5
