"""GDACS normalization, driven by the captured real feed.

Each of the five traps in the adapter docstring gets a named test. They share a
shape: none of them raises, each one just produces a confident wrong answer —
an event seven hours off, a closed event shown as ongoing, a blank title, an
alert colour treated as a magnitude, or a depth parsed out of prose.
"""

from __future__ import annotations

import copy
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.gdacs import GdacsAdapter, _wire_bool
from app.domain.enums import EventType, ProviderStatus, QualityFlag, Severity
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import DisasterQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

FIXTURE = "gdacs/eventlist_eq.json"


@pytest.fixture
def adapter() -> GdacsAdapter:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == "gdacs")
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return GdacsAdapter(provider, ProviderTransport(Defaults()))


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
        fetched_at=time.time(),
        elapsed_seconds=0.4,
    )


def _run(adapter: GdacsAdapter, payload: Any, query: DisasterQuery | None = None) -> list[Any]:
    response = _response(payload)
    return adapter.normalize(adapter.validate(response), response, query or DisasterQuery())


# --------------------------------------------------------- trap 1: naive times


def test_naive_timestamps_are_read_as_utc(adapter: GdacsAdapter) -> None:
    """`fromdate` is `"2026-08-28T05:13:35"` with no offset. Parsed as local
    time it moves every event by the host offset — seven hours here."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    expected = datetime.fromisoformat(raw["features"][0]["properties"]["fromdate"]).replace(
        tzinfo=UTC
    )
    assert event.effective_at == expected
    assert event.effective_at.utcoffset() == timedelta(0)


def test_the_utc_assumption_is_recorded_not_hidden(adapter: GdacsAdapter) -> None:
    event = _run(adapter, load_fixture(FIXTURE))[0]
    assert QualityFlag.INFERRED in event.quality.flags
    assert any("no timezone offset" in note for note in event.quality.notes)


def test_published_at_comes_from_datemodified(adapter: GdacsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]
    expected = datetime.fromisoformat(raw["features"][0]["properties"]["datemodified"]).replace(
        tzinfo=UTC
    )
    assert event.source.published_at == expected


def test_an_unparseable_start_time_drops_the_event(adapter: GdacsAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["properties"]["fromdate"] = "not-a-date"
    events = _run(adapter, raw)

    assert len(events) == len(raw["features"]) - 1
    assert any("no usable geometry or start time" in n for n in events[0].quality.notes)


# ------------------------------------------------------- trap 2: string "false"


def test_wire_booleans_are_strings_not_booleans() -> None:
    """`bool("false")` is True. That one line is how a closed event gets
    presented to a traveller as ongoing."""
    assert _wire_bool("false") is False
    assert _wire_bool("true") is True
    assert _wire_bool("False") is False
    assert _wire_bool(None) is None
    assert bool("false") is True  # the mistake this guards against


def test_a_non_current_event_says_so(adapter: GdacsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    assert raw["features"][0]["properties"]["iscurrent"] == "false"
    event = _run(adapter, raw)[0]
    assert any("no longer current" in note for note in event.quality.notes)


def test_a_temporary_event_is_flagged(adapter: GdacsAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["properties"]["istemporary"] = "true"
    event = _run(adapter, raw)[0]

    assert QualityFlag.INFERRED in event.quality.flags
    assert any("subject to revision" in note for note in event.quality.notes)


# ------------------------------------------------------- trap 3: empty eventname


def test_title_falls_back_when_eventname_is_empty(adapter: GdacsAdapter) -> None:
    """`eventname` is empty on all 26 records in the captured feed."""
    raw = load_fixture(FIXTURE)
    assert all(f["properties"]["eventname"] == "" for f in raw["features"])

    events = _run(adapter, raw)
    assert all(event.title.strip() for event in events)
    assert events[0].title == raw["features"][0]["properties"]["name"]


def test_title_never_falls_back_to_an_empty_string(adapter: GdacsAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    for key in ("eventname", "name", "description"):
        raw["features"][0]["properties"][key] = ""
    event = _run(adapter, raw)[0]
    assert event.title.strip()


def test_html_description_is_never_used(adapter: GdacsAdapter) -> None:
    """`htmldescription` is markup; handing it to a consumer that renders HTML
    is how provider content becomes an injection vector."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    assert event.description == raw["features"][0]["properties"]["description"]
    assert "<" not in (event.description or "")


