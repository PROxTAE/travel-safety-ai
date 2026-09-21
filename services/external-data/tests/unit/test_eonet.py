"""EONET normalization, driven by the captured real feed.

The headline trap is the track: `geometry` is a list of observations over time,
and the captured Typhoon Dujuan has 11 of them whose first and last points are
1,480 km apart, with intensity rising from 35 to 65 kts. Reading the first entry
reports where the storm was three days ago at the strength it had then, and
nothing about the result looks wrong.
"""

from __future__ import annotations

import copy
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.eonet import EonetAdapter, _to_point
from app.domain.enums import EventType, ProviderStatus, QualityFlag, Severity
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import DisasterQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

FIXTURE = "eonet/events.json"
STORM_INDEX = 2  # Typhoon Dujuan, the one event with a real track


@pytest.fixture
def adapter() -> EonetAdapter:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == "nasa_eonet")
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return EonetAdapter(provider, ProviderTransport(Defaults()))


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://eonet.gsfc.nasa.gov/api/v3/events",
        fetched_at=time.time(),
        elapsed_seconds=0.3,
    )


def _run(adapter: EonetAdapter, payload: Any, query: DisasterQuery | None = None) -> list[Any]:
    response = _response(payload)
    return adapter.normalize(adapter.validate(response), response, query or DisasterQuery())


def _storm(events: list[Any], raw: dict[str, Any]) -> Any:
    target = raw["events"][STORM_INDEX]["id"]
    return next(e for e in events if e.event_id.endswith(target))


# ------------------------------------------------------------- trap 1: track


def test_position_is_the_latest_observation_not_the_first(
    adapter: EonetAdapter,
) -> None:
    """1,480 km of difference between the two readings, on a live typhoon."""
    raw = load_fixture(FIXTURE)
    track = raw["events"][STORM_INDEX]["geometry"]
    assert len(track) == 11

    event = _storm(_run(adapter, raw), raw)

    assert event.geometry.longitude == pytest.approx(track[-1]["coordinates"][0])
    assert event.geometry.latitude == pytest.approx(track[-1]["coordinates"][1])
    assert event.geometry.longitude != pytest.approx(track[0]["coordinates"][0])


def test_magnitude_is_the_current_intensity_not_the_initial_one(
    adapter: EonetAdapter,
) -> None:
    """35 kts when first seen, 65 kts now. Reporting the first reading
    understates a strengthening storm by nearly half."""
    raw = load_fixture(FIXTURE)
    track = raw["events"][STORM_INDEX]["geometry"]
    event = _storm(_run(adapter, raw), raw)

    assert event.magnitude == track[-1]["magnitudeValue"]
    assert event.magnitude != track[0]["magnitudeValue"]


def test_effective_at_is_when_the_event_began(adapter: EonetAdapter) -> None:
    """The position is current, but the start time is the first observation —
    those are two different entries of the same track."""
    raw = load_fixture(FIXTURE)
    track = raw["events"][STORM_INDEX]["geometry"]
    event = _storm(_run(adapter, raw), raw)

    assert event.effective_at == datetime.fromisoformat(track[0]["date"].replace("Z", "+00:00"))
    assert event.source.observed_at == datetime.fromisoformat(
        track[-1]["date"].replace("Z", "+00:00")
    )
    assert event.source.observed_at > event.effective_at


def test_a_shuffled_track_is_still_read_in_time_order(
    adapter: EonetAdapter,
) -> None:
    """The feed happens to arrive sorted. Depending on that is one provider
    change away from reporting a storm's position backwards."""
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["events"][STORM_INDEX]["geometry"].reverse()

    event = _storm(_run(adapter, raw), raw)
    original = load_fixture(FIXTURE)["events"][STORM_INDEX]["geometry"]

    assert event.geometry.longitude == pytest.approx(original[-1]["coordinates"][0])
    assert event.effective_at == datetime.fromisoformat(original[0]["date"].replace("Z", "+00:00"))


def test_track_length_is_reported_in_quality(adapter: EonetAdapter) -> None:
    raw = load_fixture(FIXTURE)
    event = _storm(_run(adapter, raw), raw)
    assert any("11 observations" in note for note in event.quality.notes)


