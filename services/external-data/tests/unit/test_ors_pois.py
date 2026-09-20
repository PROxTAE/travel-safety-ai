"""openrouteservice POIs adapter - the emergency directory.

The category ids under test were read from the provider's own category list,
not guessed. That matters: the first attempt used a plausible-looking group id
and a "nearest hospital" search came back with a pub 250 m away. The test at
the bottom of the coverage section is the one that would have caught it.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.adapters.ors_pois import (
    CATEGORY_BY_PLACE_TYPE,
    DEFAULT_PLACE_TYPES,
    MAX_RADIUS_M,
    OrsPoisAdapter,
)
from app.domain.enums import DataStatus, PlaceType, ProviderStatus, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import NearbyPlacesQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

POIS = "openrouteservice/pois_emergency_bangkok.json"
VICTORY_MONUMENT = (100.5383, 13.7649)


def _adapter() -> OrsPoisAdapter:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == "ors_pois")
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return OrsPoisAdapter(provider, ProviderTransport(Defaults()), env="test")


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://api.openrouteservice.org/pois",
        fetched_at=time.time(),
        elapsed_seconds=0.3,
    )


def _query(**overrides: Any) -> NearbyPlacesQuery:
    fields: dict[str, Any] = {
        "longitude": VICTORY_MONUMENT[0],
        "latitude": VICTORY_MONUMENT[1],
        "radius_m": 2000,
    }
    fields.update(overrides)
    return NearbyPlacesQuery(**fields)


def _places(**overrides: Any) -> list[Any]:
    adapter = _adapter()
    response = _response(load_fixture(POIS))
    return adapter.normalize(adapter.validate(response), response, _query(**overrides))


# ------------------------------------------------------------------ coverage


def test_a_radius_past_the_provider_limit_is_refused() -> None:
    decision = _adapter().coverage(_query(radius_m=MAX_RADIUS_M + 1))
    assert decision.supported is False


def test_a_sane_radius_is_supported() -> None:
    assert _adapter().coverage(_query(radius_m=1500)).supported is True


def test_every_place_type_has_a_provider_category() -> None:
    """A PlaceType with no category would silently search for nothing."""
    for place_type in PlaceType:
        if place_type is PlaceType.OTHER:
            continue
        assert place_type in CATEGORY_BY_PLACE_TYPE


def test_the_plan_defaults_are_police_hospital_embassy() -> None:
    """What the module plan actually asks this endpoint for."""
    assert set(DEFAULT_PLACE_TYPES) == {
        PlaceType.HOSPITAL,
        PlaceType.POLICE,
        PlaceType.EMBASSY,
    }


def test_hospital_maps_to_the_category_the_provider_publishes() -> None:
    """Read from the provider's own `{"request": "list"}` response.

    A wrong id here is not a visible failure: the call succeeds and returns
    confident, well-formed results for the wrong kind of place.
    """
    assert CATEGORY_BY_PLACE_TYPE[PlaceType.HOSPITAL] == 206
    assert CATEGORY_BY_PLACE_TYPE[PlaceType.POLICE] == 369
    assert CATEGORY_BY_PLACE_TYPE[PlaceType.EMBASSY] == 361


# ------------------------------------------------------------------- request


def test_the_request_asks_only_for_the_categories_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    request = _adapter().build_request(_query(place_types=[PlaceType.POLICE]))
    assert request.json_body["filters"]["category_ids"] == [369]


def test_no_requested_type_means_the_plan_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    request = _adapter().build_request(_query())
    assert sorted(request.json_body["filters"]["category_ids"]) == sorted(
        CATEGORY_BY_PLACE_TYPE[place_type] for place_type in DEFAULT_PLACE_TYPES
    )


def test_the_cache_key_does_not_carry_an_exact_coordinate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security invariant § 11: a full-precision coordinate identifies a person,
    and a cache key outlives the request."""
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    fields = _adapter().build_request(
        _query(longitude=100.538312, latitude=13.764987)
    ).cache_key_fields
    assert fields is not None
    assert fields["lon"] == 100.5383
    assert fields["lat"] == 13.765


