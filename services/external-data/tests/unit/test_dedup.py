"""Cross-source duplicate grouping.

The rule this file protects: grouping must never remove anything. Module 05
decides which record of a duplicate pair to believe, and it cannot decide about
records it never received.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.canonical import DataQuality, SourceProvenance
from app.domain.enums import DataStatus, EventType, SourceAuthority
from app.domain.records import DisasterEvent, GeoPoint
from app.services.dedup import PROXIMITY_KM, find_duplicate_groups

BASE_TIME = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def _event(
    *,
    provider: str,
    record_id: str,
    latitude: float = 13.0,
    longitude: float = 100.0,
    minutes: float = 0.0,
    event_type: EventType = EventType.EARTHQUAKE,
    cross_ids: list[str] | None = None,
    authority: SourceAuthority = SourceAuthority.OFFICIAL,
) -> DisasterEvent:
    return DisasterEvent(
        event_id=f"{provider}:{record_id}",
        event_type=event_type,
        title="test event",
        geometry=GeoPoint.from_lat_lon(latitude, longitude),
        effective_at=BASE_TIME + timedelta(minutes=minutes),
        official=True,
        cross_reference_ids=cross_ids or [],
        quality=DataQuality(status=DataStatus.FRESH),
        source=SourceProvenance(
            source_id=f"{provider}:{record_id}",
            provider=provider,
            provider_record_id=record_id,
            authority=authority,
        ),
    )


def test_nothing_is_grouped_when_there_is_nothing_to_group() -> None:
    assert find_duplicate_groups([]) == []
    assert find_duplicate_groups([_event(provider="usgs_earthquake", record_id="a")]) == []


def test_a_shared_cross_reference_id_groups_two_sources() -> None:
    """GDACS carries the GLIDE number; USGS carries its network ids. When one
    appears in the other, that is the same real-world event."""
    usgs = _event(provider="usgs_earthquake", record_id="us7000", cross_ids=["ak123"])
    gdacs = _event(
        provider="gdacs", record_id="1562260", cross_ids=["us7000", "EQ-2026-000168"]
    )

    groups = find_duplicate_groups([usgs, gdacs])

    assert len(groups) == 1
    assert set(groups[0].event_ids) == {usgs.event_id, gdacs.event_id}
    assert groups[0].basis == "shared_identifier"
    assert groups[0].providers == ["gdacs", "usgs_earthquake"]


def test_proximity_groups_the_same_quake_located_differently() -> None:
    """Two networks rarely agree on an epicentre to the metre."""
    usgs = _event(provider="usgs_earthquake", record_id="a", latitude=13.0)
    gdacs = _event(provider="gdacs", record_id="b", latitude=13.2, minutes=3)

    groups = find_duplicate_groups([usgs, gdacs])

    assert len(groups) == 1
    assert groups[0].basis == "proximity"


def test_a_shared_identifier_outranks_proximity_as_the_basis() -> None:
    """The caller should be told the stronger reason when both apply."""
    usgs = _event(provider="usgs_earthquake", record_id="a", cross_ids=["shared"])
    gdacs = _event(provider="gdacs", record_id="b", cross_ids=["shared"], minutes=1)

    assert find_duplicate_groups([usgs, gdacs])[0].basis == "shared_identifier"


def test_distant_events_are_not_grouped() -> None:
    near = _event(provider="usgs_earthquake", record_id="a", latitude=13.0)
    far = _event(provider="gdacs", record_id="b", latitude=40.0)
    assert find_duplicate_groups([near, far]) == []


def test_events_far_apart_in_time_are_not_grouped() -> None:
    first = _event(provider="usgs_earthquake", record_id="a")
    later = _event(provider="gdacs", record_id="b", minutes=180)
    assert find_duplicate_groups([first, later]) == []


def test_different_hazard_types_are_never_grouped_by_proximity() -> None:
    """A flood and an earthquake in the same valley on the same day are two
    events, however close together they are."""
    quake = _event(provider="usgs_earthquake", record_id="a")
    flood = _event(provider="gdacs", record_id="b", event_type=EventType.FLOOD)
    assert find_duplicate_groups([quake, flood]) == []


def test_two_records_from_one_source_are_left_alone() -> None:
    """A source's own catalogue is its own business - an aftershock sequence is
    not a set of duplicates."""
    first = _event(provider="usgs_earthquake", record_id="a")
    second = _event(provider="usgs_earthquake", record_id="b", minutes=2)
    assert find_duplicate_groups([first, second]) == []


def test_three_sources_collapse_into_one_group() -> None:
    usgs = _event(provider="usgs_earthquake", record_id="us1", cross_ids=["glide-1"])
    gdacs = _event(provider="gdacs", record_id="g1", cross_ids=["glide-1"], minutes=1)
    eonet = _event(provider="nasa_eonet", record_id="e1", latitude=13.1, minutes=2)

    groups = find_duplicate_groups([usgs, gdacs, eonet])

    assert len(groups) == 1
    assert len(groups[0].event_ids) == 3
    assert groups[0].providers == ["gdacs", "nasa_eonet", "usgs_earthquake"]


def test_authorities_are_reported_without_being_ranked() -> None:
    """Module 04 supplies the metadata; module 05 does the prioritising."""
    usgs = _event(
        provider="usgs_earthquake",
        record_id="a",
        cross_ids=["x"],
        authority=SourceAuthority.OFFICIAL,
    )
    gdacs = _event(
        provider="gdacs",
        record_id="b",
        cross_ids=["x"],
        authority=SourceAuthority.INTERGOVERNMENTAL,
    )

    group = find_duplicate_groups([usgs, gdacs])[0]
    assert group.authorities == ["INTERGOVERNMENTAL", "OFFICIAL"]


def test_grouping_never_removes_or_modifies_an_event() -> None:
    """The whole point. The caller emits every event either way."""
    events = [
        _event(provider="usgs_earthquake", record_id="a", cross_ids=["x"]),
        _event(provider="gdacs", record_id="b", cross_ids=["x"]),
        _event(provider="nasa_eonet", record_id="c", latitude=45.0),
    ]
    before = [event.model_copy(deep=True) for event in events]

    find_duplicate_groups(events)

    assert events == before
    assert len(events) == 3


def test_just_inside_and_just_outside_the_distance_threshold() -> None:
    """One degree of latitude is about 111 km, so this brackets the boundary
    rather than guessing at it."""
    origin = _event(provider="usgs_earthquake", record_id="a", latitude=0.0)
    inside = _event(
        provider="gdacs", record_id="b", latitude=(PROXIMITY_KM - 20) / 111.0
    )
    outside = _event(
        provider="gdacs", record_id="c", latitude=(PROXIMITY_KM + 40) / 111.0
    )

    assert find_duplicate_groups([origin, inside])
    assert find_duplicate_groups([origin, outside]) == []


def test_an_empty_cross_reference_is_not_a_match() -> None:
    """Two events that both carry a blank id are not thereby the same event."""
    first = _event(provider="usgs_earthquake", record_id="a", cross_ids=["", "  "])
    second = _event(
        provider="gdacs", record_id="b", cross_ids=["", "  "], latitude=40.0
    )
    assert find_duplicate_groups([first, second]) == []


# --------------------------------- finding E from the PR #10 review ----------


def test_a_shared_reporting_network_does_not_group_unrelated_storms() -> None:
    """The regression this guard exists for.

    JTWC reports every typhoon in the basin. When `network:JTWC` sat in
    cross_reference_ids it appeared in 297 of 568 events in the reviewer's live
    run, and union-find chained seventeen storms — months apart, opposite
    hemispheres — into one group labelled `shared_identifier`. Module 05 could
    then have kept one record and silently dropped a typhoon heading for
    Thailand, which is the exact failure this module exists to prevent.
    """
    dujuan = _event(
        provider="nasa_eonet",
        record_id="EONET_24317",
        latitude=26.2,
        longitude=139.7,
        event_type=EventType.STORM,
        cross_ids=["network:JTWC"],
    )
    noul = _event(
        provider="gdacs",
        record_id="1010203",
        latitude=-15.0,
        longitude=-142.0,
        minutes=60 * 24 * 40,  # six weeks earlier
        event_type=EventType.STORM,
        cross_ids=["network:JTWC"],
    )

    assert find_duplicate_groups([dujuan, noul]) == []


def test_a_shared_episode_number_does_not_group_anything() -> None:
    """An episode index is a position inside one event, and every storm has an
    episode 3."""
    first = _event(provider="gdacs", record_id="a", cross_ids=["episode:3"])
    second = _event(
        provider="nasa_eonet", record_id="b", latitude=60.0, cross_ids=["episode:3"]
    )
    assert find_duplicate_groups([first, second]) == []


def test_a_real_shared_identifier_still_groups() -> None:
    """The guard must not throw out what it is there to protect."""
    usgs = _event(
        provider="usgs_earthquake",
        record_id="us7000",
        cross_ids=["EQ-2026-000168-CHN", "network:NEIC"],
    )
    gdacs = _event(
        provider="gdacs",
        record_id="1562260",
        cross_ids=["EQ-2026-000168-CHN"],
        minutes=2,
    )

    groups = find_duplicate_groups([usgs, gdacs])

    assert len(groups) == 1
    assert groups[0].basis == "shared_identifier"


def test_many_storms_sharing_one_network_stay_separate() -> None:
    """Scaled-up version of the live failure: without the guard these collapse
    into a single seventeen-member group."""
    storms = [
        _event(
            provider="nasa_eonet" if index % 2 else "gdacs",
            record_id=f"s{index}",
            latitude=-60.0 + index * 7.0,
            longitude=-170.0 + index * 20.0,
            minutes=index * 60 * 24 * 5,
            event_type=EventType.STORM,
            cross_ids=["network:JTWC"],
        )
        for index in range(17)
    ]

    assert find_duplicate_groups(storms) == []
