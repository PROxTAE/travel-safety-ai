"""USGS normalization, driven by the captured real feed.

The four traps in the adapter docstring each get a named test, because each one
produces a wrong answer that looks entirely reasonable: a quake in 1970, a
three-number "point", a silently global result set, or an impact alert
presented as a magnitude.
"""

from __future__ import annotations

import copy
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.usgs import UsgsAdapter
from app.domain.enums import EventType, ProviderStatus, QualityFlag, Severity
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import DisasterQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

FIXTURE = "usgs/significant_month.json"


@pytest.fixture
def adapter() -> UsgsAdapter:
    entry = next(
        p for p in load_registry(REGISTRY_PATH).providers if p.id == "usgs_earthquake"
    )
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return UsgsAdapter(provider, ProviderTransport(Defaults()))


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
        fetched_at=time.time(),
        elapsed_seconds=0.3,
    )


def _run(
    adapter: UsgsAdapter, payload: Any, query: DisasterQuery | None = None
) -> list[Any]:
    response = _response(payload)
    return adapter.normalize(
        adapter.validate(response), response, query or DisasterQuery()
    )


# ------------------------------------------------------------- trap 1: epoch ms


def test_epoch_milliseconds_become_the_right_year(adapter: UsgsAdapter) -> None:
    """`properties.time` is milliseconds. Reading it as seconds puts every
    earthquake in January 1970 - which looks like very stale data rather than
    like a bug."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    expected = datetime.fromtimestamp(
        raw["features"][0]["properties"]["time"] / 1000.0, tz=UTC
    )
    assert event.effective_at == expected
    assert event.effective_at.year >= 2020
    assert event.effective_at.tzinfo is not None


def test_published_at_uses_the_updated_timestamp(adapter: UsgsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]
    expected = datetime.fromtimestamp(
        raw["features"][0]["properties"]["updated"] / 1000.0, tz=UTC
    )
    assert event.source.published_at == expected


def test_observed_at_is_the_real_event_time(adapter: UsgsAdapter) -> None:
    """Unlike a forecast, an earthquake has a genuine observation time — so
    here `observed_at` must be set, not null."""
    event = _run(adapter, load_fixture(FIXTURE))[0]
    assert event.source.observed_at == event.effective_at
    assert event.source.observed_at != event.source.fetched_at


# ---------------------------------------------------------- trap 2: 3 ordinates


def test_three_ordinate_point_becomes_a_two_ordinate_point(
    adapter: UsgsAdapter,
) -> None:
    raw = load_fixture(FIXTURE)
    first = raw["features"][0]
    event = _run(adapter, raw)[0]

    assert len(event.geometry.coordinates) == 2
    assert event.geometry.longitude == pytest.approx(first["geometry"]["coordinates"][0])
    assert event.geometry.latitude == pytest.approx(first["geometry"]["coordinates"][1])


def test_depth_is_kept_as_an_attribute_not_discarded(adapter: UsgsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]
    assert event.depth_km == pytest.approx(raw["features"][0]["geometry"]["coordinates"][2])


def test_a_feature_without_geometry_is_dropped_and_counted(
    adapter: UsgsAdapter,
) -> None:
    """An event with no location cannot be intersected with a route, but losing
    one silently would understate the hazard count."""
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["geometry"] = None
    events = _run(adapter, raw)

    assert len(events) == len(raw["features"]) - 1
    assert any("no usable geometry" in note for note in events[0].quality.notes)


# ------------------------------------------------------ trap 3: client filtering


def test_bbox_filters_client_side_and_says_so(adapter: UsgsAdapter) -> None:
    """The summary feeds take no bbox, so the filtering is ours. A consumer has
    to know the set is complete only for the feed window."""
    raw = load_fixture(FIXTURE)
    first = raw["features"][0]["geometry"]["coordinates"]
    tight = (first[0] - 0.5, first[1] - 0.5, first[0] + 0.5, first[1] + 0.5)

    events = _run(adapter, raw, DisasterQuery(bbox=tight))

    assert len(events) < len(raw["features"])
    assert events
    assert QualityFlag.OUTSIDE_COVERAGE in events[0].quality.flags
    assert any("client-side" in note for note in events[0].quality.notes)


def test_bbox_across_the_antimeridian_is_not_empty(adapter: UsgsAdapter) -> None:
    """A box from +170 to -170 wraps the dateline; treated as min<=x<=max it is
    empty, which would silently hide every hazard in the Pacific."""
    raw = load_fixture(FIXTURE)
    wrapping = (170.0, -90.0, -170.0, 90.0)
    events = _run(adapter, raw, DisasterQuery(bbox=wrapping))

    pacific = [
        f
        for f in raw["features"]
        if f["geometry"]
        and (
            f["geometry"]["coordinates"][0] >= 170.0
            or f["geometry"]["coordinates"][0] <= -170.0
        )
    ]
    assert len(events) == len(pacific)
    assert events, "the fixture should contain at least one event near the dateline"


def test_time_window_filters_events(adapter: UsgsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    times = sorted(f["properties"]["time"] for f in raw["features"])
    cutoff = datetime.fromtimestamp(times[len(times) // 2] / 1000.0, tz=UTC)

    events = _run(adapter, raw, DisasterQuery(start=cutoff))
    assert all(event.effective_at >= cutoff for event in events)
    assert len(events) < len(raw["features"])


def test_no_filter_returns_the_whole_feed(adapter: UsgsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    assert len(_run(adapter, raw)) == len(raw["features"])


# -------------------------------------------------- trap 4: magnitude vs alert


def test_severity_is_not_derived_from_magnitude_or_alert(
    adapter: UsgsAdapter,
) -> None:
    """Q2/Q3 are unanswered. Magnitude is physics, PAGER alert is impact, and
    they disagree; picking either here would be a silent policy decision."""
    event = _run(adapter, load_fixture(FIXTURE))[0]
    assert event.severity is Severity.UNKNOWN


def test_provider_numbers_are_carried_through(adapter: UsgsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    properties = raw["features"][0]["properties"]
    event = _run(adapter, raw)[0]

    assert event.magnitude == properties["mag"]
    assert event.magnitude_unit == properties["magType"]
    assert event.alert_level == properties["alert"]  # raw 'green', not a Severity
    assert event.tsunami is bool(properties["tsunami"])


def test_missing_magnitude_is_flagged_not_zeroed(adapter: UsgsAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["properties"]["mag"] = None
    event = _run(adapter, raw)[0]

    assert event.magnitude is None
    assert QualityFlag.INCOMPLETE in event.quality.flags


# -------------------------------------------------------------------- dedup


def test_cross_network_ids_are_kept_for_dedup(adapter: UsgsAdapter) -> None:
    """`ids` is the comma-wrapped list of the same quake in other networks, and
    it is what makes cross-source dedup possible in module 05."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    assert event.cross_reference_ids
    assert "" not in event.cross_reference_ids
    assert raw["features"][0]["id"] not in event.cross_reference_ids
    assert all("," not in value for value in event.cross_reference_ids)