# -------------------------------------------------------- trap 2: closed=null


def test_a_null_closed_means_still_open(adapter: EonetAdapter) -> None:
    raw = load_fixture(FIXTURE)
    assert all(event["closed"] is None for event in raw["events"])
    assert all(event.ends_at is None for event in _run(adapter, raw))


def test_a_closed_event_carries_its_end_time(adapter: EonetAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["events"][0]["closed"] = "2026-09-18T00:00:00Z"
    event = _run(adapter, raw)[0]

    assert event.ends_at == datetime(2026, 9, 18, tzinfo=UTC)
    assert any("marked this event closed" in note for note in event.quality.notes)


# ------------------------------------------------------ trap 3: mixed units


def test_magnitude_units_are_recorded_as_not_comparable(
    adapter: EonetAdapter,
) -> None:
    """Acres for a fire, knots for a storm. Ranking one against the other is
    meaningless, so every record says which scale it is on."""
    raw = load_fixture(FIXTURE)
    events = _run(adapter, raw)

    units = {event.magnitude_unit for event in events}
    assert units == {"acres", "kts"}
    for event in events:
        assert any("only comparable within this event type" in note for note in event.quality.notes)


# --------------------------------------------------------- trap 4: polygons


def test_a_polygon_becomes_its_centroid_and_is_flagged(
    adapter: EonetAdapter,
) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["events"][0]["geometry"] = [
        {
            "date": "2026-09-16T00:00:00Z",
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [0.0, 2.0], [2.0, 2.0], [2.0, 0.0]]],
        }
    ]
    event = _run(adapter, raw)[0]

    assert event.geometry.longitude == pytest.approx(1.0)
    assert event.geometry.latitude == pytest.approx(1.0)
    assert QualityFlag.INFERRED in event.quality.flags
    assert any("centroid" in note for note in event.quality.notes)


def test_point_geometry_is_not_flagged_as_inferred(adapter: EonetAdapter) -> None:
    event = _run(adapter, load_fixture(FIXTURE))[0]
    assert QualityFlag.INFERRED not in event.quality.flags