def test_a_missing_key_is_an_auth_error() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _adapter().build_request(_query())
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_AUTH


# ----------------------------------------------------------------- normalize


def test_real_hospitals_and_police_come_back() -> None:
    places = _places()
    assert len(places) == 19
    kinds = {place.place_type for place in places}
    assert PlaceType.HOSPITAL in kinds
    assert PlaceType.POLICE in kinds


def test_coordinates_are_longitude_latitude() -> None:
    place = _places()[0]
    assert 100.0 < place.location.longitude < 101.0
    assert 13.0 < place.location.latitude < 14.0


def test_an_unnamed_place_is_kept_and_flagged_not_dropped() -> None:
    """A hospital that exists but is untagged is still worth showing."""
    unnamed = [place for place in _places() if place.name is None]
    assert unnamed
    for place in unnamed:
        assert QualityFlag.MISSING in place.quality.flags


def test_place_id_is_stable_and_traceable_to_openstreetmap() -> None:
    place = _places()[0]
    assert place.place_id.startswith("ors_pois:osm:")
    assert place.source.source_url is not None
    assert "openstreetmap.org" in place.source.source_url


def test_a_place_has_no_observation_time() -> None:
    """OpenStreetMap does not publish when a tag was last confirmed on the
    ground, so borrowing `fetched_at` would turn a fetch into a survey."""
    for place in _places():
        assert place.source.observed_at is None


def test_distance_is_the_provider_number_untouched() -> None:
    place = _places()[0]
    assert place.distance_m is not None
    assert place.distance_m > 0


def test_quality_is_partial_because_the_data_age_is_unknown() -> None:
    """The POI service reports no extract build date. FRESH would be a claim
    nobody measured."""
    for place in _places():
        assert place.quality.status is DataStatus.PARTIAL


def test_a_place_without_a_phone_number_says_so() -> None:
    """The shared context forbids presenting this as an official directory; a
    consumer needs to know the phone number is simply absent."""
    without_phone = [place for place in _places() if place.phone is None]
    assert without_phone
    for place in without_phone:
        assert QualityFlag.INCOMPLETE in place.quality.flags


def test_an_empty_result_is_an_empty_list_not_an_error() -> None:
    """Nothing tagged nearby is a coverage fact the caller needs, not a failure
    to retry - and emphatically not "no help nearby"."""
    payload = load_fixture(POIS)
    payload["features"] = []
    adapter = _adapter()
    response = _response(payload)
    assert adapter.normalize(adapter.validate(response), response, _query()) == []


def test_an_unknown_category_becomes_other_and_keeps_the_provider_name() -> None:
    payload = load_fixture(POIS)
    payload["features"][0]["properties"]["category_ids"] = {
        "9999": {"category_name": "pigeon_loft", "category_group": "other"}
    }
    adapter = _adapter()
    response = _response(payload)
    place = adapter.normalize(adapter.validate(response), response, _query())[0]
    assert place.place_type is PlaceType.OTHER
    assert place.provider_category == "pigeon_loft"
    assert QualityFlag.INFERRED in place.quality.flags


def test_embassies_are_flagged_as_unreliable() -> None:
    """The shared context calls them out specifically. A traveller acting on a
    stale embassy pin in an emergency is the failure this flag exists for."""
    payload = load_fixture(POIS)
    payload["features"][0]["properties"]["category_ids"] = {
        "361": {"category_name": "embassy", "category_group": "public_places"}
    }
    adapter = _adapter()
    response = _response(payload)
    place = adapter.normalize(adapter.validate(response), response, _query())[0]
    assert place.place_type is PlaceType.EMBASSY
    assert QualityFlag.STALE in place.quality.flags


def test_a_payload_that_is_not_a_feature_collection_is_a_schema_change() -> None:
    with pytest.raises(ProviderError) as excinfo:
        _adapter().validate(_response({"type": "Nope"}))
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED
