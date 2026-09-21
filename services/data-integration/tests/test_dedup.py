"""Dedup fixtures derive from the USGS HTTP 200 public capture in module 04.

Source: external-data/tests/fixtures/real-sanitized/usgs/significant_month.json,
captured 2026-09-19T07:45:38Z, event us7000ti1p. Mutations exercise matching rules.
"""

import copy

from app.pipeline.dedup import candidate_groups, candidate_links, exact_clusters, resolve_field


def captured_event() -> dict:
    return {
        "event_id": "us7000ti1p",
        "cross_reference_ids": [],
        "effective_at": "2026-09-17T14:19:52.210Z",
        "canonical_geometry": {"type": "Point", "coordinates": [-171.3756, 52.8594]},
        "official": True,
        "severity": "UNKNOWN",
        "magnitude": 6.5,
        "source": {
            "source_id": "usgs:us7000ti1p",
            "provider": "usgs",
            "provider_record_id": "us7000ti1p",
            "published_at": "2026-09-18T14:29:54.553Z",
            "fetched_at": "2026-09-19T07:45:38Z",
            "authority": "OFFICIAL",
        },
    }


def test_provider_version_is_exact_and_preserves_both_sources() -> None:
    first = captured_event()
    repeat = copy.deepcopy(first)
    repeat["source"]["source_id"] = "usgs:us7000ti1p:refetch"
    records = [first, repeat]
    links = candidate_links(records, max_distance_m=1000, max_time_seconds=3600)
    assert links[0].reason == "PROVIDER_VERSION"
    assert links[0].mergeable
    cluster = exact_clusters(records, links)[0]
    assert cluster.members == (0, 1)
    assert len(cluster.source_ids) == 2


def test_provider_update_is_retained_as_a_distinct_version() -> None:
    first = captured_event()
    update = copy.deepcopy(first)
    update["source"]["published_at"] = "2026-09-19T08:00:00Z"
    links = candidate_links([first, update], max_distance_m=1000, max_time_seconds=3600)
    assert links[0].reason == "PROVIDER_UPDATE"
    assert not links[0].mergeable
    assert len(exact_clusters([first, update], links)) == 2


def test_cross_reference_links_events_without_losing_official_evidence() -> None:
    official = captured_event()
    other = copy.deepcopy(official)
    other["event_id"] = "other-network-event"
    other["cross_reference_ids"] = ["us7000ti1p"]
    other["official"] = False
    other["source"] = {
        **other["source"],
        "source_id": "other:one",
        "provider": "other",
        "provider_record_id": "one",
    }
    links = candidate_links([official, other], max_distance_m=0, max_time_seconds=0)
    assert links[0].reason == "CROSS_REFERENCE"
    assert exact_clusters([official, other], links)[0].source_ids == (
        "usgs:us7000ti1p",
        "other:one",
    )


def test_nearby_events_are_candidates_only() -> None:
    official = captured_event()
    nearby = copy.deepcopy(official)
    nearby["event_id"] = "distinct-event"
    nearby["cross_reference_ids"] = []
    nearby["source"] = {
        **nearby["source"],
        "source_id": "community:one",
        "provider": "community",
        "provider_record_id": "one",
    }
    links = candidate_links([official, nearby], max_distance_m=1000, max_time_seconds=3600)
    assert links[0].reason == "SPATIAL_TEMPORAL"
    assert not links[0].mergeable
    assert len(exact_clusters([official, nearby], links)) == 2
    assert candidate_groups(2, links) == [(0, 1)]


def test_safety_conflict_keeps_all_evidence_and_prefers_official_source() -> None:
    official = captured_event()
    official["severity"] = "SEVERE"
    community = copy.deepcopy(official)
    community["severity"] = "MINOR"
    community["official"] = False
    community["source"] = {
        **community["source"],
        "source_id": "community:one",
        "provider": "community",
        "authority": "COMMUNITY",
    }
    result = resolve_field([community, official], "severity")
    assert result.selected_value == "SEVERE"
    assert result.selected_source_id == "usgs:us7000ti1p"
    assert result.status == "CONFLICTING"
    assert result.reason == "UNRESOLVED_SAFETY_CONFLICT"
    assert {item.value for item in result.evidence} == {"SEVERE", "MINOR"}


def test_agreement_and_missing_values_are_distinct() -> None:
    first = captured_event()
    second = copy.deepcopy(first)
    second["source"]["source_id"] = "usgs:refetch"
    assert resolve_field([first, second], "magnitude").reason == "SOURCE_AGREEMENT"
    assert resolve_field([first, second], "missing_field").status == "UNAVAILABLE"