def test_unusable_geometry_is_dropped_and_counted(adapter: EonetAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["events"][0]["geometry"] = []
    events = _run(adapter, raw)

    assert len(events) == len(raw["events"]) - 1
    assert any("no usable geometry" in note for note in events[0].quality.notes)


def test_to_point_handles_a_bare_point() -> None:
    from app.adapters.eonet import EonetGeometry

    entry = EonetGeometry(date="2026-09-16T00:00:00Z", type="Point", coordinates=[10.0, 20.0])
    assert _to_point(entry) == (10.0, 20.0, False)


# -------------------------------------------------------------- categories


def test_categories_map_to_canonical_types(adapter: EonetAdapter) -> None:
    raw = load_fixture(FIXTURE)
    events = _run(adapter, raw)
    types = {event.event_type for event in events}
    assert types == {EventType.WILDFIRE, EventType.STORM}


def test_an_unknown_category_becomes_other(adapter: EonetAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["events"][0]["categories"] = [{"id": "somethingNew", "title": "New"}]
    assert _run(adapter, raw)[0].event_type is EventType.OTHER


def test_a_specific_category_wins_over_a_generic_one(adapter: EonetAdapter) -> None:
    """An event tagged both 'manmade' and 'wildfires' is a wildfire; falling
    through to OTHER would lose that."""
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["events"][0]["categories"] = [
        {"id": "manmade", "title": "Manmade"},
        {"id": "wildfires", "title": "Wildfires"},
    ]
    assert _run(adapter, raw)[0].event_type is EventType.WILDFIRE


def test_requested_types_are_pushed_to_the_provider(adapter: EonetAdapter) -> None:
    request = adapter.build_request(
        DisasterQuery(event_types=[EventType.WILDFIRE, EventType.FLOOD])
    )
    assert request.params is not None
    assert set(request.params["category"].split(",")) == {"wildfires", "floods"}


def test_coverage_rejects_hazards_eonet_does_not_publish(
    adapter: EonetAdapter,
) -> None:
    assert adapter.coverage(DisasterQuery(event_types=[EventType.HEALTH])).supported is False


# ------------------------------------------------------- provider filtering


def test_bbox_is_pushed_in_the_providers_own_order(adapter: EonetAdapter) -> None:
    """EONET documents bbox as upper-left then lower-right, which is not
    GeoJSON order."""
    request = adapter.build_request(DisasterQuery(bbox=(100.0, 10.0, 150.0, 40.0)))
    assert request.params is not None
    assert request.params["bbox"] == "100.0,40.0,150.0,10.0"


def test_a_wrapping_bbox_is_not_pushed_to_the_provider(
    adapter: EonetAdapter,
) -> None:
    """A box crossing the antimeridian is two spans; the parameter takes one."""
    request = adapter.build_request(DisasterQuery(bbox=(170.0, -10.0, -170.0, 10.0)))
    assert request.params is not None
    assert "bbox" not in request.params


def test_provider_results_are_re_checked_against_the_bbox(
    adapter: EonetAdapter,
) -> None:
    """The provider filters, but a change in its behaviour must not widen our
    result set silently."""
    raw = load_fixture(FIXTURE)
    far_away = (0.0, 0.0, 1.0, 1.0)  # nowhere near any fixture event
    assert _run(adapter, raw, DisasterQuery(bbox=far_away)) == []


def test_a_past_window_asks_for_closed_events_too(adapter: EonetAdapter) -> None:
    request = adapter.build_request(DisasterQuery(start=datetime(2026, 9, 1, tzinfo=UTC)))
    assert request.params is not None
    assert request.params["status"] == "all"
    assert request.params["start"] == "2026-09-01"


def test_a_query_with_no_window_asks_for_open_events(adapter: EonetAdapter) -> None:
    request = adapter.build_request(DisasterQuery())
    assert request.params is not None
    assert request.params["status"] == "open"


# ------------------------------------------------------------------- shape


def test_severity_stays_unknown(adapter: EonetAdapter) -> None:
    assert _run(adapter, load_fixture(FIXTURE))[0].severity is Severity.UNKNOWN


def test_the_reporting_network_is_not_a_cross_reference_id(
    adapter: EonetAdapter,
) -> None:
    """IRWIN and JTWC are the agencies that reported an event, not identifiers
    of it. JTWC reports every typhoon, so matching on it groups every typhoon —
    which is what it did before this was split out."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    assert event.reporting_networks == [raw["events"][0]["sources"][0]["id"]]
    # EONET publishes no id for this event in another system.
    assert event.cross_reference_ids == []


def test_source_url_points_at_the_upstream_record(adapter: EonetAdapter) -> None:
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]
    assert event.source.source_url == raw["events"][0]["sources"][0]["url"]


def test_curation_lag_is_stated(adapter: EonetAdapter) -> None:
    """EONET is corroboration, not the first alert. Consumers should know."""
    event = _run(adapter, load_fixture(FIXTURE))[0]
    assert any("corroboration" in note for note in event.quality.notes)


def test_malformed_feed_is_a_schema_change(adapter: EonetAdapter) -> None:
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(_response({"events": [{"id": "x"}]}))  # no title
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_empty_feed_is_a_valid_answer(adapter: EonetAdapter) -> None:
    assert _run(adapter, {"events": []}) == []


def test_time_window_filters_events(adapter: EonetAdapter) -> None:
    raw = load_fixture(FIXTURE)
    cutoff = datetime(2026, 9, 16, 12, tzinfo=UTC)
    events = _run(adapter, raw, DisasterQuery(start=cutoff))

    assert events
    assert all(event.effective_at >= cutoff for event in events)
    assert len(events) < len(raw["events"])


def test_freshness_is_measured_from_the_latest_observation(
    adapter: EonetAdapter,
) -> None:
    """A three-day-old storm observed an hour ago is fresh data about an old
    event, not stale data."""
    raw = load_fixture(FIXTURE)
    event = _storm(_run(adapter, raw), raw)
    assert event.quality.freshness_seconds is not None
    age_from_start = (datetime.now(UTC) - event.effective_at).total_seconds()
    assert event.quality.freshness_seconds < age_from_start - timedelta(hours=12).total_seconds()
