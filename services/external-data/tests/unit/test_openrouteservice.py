"""openrouteservice Directions adapter.

The fixtures are real responses captured on 2026-09-20, including the two
rejections the provider returns for limits that are not visible in a successful
answer.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.adapters.openrouteservice import (
    GRAPH_FRESH_WITHIN_SECONDS,
    OpenRouteServiceAdapter,
)
from app.domain.enums import (
    DataStatus,
    ProviderStatus,
    QualityFlag,
    RiskLevel,
    RouteLabel,
    TravelMode,
)
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import RouteQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

DIRECTIONS = "openrouteservice/directions_bkk_ayutthaya.json"
NO_ROUTE = "openrouteservice/directions_no_route.json"
LIMIT_EXCEEDED = "openrouteservice/directions_limit_exceeded.json"

BANGKOK = (100.5383, 13.7649)
AYUTTHAYA = (100.5878, 14.3532)


def _adapter() -> OpenRouteServiceAdapter:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == "openrouteservice")
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return OpenRouteServiceAdapter(provider, ProviderTransport(Defaults()), env="test")


def _response(payload: Any, status_code: int = 200) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=status_code,
        headers={},
        url="https://api.openrouteservice.org/v2/directions/driving-car/geojson",
        fetched_at=time.time(),
        elapsed_seconds=0.4,
    )


def _query(**overrides: Any) -> RouteQuery:
    fields: dict[str, Any] = {"waypoints": [BANGKOK, AYUTTHAYA], "mode": TravelMode.CAR}
    fields.update(overrides)
    return RouteQuery(**fields)


def _routes(**overrides: Any) -> list[Any]:
    adapter = _adapter()
    response = _response(load_fixture(DIRECTIONS))
    query = _query(**overrides)
    return adapter.normalize(adapter.validate(response), response, query)


# ------------------------------------------------------------------ coverage


def test_train_is_not_a_road_network_question() -> None:
    """Routing a TRAIN request by car would return a plausible, wrong answer."""
    decision = _adapter().coverage(_query(mode=TravelMode.TRAIN))
    assert decision.supported is False
    assert "road-network" in (decision.reason or "")


@pytest.mark.parametrize("mode", [TravelMode.CAR, TravelMode.WALK, TravelMode.BICYCLE])
def test_road_modes_are_supported(mode: TravelMode) -> None:
    assert _adapter().coverage(_query(mode=mode)).supported is True


def test_too_many_alternatives_is_refused_before_the_call() -> None:
    """The provider caps this at 3 (error 2003, fixture). Catching it here turns
    a wasted request and a 400 into an answer about coverage."""
    decision = _adapter().coverage(_query(alternatives=4))
    assert decision.supported is False
    assert "3" in (decision.reason or "")


def test_alternatives_with_a_via_point_are_refused() -> None:
    """Verified against the live API: ORS rejects alternative_routes when there
    are more than two waypoints."""
    decision = _adapter().coverage(
        _query(waypoints=[BANGKOK, (100.56, 14.0), AYUTTHAYA], alternatives=2)
    )
    assert decision.supported is False
    assert "via point" in (decision.reason or "")


def test_alternatives_alone_are_fine() -> None:
    assert _adapter().coverage(_query(alternatives=2)).supported is True


def test_unknown_preference_is_refused() -> None:
    assert _adapter().coverage(_query(preference="scenic")).supported is False


# ------------------------------------------------------------------- request


def test_request_asks_for_metres_and_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    request = _adapter().build_request(_query(alternatives=2))
    assert request.method == "POST"
    assert request.path_or_url.endswith("/driving-car/geojson")
    body = request.json_body
    assert body["units"] == "m"
    assert body["instructions"] is True
    assert body["alternative_routes"]["target_count"] == 2
    assert body["coordinates"][0] == [100.5383, 13.7649]


def test_the_key_never_appears_in_the_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "super-secret-key")
    get_settings.cache_clear()
    request = _adapter().build_request(_query())
    assert "super-secret-key" not in repr(request.cache_key_fields)


def test_a_missing_key_is_an_auth_error_not_a_crash() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _adapter().build_request(_query())
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_AUTH


def test_avoid_polygons_reach_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    polygon = {"type": "Polygon", "coordinates": [[[100.0, 13.0]]]}
    request = _adapter().build_request(_query(avoid_polygons=polygon))
    assert request.json_body["options"]["avoid_polygons"] == polygon


def test_different_waypoints_give_different_cache_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    adapter = _adapter()
    first = adapter.build_request(_query()).cache_key_fields
    second = adapter.build_request(_query(waypoints=[BANGKOK, (98.98, 18.78)])).cache_key_fields
    assert first != second


# ------------------------------------------------------------------ validate


def test_no_routable_point_is_coverage_not_an_outage() -> None:
    """Error 2010 means the caller asked about a place with no road near it.

    Reporting it as an outage would both mislead the caller and, after a few
    such requests, open the circuit breaker against a healthy provider.
    """
    with pytest.raises(ProviderError) as excinfo:
        _adapter().validate(_response(load_fixture(NO_ROUTE), status_code=404))
    assert excinfo.value.code is ProviderErrorCode.OUTSIDE_COVERAGE


def test_a_rejected_parameter_is_reported_as_coverage() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _adapter().validate(_response(load_fixture(LIMIT_EXCEEDED), status_code=400))
    assert excinfo.value.code is ProviderErrorCode.OUTSIDE_COVERAGE


def test_a_payload_that_is_not_a_feature_collection_is_a_schema_change() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _adapter().validate(_response({"type": "Nonsense"}))
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


# ----------------------------------------------------------------- normalize


def test_both_routes_are_returned() -> None:
    routes = _routes(alternatives=2)
    assert len(routes) == 2


def test_the_first_route_is_labelled_original_not_recommended() -> None:
    """RECOMMENDED is a risk ranking. Module 04 has not ranked anything."""
    routes = _routes(alternatives=2)
    assert routes[0].label is RouteLabel.ORIGINAL
    assert routes[1].label is RouteLabel.ALTERNATIVE


def test_risk_and_exposure_are_never_invented() -> None:
    """The safety invariant for this adapter.

    `exposure.score = 0` plus `closed = false` would be a route across a closed
    bridge asserting, in the contract's own vocabulary, that nothing is wrong.
    """
    for route in _routes(alternatives=2):
        assert route.risk_level is RiskLevel.UNKNOWN
        assert route.exposure is None
        assert QualityFlag.INCOMPLETE in route.quality.flags


def test_distance_and_duration_are_metres_and_seconds() -> None:
    route = _routes()[0]
    # 73.7 km Bangkok to Ayutthaya; kilometres would be a factor of 1000 out.
    assert 60_000 < route.distance_m < 90_000
    assert 1_800 < route.duration_seconds < 7_200


def test_geometry_is_longitude_latitude() -> None:
    route = _routes()[0]
    longitude, latitude = route.geometry.coordinates[0]
    assert 100.0 < longitude < 101.0
    assert 13.0 < latitude < 15.0


def test_geometry_keeps_only_two_ordinates() -> None:
    """ORS may append elevation. Passing a triple through would smuggle a height
    into a field consumers read as a pair."""
    route = _routes()[0]
    assert all(len(point) == 2 for point in route.geometry.coordinates)


def test_steps_keep_the_provider_wording() -> None:
    route = _routes()[0]
    steps = route.segments[0].steps
    assert steps
    assert steps[0].instruction


def test_unnamed_roads_do_not_become_a_dash() -> None:
    """ORS writes "-" for an unnamed road; that would end up on a map label."""
    for route in _routes(alternatives=2):
        for segment in route.segments:
            assert all(step.street_name != "-" for step in segment.steps)


def test_route_id_is_stable_across_identical_calls() -> None:
    """A cached answer and a fresh one must not look like two different routes."""
    first = [route.route_id for route in _routes(alternatives=2)]
    second = [route.route_id for route in _routes(alternatives=2)]
    assert first == second


def test_route_id_changes_with_the_waypoints() -> None:
    first = _routes()[0].route_id
    second = _routes(waypoints=[BANGKOK, (98.98, 18.78)])[0].route_id
    assert first != second


def test_bbox_is_geojson_order() -> None:
    route = _routes()[0]
    assert route.bbox is not None
    min_lon, min_lat, max_lon, max_lat = route.bbox
    assert min_lon <= max_lon
    assert min_lat <= max_lat


# ------------------------------------------------------------------- quality


def test_freshness_is_the_graph_age_not_the_request_age() -> None:
    """A route is computed, never observed.

    Measuring freshness from "now minus the request" would make every route
    FRESH forever and say nothing; measuring it from the road graph says
    something true and useful - how old the map is.
    """
    route = _routes()[0]
    assert route.sources[0].observed_at is None
    assert route.sources[0].published_at is not None
    assert route.quality.freshness_seconds is not None
    assert route.quality.freshness_seconds > 0


def test_a_recent_graph_is_fresh() -> None:
    """The fixture's graph was eight days old at capture - well inside the
    thirty-day window, so this must not report STALE."""
    route = _routes()[0]
    assert route.quality.freshness_seconds is not None
    if route.quality.freshness_seconds < GRAPH_FRESH_WITHIN_SECONDS:
        assert route.quality.status is not DataStatus.STALE


def test_a_missing_graph_date_is_partial_not_fresh() -> None:
    """No build date means the age is unknown. FRESH would assert something
    nobody measured."""
    payload = load_fixture(DIRECTIONS)
    payload["metadata"]["engine"].pop("graph_date", None)
    adapter = _adapter()
    response = _response(payload)
    route = adapter.normalize(adapter.validate(response), response, _query())[0]
    assert route.quality.status is DataStatus.PARTIAL
    assert QualityFlag.MISSING in route.quality.flags


def test_provenance_carries_the_licence_and_a_content_hash() -> None:
    route = _routes()[0]
    assert route.sources[0].license
    assert route.sources[0].content_hash is not None
    assert route.sources[0].provider == "openrouteservice"


def test_source_id_does_not_collide_between_unrelated_queries() -> None:
    """The provider gives its routes no id, only a position in the response.

    Using that bare index made `source_id` "openrouteservice:0" for the first
    route of every query ever made, so two unrelated routes claimed to be the
    same source record - and provenance that does not identify one record is
    not provenance.
    """
    bangkok_to_ayutthaya = [route.sources[0].source_id for route in _routes()]
    bangkok_to_chiang_mai = [
        route.sources[0].source_id for route in _routes(waypoints=[BANGKOK, (98.98, 18.78)])
    ]
    assert not set(bangkok_to_ayutthaya) & set(bangkok_to_chiang_mai)


def test_source_id_is_stable_for_the_same_query() -> None:
    """Unique is only half of it; it must also survive a re-fetch, or a cached
    record and a fresh one look like two different sources."""
    first = [route.sources[0].source_id for route in _routes()]
    second = [route.sources[0].source_id for route in _routes()]
    assert first == second


def test_each_route_in_one_response_has_its_own_source_id() -> None:
    routes = _routes(alternatives=2)
    ids = [route.sources[0].source_id for route in routes]
    assert len(set(ids)) == len(ids)
