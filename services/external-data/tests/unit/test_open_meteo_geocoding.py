"""Geocoding normalization, driven by the captured real response."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

from app.adapters.base import HealthRecorder
from app.adapters.open_meteo_geocoding import (
    GeocodeQuery,
    OpenMeteoGeocodingAdapter,
)
from app.domain.enums import HealthState, ProviderStatus, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

FIXTURE = "open_meteo_geocoding/search_bangkok.json"
GEOCODE_URL_PATH = "https://geocoding-api.open-meteo.com/v1/search"
QUERY = GeocodeQuery(name="Bangkok", count=3)


@pytest.fixture
def adapter() -> OpenMeteoGeocodingAdapter:
    entry = next(
        p for p in load_registry(REGISTRY_PATH).providers if p.id == "open_meteo_geocoding"
    )
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return OpenMeteoGeocodingAdapter(provider, ProviderTransport(Defaults()))


def _adapter_with(recorder: HealthRecorder) -> OpenMeteoGeocodingAdapter:
    entry = next(
        p for p in load_registry(REGISTRY_PATH).providers if p.id == "open_meteo_geocoding"
    )
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    defaults = Defaults()
    defaults.retry.initial_backoff_seconds = 0.001
    return OpenMeteoGeocodingAdapter(
        provider, ProviderTransport(defaults), health_recorder=recorder
    )


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://geocoding-api.open-meteo.com/v1/search?name=Bangkok",
        fetched_at=time.time(),
        elapsed_seconds=0.1,
    )


def test_coordinates_are_flipped_to_geojson_order(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    """The provider gives latitude/longitude as separate floats; every canonical
    coordinate in this project is [longitude, latitude]."""
    raw = load_fixture(FIXTURE)
    first = raw["results"][0]

    response = _response(raw)
    result = adapter.normalize(adapter.validate(response), response, QUERY)[0]

    longitude, latitude = result.location.coordinates.coordinates
    assert latitude == pytest.approx(first["latitude"])
    assert longitude == pytest.approx(first["longitude"])
    # Bangkok: latitude ~13.7, longitude ~100.5. A swap would put latitude at
    # 100.5, which is not a valid latitude at all.
    assert 0 < latitude < 30
    assert 90 < longitude < 110


def test_place_id_is_provider_scoped(adapter: OpenMeteoGeocodingAdapter) -> None:
    response = _response(load_fixture(FIXTURE))
    result = adapter.normalize(adapter.validate(response), response, QUERY)[0]
    assert result.location.place_id.startswith("open_meteo_geocoding:")


def test_display_name_is_composed_from_parts(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    response = _response(load_fixture(FIXTURE))
    result = adapter.normalize(adapter.validate(response), response, QUERY)[0]
    assert "Bangkok" in result.location.display_name
    assert not result.location.display_name.startswith(",")
    assert ", ," not in result.location.display_name


def test_country_code_is_iso_alpha2_uppercase(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    response = _response(load_fixture(FIXTURE))
    for result in adapter.normalize(adapter.validate(response), response, QUERY):
        code = result.location.country_code
        if code is not None:
            assert len(code) == 2
            assert code.isupper()


def test_observed_at_is_null_with_a_quality_flag(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    """A place-name index has no observation time. Copying fetched_at in would
    make a static record look freshly measured."""
    response = _response(load_fixture(FIXTURE))
    result = adapter.normalize(adapter.validate(response), response, QUERY)[0]

    assert result.source.observed_at is None
    assert QualityFlag.MISSING in result.quality.flags
    assert result.source.fetched_at is not None


def test_provenance_carries_licence_and_record_id(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    raw = load_fixture(FIXTURE)
    response = _response(raw)
    result = adapter.normalize(adapter.validate(response), response, QUERY)[0]

    assert result.source.provider == "open_meteo_geocoding"
    assert result.source.provider_record_id == str(raw["results"][0]["id"])
    assert result.source.license is not None
    assert result.source.expires_at is not None
    assert result.source.content_hash is not None


def test_module_04_never_marks_a_location_confirmed(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    response = _response(load_fixture(FIXTURE))
    for result in adapter.normalize(adapter.validate(response), response, QUERY):
        assert result.location.confirmed_by_user is False


def test_no_match_yields_an_empty_list_not_an_error(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    """The provider omits `results` entirely when nothing matches. That is a
    successful answer of "no such place", not a failure."""
    response = _response({"generationtime_ms": 0.2})
    assert adapter.normalize(adapter.validate(response), response, QUERY) == []


def test_missing_required_field_is_a_schema_change(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    response = _response({"results": [{"id": 1, "name": "X"}]})  # no coordinates
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(response)
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_unknown_extra_field_does_not_break_the_capability(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    """Providers add fields. Refusing an otherwise valid response over a new
    optional key would take geocoding down for no safety gain."""
    raw = load_fixture(FIXTURE)
    raw["results"][0]["some_new_field"] = {"nested": True}
    response = _response(raw)
    assert adapter.normalize(adapter.validate(response), response, QUERY)


def test_coverage_rejects_an_empty_search_term(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    assert adapter.coverage(GeocodeQuery(name="   ")).supported is False
    assert adapter.coverage(GeocodeQuery(name="Bangkok")).supported is True


def test_coverage_rejects_an_out_of_range_count(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    assert adapter.coverage(GeocodeQuery(name="X", count=0)).supported is False
    assert adapter.coverage(GeocodeQuery(name="X", count=999)).supported is False


def test_cache_key_normalises_the_search_term(
    adapter: OpenMeteoGeocodingAdapter,
) -> None:
    lower = adapter.build_request(GeocodeQuery(name=" bangkok "))
    upper = adapter.build_request(GeocodeQuery(name="BANGKOK"))
    assert lower.cache_key_fields == upper.cache_key_fields


def test_locale_changes_the_cache_key(adapter: OpenMeteoGeocodingAdapter) -> None:
    english = adapter.build_request(GeocodeQuery(name="Bangkok", language="en"))
    thai = adapter.build_request(GeocodeQuery(name="Bangkok", language="th"))
    assert english.cache_key_fields != thai.cache_key_fields


class _RecordingHealth:
    """Stand-in for ProviderRepository; records what the adapter observed."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail = fail

    async def upsert_health(self, **kwargs: object) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append(kwargs)


