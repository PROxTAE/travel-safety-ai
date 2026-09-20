"""Weather normalization: time zone, column layout, batching and ETA alignment.

Every test here is driven by a captured real response. The three traps in the
adapter docstring are each covered by a named test, because each one produces a
plausible-looking wrong answer rather than a crash.
"""

from __future__ import annotations

import copy
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.open_meteo_weather import (
    MAX_SAMPLES_PER_REQUEST,
    CoordinateSample,
    OpenMeteoWeatherAdapter,
    WeatherQuery,
)
from app.domain.enums import ProviderStatus, QualityFlag, Severity
from app.domain.errors import ProviderError, ProviderErrorCode
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

SINGLE = "open_meteo_weather/forecast_bangkok.json"
BATCHED = "open_meteo_weather/forecast_batched.json"


@pytest.fixture
def adapter() -> OpenMeteoWeatherAdapter:
    entry = next(
        p for p in load_registry(REGISTRY_PATH).providers if p.id == "open_meteo_forecast"
    )
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return OpenMeteoWeatherAdapter(provider, ProviderTransport(Defaults()))


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://api.open-meteo.com/v1/forecast",
        fetched_at=time.time(),
        elapsed_seconds=0.2,
    )


def _run(
    adapter: OpenMeteoWeatherAdapter, payload: Any, query: WeatherQuery
) -> list[Any]:
    response = _response(payload)
    return adapter.normalize(adapter.validate(response), response, query)


def _sample(lat: float = 13.7563, lon: float = 100.5018, **kw: Any) -> CoordinateSample:
    return CoordinateSample(latitude=lat, longitude=lon, **kw)


# ------------------------------------------------------------------ trap 1: tz


def test_times_are_parsed_as_utc(adapter: OpenMeteoWeatherAdapter) -> None:
    """The provider returns "2026-09-19T00:00" with no suffix even under
    timezone=UTC. Parsing that as naive local time shifts every forecast by the
    host offset - on this team's machines, by seven hours."""
    raw = load_fixture(SINGLE)
    points = _run(adapter, raw, WeatherQuery(samples=[_sample()]))

    assert points
    for point in points:
        assert point.valid_at.tzinfo is not None
        assert point.valid_at.utcoffset() == timedelta(0)

    assert points[0].valid_at.isoformat().startswith(raw["hourly"]["time"][0])