# -------------------------------------------------------- trap 4: alert vs mag


def test_alert_level_is_carried_raw_not_cast_to_severity(
    adapter: GdacsAdapter,
) -> None:
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    assert event.alert_level == raw["features"][0]["properties"]["alertlevel"]
    assert event.alert_level in {"Green", "Orange", "Red"}
    assert event.severity is Severity.UNKNOWN


def test_severity_value_and_unit_come_from_severitydata(
    adapter: GdacsAdapter,
) -> None:
    raw = load_fixture(FIXTURE)
    data = raw["features"][0]["properties"]["severitydata"]
    event = _run(adapter, raw)[0]

    assert event.magnitude == data["severity"]
    assert event.magnitude_unit == data["severityunit"]


def test_missing_severity_is_flagged(adapter: GdacsAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["properties"]["severitydata"] = None
    event = _run(adapter, raw)[0]

    assert event.magnitude is None
    assert QualityFlag.INCOMPLETE in event.quality.flags


# ----------------------------------------------------------- trap 5: prose depth


def test_depth_is_not_parsed_out_of_free_text(adapter: GdacsAdapter) -> None:
    """`severitytext` reads "Magnitude 5M, Depth:10km". A regex over prose is
    not something a safety decision should rest on, so the number is left
    unparsed and the text is passed through for a human."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    assert event.depth_km is None
    assert any("Depth:10km" in note for note in event.quality.notes)


# --------------------------------------------------------------- event types


def test_event_type_codes_are_mapped(adapter: GdacsAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    for feature, code in zip(raw["features"], ["TC", "FL", "VO", "WF"], strict=False):
        feature["properties"]["eventtype"] = code

    events = _run(adapter, raw)
    assert [e.event_type for e in events[:4]] == [
        EventType.CYCLONE,
        EventType.FLOOD,
        EventType.VOLCANO,
        EventType.WILDFIRE,
    ]


def test_an_unknown_hazard_code_becomes_other(adapter: GdacsAdapter) -> None:
    """A code we have never seen must not be guessed into a specific hazard."""
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["properties"]["eventtype"] = "XX"
    assert _run(adapter, raw)[0].event_type is EventType.OTHER


def test_drought_maps_to_other_because_the_enum_has_none(
    adapter: GdacsAdapter,
) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["properties"]["eventtype"] = "DR"
    assert _run(adapter, raw)[0].event_type is EventType.OTHER


def test_requested_types_are_pushed_to_the_provider(adapter: GdacsAdapter) -> None:
    """Hazard type is the one filter this endpoint is known to honour, so it is
    the one that should not be done client-side."""
    request = adapter.build_request(DisasterQuery(event_types=[EventType.FLOOD, EventType.CYCLONE]))
    assert request.params is not None
    assert set(request.params["eventlist"].split(",")) == {"FL", "TC"}


def test_no_requested_types_asks_for_everything(adapter: GdacsAdapter) -> None:
    request = adapter.build_request(DisasterQuery())
    assert request.params is not None
    assert "EQ" in request.params["eventlist"]
    assert "TC" in request.params["eventlist"]


def test_coverage_rejects_hazards_gdacs_does_not_publish(
    adapter: GdacsAdapter,
) -> None:
    decision = adapter.coverage(DisasterQuery(event_types=[EventType.TRANSPORT_CLOSURE]))
    assert decision.supported is False


def test_coverage_accepts_a_hazard_it_does_publish(adapter: GdacsAdapter) -> None:
    assert adapter.coverage(DisasterQuery(event_types=[EventType.FLOOD])).supported


# ---------------------------------------------------------------- filtering


def test_bbox_filters_client_side_and_says_so(adapter: GdacsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    first = raw["features"][0]["geometry"]["coordinates"]
    tight = (first[0] - 0.5, first[1] - 0.5, first[0] + 0.5, first[1] + 0.5)

    events = _run(adapter, raw, DisasterQuery(bbox=tight))

    assert events
    assert len(events) < len(raw["features"])
    assert QualityFlag.OUTSIDE_COVERAGE in events[0].quality.flags
    assert any("client-side" in note for note in events[0].quality.notes)


def test_bbox_across_the_antimeridian_is_handled(adapter: GdacsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    events = _run(adapter, raw, DisasterQuery(bbox=(170.0, -90.0, -170.0, 90.0)))
    pacific = [
        f
        for f in raw["features"]
        if f["geometry"]
        and (f["geometry"]["coordinates"][0] >= 170.0 or f["geometry"]["coordinates"][0] <= -170.0)
    ]
    assert len(events) == len(pacific)


def test_time_window_filters_events(adapter: GdacsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    starts = sorted(
        datetime.fromisoformat(f["properties"]["fromdate"]).replace(tzinfo=UTC)
        for f in raw["features"]
    )
    cutoff = starts[len(starts) // 2]

    events = _run(adapter, raw, DisasterQuery(start=cutoff))
    assert all(event.effective_at >= cutoff for event in events)


# ------------------------------------------------------------------- shape


def test_instantaneous_events_have_no_end(adapter: GdacsAdapter) -> None:
    """`todate` equals `fromdate` on every earthquake in the feed. Emitting an
    end equal to the start would claim the event "finished" at that instant."""
    raw = load_fixture(FIXTURE)
    assert (
        raw["features"][0]["properties"]["fromdate"] == raw["features"][0]["properties"]["todate"]
    )
    assert _run(adapter, raw)[0].ends_at is None


def test_a_real_end_time_is_preserved(adapter: GdacsAdapter) -> None:
    raw = copy.deepcopy(load_fixture(FIXTURE))
    raw["features"][0]["properties"]["todate"] = "2026-08-30T00:00:00"
    event = _run(adapter, raw)[0]

    assert event.ends_at == datetime(2026, 8, 30, tzinfo=UTC)
    assert event.ends_at > event.effective_at


def test_event_id_includes_the_episode(adapter: GdacsAdapter) -> None:
    """One GDACS event has many episodes; collapsing them would merge distinct
    updates of a moving storm into one record."""
    raw = load_fixture(FIXTURE)
    properties = raw["features"][0]["properties"]
    event = _run(adapter, raw)[0]

    assert event.event_id == f"gdacs:{properties['eventid']}:{properties['episodeid']}"


def test_glide_is_kept_for_cross_source_dedup(adapter: GdacsAdapter) -> None:
    """GLIDE is an international identifier shared across agencies, so it is the
    strongest key module 05 has for matching this event against USGS."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]
    assert raw["features"][0]["properties"]["glide"] in event.cross_reference_ids


def test_the_reporting_network_is_not_a_cross_reference_id(
    adapter: GdacsAdapter,
) -> None:
    """`source` is the agency that reported the event - NEIC, JTWC - and it is
    shared by every event that agency publishes. Putting it in
    cross_reference_ids made unrelated storms match each other."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    assert event.reporting_networks == [raw["features"][0]["properties"]["source"]]
    assert all("network:" not in value for value in event.cross_reference_ids)


def test_the_episode_is_its_own_field_not_a_cross_reference(
    adapter: GdacsAdapter,
) -> None:
    """An episode number is an index within one event, not an id of it."""
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]

    assert event.episode_id == str(raw["features"][0]["properties"]["episodeid"])
    assert all("episode:" not in value for value in event.cross_reference_ids)


def test_cross_reference_ids_hold_only_event_identifiers(
    adapter: GdacsAdapter,
) -> None:
    """Every value here must name one specific event. A namespaced tag is a
    category, and categories match far too much."""
    for event in _run(adapter, load_fixture(FIXTURE)):
        for value in event.cross_reference_ids:
            assert ":" not in value or value.count("-") >= 2, value


def test_source_url_is_the_human_report_page(adapter: GdacsAdapter) -> None:
    raw = load_fixture(FIXTURE)
    event = _run(adapter, raw)[0]
    assert event.source.source_url == raw["features"][0]["properties"]["url"]["report"]
    assert event.official is True


def test_authority_is_intergovernmental(adapter: GdacsAdapter) -> None:
    event = _run(adapter, load_fixture(FIXTURE))[0]
    assert str(event.source.authority) == "INTERGOVERNMENTAL"


def test_malformed_feed_is_a_schema_change(adapter: GdacsAdapter) -> None:
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(_response({"features": [{"properties": {"eventid": 1}}]}))
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_empty_feed_is_a_valid_answer(adapter: GdacsAdapter) -> None:
    assert _run(adapter, {"type": "FeatureCollection", "features": []}) == []