@respx.mock
async def test_a_successful_call_records_an_up_observation() -> None:
    """This is what turns the health endpoint from a restatement of config into
    a report of reality."""
    respx.get(GEOCODE_URL_PATH).mock(
        return_value=httpx.Response(200, json=load_fixture(FIXTURE))
    )
    recorder = _RecordingHealth()
    adapter = _adapter_with(recorder)

    await adapter.query(GeocodeQuery(name="Bangkok"))

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["provider_id"] == "open_meteo_geocoding"
    assert call["state"] is HealthState.UP
    assert isinstance(call["latency_ms"], int)


@respx.mock
async def test_a_provider_outage_records_down() -> None:
    respx.get(GEOCODE_URL_PATH).mock(return_value=httpx.Response(503))
    recorder = _RecordingHealth()
    adapter = _adapter_with(recorder)

    with pytest.raises(ProviderError):
        await adapter.query(GeocodeQuery(name="Bangkok"))

    assert recorder.calls[0]["state"] is HealthState.DOWN


@respx.mock
async def test_an_auth_failure_records_not_configured_not_down() -> None:
    """A 401 means our key is wrong, not that the provider is unhealthy."""
    respx.get(GEOCODE_URL_PATH).mock(return_value=httpx.Response(401))
    recorder = _RecordingHealth()
    adapter = _adapter_with(recorder)

    with pytest.raises(ProviderError):
        await adapter.query(GeocodeQuery(name="Bangkok"))

    assert recorder.calls[0]["state"] is HealthState.NOT_CONFIGURED


@respx.mock
async def test_a_failing_recorder_does_not_fail_the_request() -> None:
    """The observation is a side effect. Data that already arrived must still
    reach the caller when the database is unavailable."""
    respx.get(GEOCODE_URL_PATH).mock(
        return_value=httpx.Response(200, json=load_fixture(FIXTURE))
    )
    adapter = _adapter_with(_RecordingHealth(fail=True))

    assert await adapter.query(GeocodeQuery(name="Bangkok"))