def test_provider_ignoring_utc_is_a_schema_change(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    raw = copy.deepcopy(load_fixture(SINGLE))
    raw["utc_offset_seconds"] = 25200  # Asia/Bangkok
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(_response(raw))
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


# -------------------------------------------------------------- trap 2: layout


def test_column_arrays_become_one_point_per_hour(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    raw = load_fixture(SINGLE)
    points = _run(adapter, raw, WeatherQuery(samples=[_sample()]))
    assert len(points) == len(raw["hourly"]["time"])


def test_ragged_columns_are_a_schema_change(adapter: OpenMeteoWeatherAdapter) -> None:
    """A short column is not a partial result - it means the rows no longer line
    up, so every value after the gap would be attributed to the wrong hour."""
    raw = copy.deepcopy(load_fixture(SINGLE))
    raw["hourly"]["temperature_2m"] = raw["hourly"]["temperature_2m"][:5]
    with pytest.raises(ProviderError) as excinfo:
        adapter.validate(_response(raw))
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_values_land_in_the_right_canonical_field(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    raw = load_fixture(SINGLE)
    hourly = raw["hourly"]
    point = _run(adapter, raw, WeatherQuery(samples=[_sample()]))[0]

    assert point.temperature_c == hourly["temperature_2m"][0]
    assert point.apparent_temperature_c == hourly["apparent_temperature"][0]
    assert point.precipitation_mm == hourly["precipitation"][0]
    assert point.precipitation_probability == hourly["precipitation_probability"][0]
    assert point.snowfall_cm == hourly["snowfall"][0]
    assert point.wind_speed_kmh == hourly["wind_speed_10m"][0]
    assert point.wind_gust_kmh == hourly["wind_gusts_10m"][0]
    assert point.visibility_m == hourly["visibility"][0]
    assert point.weather_code == hourly["weather_code"][0]


def test_a_null_measurement_stays_null(adapter: OpenMeteoWeatherAdapter) -> None:
    """Substituting 0 would read as "no rain" instead of "unknown"."""
    raw = copy.deepcopy(load_fixture(SINGLE))
    raw["hourly"]["precipitation"][0] = None
    point = _run(adapter, raw, WeatherQuery(samples=[_sample()]))[0]
    assert point.precipitation_mm is None


def test_unit_drift_is_recorded_not_raised(adapter: OpenMeteoWeatherAdapter) -> None:
    raw = copy.deepcopy(load_fixture(SINGLE))
    raw["hourly_units"]["temperature_2m"] = "°F"
    point = _run(adapter, raw, WeatherQuery(samples=[_sample()]))[0]

    assert QualityFlag.CONFLICTING in point.quality.flags
    assert any("expected °C" in note for note in point.quality.notes)


# ------------------------------------------------------------- trap 3: batching


def test_batched_response_maps_to_samples_by_position(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    """A batched response is an array with no id field, so position is the only
    link back to the request. Getting this wrong hands Chiang Mai's weather to
    someone in Bangkok."""
    raw = load_fixture(BATCHED)
    bangkok = _sample(13.7563, 100.5018, sample_id="bkk")
    chiang_mai = _sample(18.7883, 98.9853, sample_id="cnx")

    points = _run(adapter, raw, WeatherQuery(samples=[bangkok, chiang_mai]))

    bkk = [p for p in points if p.sample_id == "bkk"]
    cnx = [p for p in points if p.sample_id == "cnx"]
    assert bkk and cnx
    assert bkk[0].location.latitude == pytest.approx(raw[0]["latitude"])
    assert cnx[0].location.latitude == pytest.approx(raw[1]["latitude"])
    assert bkk[0].location.latitude < cnx[0].location.latitude  # Bangkok is south


def test_entry_count_mismatch_is_a_schema_change(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    raw = load_fixture(BATCHED)[:1]  # asked for two points, got one back
    with pytest.raises(ProviderError) as excinfo:
        _run(
            adapter,
            raw,
            WeatherQuery(samples=[_sample(), _sample(18.7883, 98.9853)]),
        )
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED


def test_single_coordinate_object_and_batched_array_both_parse(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    assert len(adapter.validate(_response(load_fixture(SINGLE)))) == 1
    assert len(adapter.validate(_response(load_fixture(BATCHED)))) == 2


# ---------------------------------------------------------------- ETA alignment


def test_eta_selects_a_single_nearest_hour(adapter: OpenMeteoWeatherAdapter) -> None:
    raw = load_fixture(SINGLE)
    target = datetime.fromisoformat(raw["hourly"]["time"][5]).replace(tzinfo=UTC)
    eta = target + timedelta(minutes=12)

    points = _run(adapter, raw, WeatherQuery(samples=[_sample(eta=eta)]))

    assert len(points) == 1
    assert points[0].valid_at == target
    assert points[0].eta_offset_seconds == -12 * 60


def test_a_far_eta_offset_is_flagged(adapter: OpenMeteoWeatherAdapter) -> None:
    """Half an hour either side is the honest limit of an hourly forecast."""
    raw = load_fixture(SINGLE)
    last = datetime.fromisoformat(raw["hourly"]["time"][-1]).replace(tzinfo=UTC)
    points = _run(
        adapter, raw, WeatherQuery(samples=[_sample(eta=last + timedelta(hours=6))])
    )

    assert QualityFlag.INFERRED in points[0].quality.flags
    assert any("from the supplied ETA" in note for note in points[0].quality.notes)


def test_no_eta_returns_every_hour_in_the_window(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    raw = load_fixture(SINGLE)
    start = datetime.fromisoformat(raw["hourly"]["time"][2]).replace(tzinfo=UTC)
    end = datetime.fromisoformat(raw["hourly"]["time"][6]).replace(tzinfo=UTC)

    points = _run(adapter, raw, WeatherQuery(samples=[_sample()], start=start, end=end))

    assert len(points) == 5
    assert all(start <= point.valid_at <= end for point in points)


# ------------------------------------------------------------------- sampling


def test_a_long_route_is_downsampled_evenly_not_truncated(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    """Keeping only the first ten points reports nothing about the half of the
    route the traveller has not driven yet."""
    from app.adapters.open_meteo_weather import _select_samples

    samples = [_sample(lat=float(i), sample_id=str(i)) for i in range(50)]
    selected = _select_samples(samples)

    assert len(selected) == MAX_SAMPLES_PER_REQUEST
    assert selected[0].sample_id == "0"
    assert selected[-1].sample_id == "49"  # the far end survives


def test_downsampling_lowers_coverage_and_flags_it(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    raw = load_fixture(BATCHED)
    # 20 requested, 10 sent, but the fixture only holds 2 entries - build a
    # matching payload so the position check passes.
    payload = [copy.deepcopy(raw[0]) for _ in range(MAX_SAMPLES_PER_REQUEST)]
    samples = [_sample(lat=13.0 + i * 0.1, sample_id=str(i)) for i in range(20)]

    points = _run(adapter, payload, WeatherQuery(samples=samples))

    assert points[0].quality.coverage == pytest.approx(0.5)
    assert QualityFlag.INCOMPLETE in points[0].quality.flags


def test_grid_offset_is_recorded(adapter: OpenMeteoWeatherAdapter) -> None:
    """The returned coordinate is the model cell, not the requested point."""
    raw = load_fixture(SINGLE)
    point = _run(adapter, raw, WeatherQuery(samples=[_sample()]))[0]
    assert any("model grid cell" in note for note in point.quality.notes)


# --------------------------------------------------------------- provenance


def test_forecast_has_no_observation_time(adapter: OpenMeteoWeatherAdapter) -> None:
    """Model output is not a measurement. This is the single most dangerous
    thing to get wrong in this module."""
    point = _run(adapter, load_fixture(SINGLE), WeatherQuery(samples=[_sample()]))[0]
    assert point.source.observed_at is None
    assert QualityFlag.MISSING in point.quality.flags
    assert any("model output" in note for note in point.quality.notes)


def test_severity_stays_unknown_pending_sign_off(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    """Q2/Q3 are unanswered; inventing a threshold here would be a silent
    decision about what counts as dangerous weather."""
    point = _run(adapter, load_fixture(SINGLE), WeatherQuery(samples=[_sample()]))[0]
    assert point.severity is Severity.UNKNOWN


def test_quality_score_is_absent(adapter: OpenMeteoWeatherAdapter) -> None:
    point = _run(adapter, load_fixture(SINGLE), WeatherQuery(samples=[_sample()]))[0]
    assert point.quality.score is None


def test_expires_at_follows_the_registry_ttl(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    point = _run(adapter, load_fixture(SINGLE), WeatherQuery(samples=[_sample()]))[0]
    ttl = adapter.provider.entry.cache.effective_ttl
    assert point.source.expires_at is not None
    delta = (point.source.expires_at - point.source.fetched_at).total_seconds()
    assert delta == pytest.approx(ttl, abs=1)


# ----------------------------------------------------------------- coverage


def test_coverage_rejects_an_empty_sample_list(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    assert adapter.coverage(WeatherQuery(samples=[])).supported is False


def test_coverage_rejects_a_reversed_window(adapter: OpenMeteoWeatherAdapter) -> None:
    now = datetime.now(UTC)
    decision = adapter.coverage(
        WeatherQuery(samples=[_sample()], start=now, end=now - timedelta(hours=1))
    )
    assert decision.supported is False


def test_coverage_rejects_an_impossible_coordinate(
    adapter: OpenMeteoWeatherAdapter,
) -> None:
    assert adapter.coverage(WeatherQuery(samples=[_sample(lat=95.0)])).supported is False


def test_request_always_pins_utc_and_units(adapter: OpenMeteoWeatherAdapter) -> None:
    request = adapter.build_request(WeatherQuery(samples=[_sample()]))
    assert request.params is not None
    assert request.params["timezone"] == "UTC"
    assert request.params["temperature_unit"] == "celsius"
    assert request.params["wind_speed_unit"] == "kmh"
    assert request.params["precipitation_unit"] == "mm"