def test_event_id_is_provider_scoped(adapter: UsgsAdapter) -> None:
    event = _run(adapter, load_fixture(FIXTURE))[0]
    assert event.event_id.startswith("usgs_earthquake:")


def test_source_url_points_at_the_provider_record(adapter: UsgsAdapter) -> None:
    """The safety map has to be able to open the official page for an event."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]
    assert event.source.source_url == raw["features"][0]["properties"]["url"]
    assert event.official is True


# ------------------------------------------------------------ feed selection


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(minutes=30), "hour"),
        (timedelta(hours=5), "day"),
        (timedelta(days=3), "week"),
        (timedelta(days=20), "month"),
        (timedelta(days=200), "month"),
    ],
)
def test_feed_window_follows_the_requested_age(
    adapter: UsgsAdapter, age: timedelta, expected: str
) -> None:
    request = adapter.build_request(DisasterQuery(start=datetime.now(UTC) - age))
    assert f"_{expected}.geojson" in request.path_or_url


def test_min_magnitude_uses_a_provider_published_tier(adapter: UsgsAdapter) -> None:
    """The provider publishes these tiers itself, so honouring the caller's
    threshold does not require module 04 to invent one."""
    assert "4.5_" in adapter.build_request(DisasterQuery(min_magnitude=5.0)).path_or_url
    assert "2.5_" in adapter.build_request(DisasterQuery(min_magnitude=3.0)).path_or_url
    assert "all_" in adapter.build_request(DisasterQuery()).path_or_url


def test_bbox_is_part_of_the_cache_key(adapter: UsgsAdapter) -> None:
    """The feed is global and filtering happens after the fetch, so a narrow
    query must not be answered from a wide query's cached result."""
    wide = adapter.build_request(DisasterQuery())
    narrow = adapter.build_request(DisasterQuery(bbox=(0.0, 0.0, 1.0, 1.0)))
    assert wide.cache_key_fields != narrow.cache_key_fields


# ---------------------------------------------------------------- coverage


def test_coverage_rejects_a_query_for_other_hazards_only(
    adapter: UsgsAdapter,
) -> None:
    decision = adapter.coverage(DisasterQuery(event_types=[EventType.FLOOD]))
    assert decision.supported is False
    assert decision.reason is not None and "earthquake" in decision.reason.lower()


def test_coverage_accepts_an_earthquake_request(adapter: UsgsAdapter) -> None:
    assert adapter.coverage(DisasterQuery(event_types=[EventType.EARTHQUAKE])).supported


def test_coverage_rejects_an_inverted_bbox(adapter: UsgsAdapter) -> None:
    assert adapter.coverage(DisasterQuery(bbox=(0.0, 10.0, 1.0, 5.0))).supported is False


def test_malformed_feed_is_a_schema_change(adapter: UsgsAdapter) -> None:
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(_response({"features": [{"id": "x"}]}))  # no properties
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_empty_feed_is_a_valid_answer(adapter: UsgsAdapter) -> None:
    """No earthquakes in the window is a real answer, not a failure."""
    assert _run(adapter, {"type": "FeatureCollection", "features": []}) == []


def test_feed_url_uses_only_the_origin_from_the_configured_url(
    adapter: UsgsAdapter,
) -> None:
    """`USGS_FEED_URL` is configured as a complete feed URL, not an origin —
    that is what `.env.example` gives every module. Joining a path onto it
    duplicates the whole path, producing `.../all_day.geojson/earthquakes/...`
    which 404s."""
    request = adapter.build_request(DisasterQuery())
    transport = adapter.transport

    resolved = transport.build_url(adapter.provider, request.path_or_url)

    assert resolved == (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    )
    assert resolved.count("/earthquakes/feed/") == 1
