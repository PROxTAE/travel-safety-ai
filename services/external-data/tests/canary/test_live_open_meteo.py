"""Live canary: hits the real Open-Meteo endpoints.

Excluded from the default run. Execute deliberately:

    uv run pytest -m canary

This is the Phase 2 exit check from the module plan - Bangkok, Chiang Mai and an
international location must resolve for real, with a forecast and honest
freshness. It also detects schema drift that a frozen fixture never will, which
is the whole reason to keep a test that depends on the network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.open_meteo_geocoding import GeocodeQuery, OpenMeteoGeocodingAdapter
from app.adapters.open_meteo_weather import (
    CoordinateSample,
    OpenMeteoWeatherAdapter,
    WeatherQuery,
)
from app.domain.enums import DataStatus, ProviderStatus, Severity
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderTransport
from tests.conftest import REGISTRY_PATH

pytestmark = pytest.mark.canary


def _adapter(provider_id: str, adapter_class: type):  # type: ignore[type-arg]
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == provider_id)
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return adapter_class(provider, ProviderTransport(Defaults()))


@pytest.fixture
def geocoder() -> OpenMeteoGeocodingAdapter:
    return _adapter("open_meteo_geocoding", OpenMeteoGeocodingAdapter)


@pytest.fixture
def weather() -> OpenMeteoWeatherAdapter:
    return _adapter("open_meteo_forecast", OpenMeteoWeatherAdapter)


@pytest.mark.parametrize(
    ("name", "country", "lat_range"),
    [
        ("Bangkok", "TH", (13.0, 14.5)),
        ("Chiang Mai", "TH", (18.0, 19.5)),
        ("Tokyo", "JP", (35.0, 36.5)),
        ("Reykjavik", "IS", (63.5, 65.0)),
    ],
)
async def test_live_geocode_resolves_a_real_place(
    geocoder: OpenMeteoGeocodingAdapter,
    name: str,
    country: str,
    lat_range: tuple[float, float],
) -> None:
    results = await geocoder.query(GeocodeQuery(name=name, count=3))

    assert results, f"no result for {name}"
    top = results[0].location
    assert top.country_code == country
    low, high = lat_range
    assert low <= top.coordinates.latitude <= high
    assert -180 <= top.coordinates.longitude <= 180
    assert top.timezone
    # Recent, not "not in the future": the transport stamps fetched_at from
    # time.time() while this reads datetime.now(), and on Windows those two
    # disagree at the microsecond level.
    age = (datetime.now(UTC) - results[0].source.fetched_at).total_seconds()
    assert -1.0 < age < 60.0


async def test_live_geocode_provenance_is_complete(
    geocoder: OpenMeteoGeocodingAdapter,
) -> None:
    result = (await geocoder.query(GeocodeQuery(name="Bangkok", count=1)))[0]

    assert result.source.provider == "open_meteo_geocoding"
    assert result.source.provider_record_id
    assert result.source.source_url
    assert result.source.license
    assert result.source.expires_at and result.source.expires_at > result.source.fetched_at
    # A place-name index has no observation time and must not fake one.
    assert result.source.observed_at is None


async def test_live_forecast_covers_a_real_route(
    weather: OpenMeteoWeatherAdapter,
) -> None:
    """Two real points with ETAs an hour apart, the shape module 05 will ask for."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    points = await weather.query(
        WeatherQuery(
            samples=[
                CoordinateSample(13.7563, 100.5018, eta=now + timedelta(hours=1), sample_id="bkk"),
                CoordinateSample(18.7883, 98.9853, eta=now + timedelta(hours=4), sample_id="cnx"),
            ]
        )
    )

    assert len(points) == 2
    assert {p.sample_id for p in points} == {"bkk", "cnx"}

    for point in points:
        assert point.valid_at.utcoffset() == timedelta(0)
        assert point.temperature_c is not None
        assert point.quality.status is DataStatus.FRESH
        assert point.source.observed_at is None  # model output, never a measurement
        assert point.severity is Severity.UNKNOWN  # pending Q2/Q3
        assert abs(point.eta_offset_seconds or 0) <= 3600


async def test_live_forecast_units_have_not_drifted(
    weather: OpenMeteoWeatherAdapter,
) -> None:
    """We pin units in the request. If the provider stops honouring that, the
    adapter records it - and this canary is where the team finds out."""
    points = await weather.query(
        WeatherQuery(samples=[CoordinateSample(13.7563, 100.5018)])
    )

    drift = [note for note in points[0].quality.notes if "expected" in note]
    assert drift == [], f"unit drift detected: {drift}"


async def test_live_forecast_is_plausible_for_the_tropics(
    weather: OpenMeteoWeatherAdapter,
) -> None:
    """A weak sanity bound, not a weather assertion. It catches a unit swap -
    Bangkok at 27 °F, or wind reported in m/s and read as km/h."""
    points = await weather.query(
        WeatherQuery(samples=[CoordinateSample(13.7563, 100.5018)])
    )

    temperatures = [p.temperature_c for p in points if p.temperature_c is not None]
    assert temperatures
    assert all(5.0 <= value <= 50.0 for value in temperatures)
    assert all(
        p.wind_speed_kmh is None or 0.0 <= p.wind_speed_kmh <= 250.0 for p in points
    )
    assert all(
        p.precipitation_probability is None or 0 <= p.precipitation_probability <= 100
        for p in points
    )
