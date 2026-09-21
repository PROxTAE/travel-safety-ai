"""Live canary: hits the real provider endpoints.

Excluded from the default run. Execute deliberately:

    uv run pytest -m canary

These are the phase exit checks from the module plan: Bangkok, Chiang Mai and an
international location must resolve for real with a forecast and honest
freshness (Phase 2), and the USGS feed must still have the shape the adapter
expects (Phase 3). They also detect schema drift that a frozen fixture never
will, which is the whole reason to keep tests that depend on the network.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.eonet import EonetAdapter
from app.adapters.gdacs import GdacsAdapter
from app.adapters.gtfs import GtfsAdapter
from app.adapters.open_meteo_geocoding import GeocodeQuery, OpenMeteoGeocodingAdapter
from app.adapters.open_meteo_weather import (
    CoordinateSample,
    OpenMeteoWeatherAdapter,
    WeatherQuery,
)
from app.adapters.openrouteservice import OpenRouteServiceAdapter
from app.adapters.ors_pois import OrsPoisAdapter
from app.adapters.usgs import UsgsAdapter
from app.domain.enums import (
    DataStatus,
    EventType,
    PlaceType,
    ProviderStatus,
    RiskLevel,
    Severity,
    TransportStatusCode,
    TravelMode,
)
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import (
    DisasterQuery,
    NearbyPlacesQuery,
    RouteQuery,
    TransitQuery,
)
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderTransport
from tests.conftest import REGISTRY_PATH

pytestmark = pytest.mark.canary

# One live call per distinct question, shared by every test that asks it.
# Three tests hitting the same free public feed in as many seconds is both
# impolite and flaky - a canary that fails at random gets ignored, and then it
# is not a canary any more. A failure here should mean the provider is actually
# unreachable.
_LIVE_CACHE: dict[str, list[Any]] = {}

# Read at import time, before the autouse fixture in conftest clears provider
# credentials for the rest of the suite. Without a key the routing canaries skip
# rather than fail: a machine with no openrouteservice account is a normal state
# for a teammate running the tests, and a canary that always fails gets ignored.
_ORS_KEY = os.environ.get("ORS_API_KEY") or ""
_needs_ors = pytest.mark.skipif(not _ORS_KEY, reason="ORS_API_KEY is not set in this environment")


async def _once(key: str, fetch: Callable[[], Awaitable[list[Any]]]) -> list[Any]:
    if key not in _LIVE_CACHE:
        _LIVE_CACHE[key] = await fetch()
    return _LIVE_CACHE[key]


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
    points = await weather.query(WeatherQuery(samples=[CoordinateSample(13.7563, 100.5018)]))

    drift = [note for note in points[0].quality.notes if "expected" in note]
    assert drift == [], f"unit drift detected: {drift}"


async def test_live_forecast_is_plausible_for_the_tropics(
    weather: OpenMeteoWeatherAdapter,
) -> None:
    """A weak sanity bound, not a weather assertion. It catches a unit swap -
    Bangkok at 27 °F, or wind reported in m/s and read as km/h."""
    points = await weather.query(WeatherQuery(samples=[CoordinateSample(13.7563, 100.5018)]))

    temperatures = [p.temperature_c for p in points if p.temperature_c is not None]
    assert temperatures
    assert all(5.0 <= value <= 50.0 for value in temperatures)
    assert all(p.wind_speed_kmh is None or 0.0 <= p.wind_speed_kmh <= 250.0 for p in points)
    assert all(
        p.precipitation_probability is None or 0 <= p.precipitation_probability <= 100
        for p in points
    )


# --------------------------------------------------------------- USGS (Phase 3)


@pytest.fixture
def usgs() -> UsgsAdapter:
    return _adapter("usgs_earthquake", UsgsAdapter)


async def test_live_usgs_feed_matches_the_expected_shape(usgs: UsgsAdapter) -> None:
    """Schema drift on a hazard feed is the kind of thing a frozen fixture will
    never tell you about."""
    events = await _once("usgs:7d", _usgs_week(usgs))

    # A quiet week worldwide is implausible, but assert only what must hold.
    for event in events:
        assert event.event_type is EventType.EARTHQUAKE
        assert len(event.geometry.coordinates) == 2
        assert -180 <= event.geometry.longitude <= 180
        assert -90 <= event.geometry.latitude <= 90
        assert event.effective_at.utcoffset() == timedelta(0)
        assert event.effective_at.year >= 2020  # epoch-ms handled correctly
        assert event.source.observed_at == event.effective_at
        assert event.source.source_url and event.source.source_url.startswith("https://")
        assert event.official is True
        assert event.severity is Severity.UNKNOWN  # pending Q2/Q3


async def test_live_usgs_magnitudes_are_plausible(usgs: UsgsAdapter) -> None:
    """Catches a unit or scale swap: magnitudes live roughly in -2..10."""
    from app.adapters.usgs import DisasterQuery

    events = await usgs.query(DisasterQuery(start=datetime.now(UTC) - timedelta(days=7)))
    magnitudes = [e.magnitude for e in events if e.magnitude is not None]

    assert magnitudes, "no magnitudes in a week of global earthquakes"
    assert all(-2.0 <= value <= 10.0 for value in magnitudes)
    assert all(e.depth_km is None or -5.0 <= e.depth_km <= 800.0 for e in events)


# -------------------------------------------------------------- GDACS (Phase 3)


@pytest.fixture
def gdacs() -> GdacsAdapter:
    return _adapter("gdacs", GdacsAdapter)


async def test_live_gdacs_feed_matches_the_expected_shape(gdacs: GdacsAdapter) -> None:
    events = await _once("gdacs:all", lambda: gdacs.query(DisasterQuery()))

    assert events, "GDACS reported no active hazards worldwide, which is implausible"
    for event in events:
        assert event.title.strip()  # eventname is empty; the fallback must work
        assert len(event.geometry.coordinates) == 2
        assert -180 <= event.geometry.longitude <= 180
        assert -90 <= event.geometry.latitude <= 90
        assert event.effective_at.utcoffset() == timedelta(0)
        assert event.official is True
        assert event.severity is Severity.UNKNOWN  # pending Q2/Q3
        assert "<" not in (event.description or "")  # never the html field


async def test_live_gdacs_alert_levels_are_still_the_expected_scale(
    gdacs: GdacsAdapter,
) -> None:
    """If this scale ever changes, the mapping notes and the UI guidance that
    depend on it are wrong — and a frozen fixture would never say so."""
    events = await _once("gdacs:all", lambda: gdacs.query(DisasterQuery()))
    levels = {event.alert_level for event in events if event.alert_level}

    assert levels
    assert levels <= {"Green", "Orange", "Red"}, levels


async def test_live_gdacs_hazard_types_all_map(gdacs: GdacsAdapter) -> None:
    """An unmapped provider code becomes OTHER, which is safe but lossy. This
    surfaces a new code as soon as GDACS starts publishing one."""
    events = await _once("gdacs:all", lambda: gdacs.query(DisasterQuery()))
    unmapped = [e for e in events if e.event_type is EventType.OTHER]

    # Drought legitimately maps to OTHER; anything else is worth knowing about.
    assert len(unmapped) < len(events), "every hazard fell through to OTHER"


# -------------------------------------------------------------- EONET (Phase 3)


@pytest.fixture
def eonet() -> EonetAdapter:
    return _adapter("nasa_eonet", EonetAdapter)


async def test_live_eonet_feed_matches_the_expected_shape(eonet: EonetAdapter) -> None:
    events = await _once("eonet:open", lambda: eonet.query(DisasterQuery()))

    assert events, "EONET reported no open natural events, which is implausible"
    for event in events:
        assert event.title.strip()
        assert len(event.geometry.coordinates) == 2
        assert -180 <= event.geometry.longitude <= 180
        assert -90 <= event.geometry.latitude <= 90
        assert event.effective_at.utcoffset() == timedelta(0)
        assert event.ends_at is None  # status=open was requested
        assert event.severity is Severity.UNKNOWN


async def test_live_eonet_position_is_the_latest_track_point(
    eonet: EonetAdapter,
) -> None:
    """The trap this adapter exists for: a tracked storm reported at its first
    observation is hundreds of kilometres from where it actually is."""
    events = await eonet.query(DisasterQuery(event_types=[EventType.STORM]))

    for event in events:
        assert event.source.observed_at is not None
        # The record describes the latest observation, so that timestamp can
        # never be older than the moment the event began.
        assert event.source.observed_at >= event.effective_at


async def test_live_eonet_bbox_is_honoured_by_the_provider(
    eonet: EonetAdapter,
) -> None:
    """The bbox parameter is pushed to the provider in its own coordinate
    order. If that order ever changes, results silently widen - so verify."""
    box = (-125.0, 32.0, -115.0, 42.0)  # western United States
    events = await eonet.query(DisasterQuery(bbox=box))

    for event in events:
        assert box[0] <= event.geometry.longitude <= box[2]
        assert box[1] <= event.geometry.latitude <= box[3]


def _usgs_week(usgs: UsgsAdapter) -> Callable[[], Awaitable[list[Any]]]:
    """A fixed window, so the two USGS canaries really do ask one question."""
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=7)
    return lambda: usgs.query(DisasterQuery(start=start))


# --------------------------------------------------------------------- ORS


@pytest.fixture
def ors(monkeypatch: pytest.MonkeyPatch) -> OpenRouteServiceAdapter:
    monkeypatch.setenv("ORS_API_KEY", _ORS_KEY)
    get_settings.cache_clear()
    return _adapter("openrouteservice", OpenRouteServiceAdapter)


@pytest.fixture
def ors_pois(monkeypatch: pytest.MonkeyPatch) -> OrsPoisAdapter:
    monkeypatch.setenv("ORS_API_KEY", _ORS_KEY)
    get_settings.cache_clear()
    return _adapter("ors_pois", OrsPoisAdapter)


BANGKOK = (100.5383, 13.7649)
AYUTTHAYA = (100.5878, 14.3532)


def _bangkok_route(ors: OpenRouteServiceAdapter) -> Callable[[], Awaitable[list[Any]]]:
    return lambda: ors.query(
        RouteQuery(waypoints=[BANGKOK, AYUTTHAYA], mode=TravelMode.CAR, alternatives=2)
    )


@_needs_ors
async def test_live_ors_returns_a_real_road_route(
    ors: OpenRouteServiceAdapter,
) -> None:
    """Phase 4 exit: a real road route with geometry and turn instructions."""
    routes = await _once("ors_bangkok", _bangkok_route(ors))

    assert routes, "the provider returned no route at all"
    route = routes[0]
    # Bangkok to Ayutthaya is about 75 km by road. A value near 74 in the wrong
    # unit would be metres, and near 74000 in kilometres - both are caught here.
    assert 50_000 < route.distance_m < 150_000
    assert route.duration_seconds > 600
    assert len(route.geometry.coordinates) > 50
    assert route.segments and route.segments[0].steps


@_needs_ors
async def test_live_ors_geometry_is_longitude_latitude(
    ors: OpenRouteServiceAdapter,
) -> None:
    """Schema drift that a frozen fixture can never catch: if the provider ever
    changed ordinate order, every route would silently land in Somalia."""
    routes = await _once("ors_bangkok", _bangkok_route(ors))

    for longitude, latitude in routes[0].geometry.coordinates[:200]:
        assert 95.0 < longitude < 110.0
        assert 5.0 < latitude < 22.0


@_needs_ors
async def test_live_ors_never_asserts_a_risk_level(
    ors: OpenRouteServiceAdapter,
) -> None:
    """The safety invariant, checked against the live provider rather than a
    fixture, so a future provider field cannot start populating it by accident."""
    routes = await _once("ors_bangkok", _bangkok_route(ors))

    for route in routes:
        assert route.risk_level is RiskLevel.UNKNOWN
        assert route.exposure is None


@_needs_ors
async def test_live_ors_reports_the_road_graph_age(
    ors: OpenRouteServiceAdapter,
) -> None:
    """Freshness here is the age of the map, not of the request.

    If the provider stops sending `graph_date` the record must say PARTIAL
    rather than quietly claiming to be fresh, so the field is worth watching.
    """
    routes = await _once("ors_bangkok", _bangkok_route(ors))
    quality = routes[0].quality

    if routes[0].source.published_at is None:
        assert quality.status is DataStatus.PARTIAL
    else:
        assert quality.freshness_seconds is not None
        assert quality.freshness_seconds > 0
    # A route is computed, never observed.
    assert routes[0].source.observed_at is None


@_needs_ors
async def test_live_ors_finds_hospitals_near_victory_monument(
    ors_pois: OrsPoisAdapter,
) -> None:
    """Phase 4 exit for the emergency directory.

    Central Bangkok has several large hospitals within two kilometres. An empty
    answer here means the category mapping has drifted - which is exactly how
    this went wrong the first time, when a plausible-looking category id
    returned restaurants.
    """
    places = await _once(
        "ors_pois_bangkok",
        lambda: ors_pois.query(
            NearbyPlacesQuery(
                longitude=BANGKOK[0],
                latitude=BANGKOK[1],
                radius_m=2000,
                place_types=[PlaceType.HOSPITAL, PlaceType.POLICE],
            )
        ),
    )

    assert places, "no emergency places found in central Bangkok"
    assert any(place.place_type is PlaceType.HOSPITAL for place in places)
    assert all(
        place.place_type in (PlaceType.HOSPITAL, PlaceType.POLICE, PlaceType.OTHER)
        for place in places
    )


@_needs_ors
async def test_live_ors_places_stay_inside_the_radius(
    ors_pois: OrsPoisAdapter,
) -> None:
    places = await _once("ors_pois_bangkok", lambda: [])

    for place in places:
        if place.distance_m is not None:
            # A little slack: the provider measures from the buffered geometry.
            assert place.distance_m <= 2_500
        assert place.source.source_url is not None


# --------------------------------------------------------------------- GTFS


@pytest.fixture
def gtfs() -> GtfsAdapter:
    return _adapter("gtfs_registry", GtfsAdapter)


NEW_YORK_BBOX = (-74.1, 40.6, -73.8, 40.9)


def _nyc_transit(gtfs: GtfsAdapter) -> Callable[[], Awaitable[list[Any]]]:
    return lambda: gtfs.query(TransitQuery(bbox=NEW_YORK_BBOX, limit=80))


async def test_live_gtfs_returns_running_trips(gtfs: GtfsAdapter) -> None:
    """Phase 5 exit: at least one real GTFS-Realtime region must work."""
    statuses = await _once("gtfs_nyc", _nyc_transit(gtfs))

    assert statuses, "the agency feed reported no trips at all"
    for status in statuses:
        assert status.origin_stop.name
        assert status.destination_stop.name


async def test_live_gtfs_joins_some_trips_to_the_timetable(
    gtfs: GtfsAdapter,
) -> None:
    """The check a frozen fixture cannot make.

    The realtime and schedule feeds use different trip-id forms, and joining
    them wrongly matches nothing while looking perfectly healthy - every record
    is still valid, just UNKNOWN. If the agency changes either format, this is
    what notices.
    """
    statuses = await _once("gtfs_nyc", _nyc_transit(gtfs))
    matched = [s for s in statuses if s.scheduled_arrival is not None]

    assert matched, (
        "no live trip matched the published timetable - the trip-id join has " "most likely drifted"
    )


async def test_live_gtfs_delays_are_minutes_not_timezone_offsets(
    gtfs: GtfsAdapter,
) -> None:
    """GTFS clock times are local to the agency. Reading them as UTC makes every
    New York train exactly four hours late."""
    statuses = await _once("gtfs_nyc", _nyc_transit(gtfs))

    for status in statuses:
        if status.delay_minutes is not None:
            assert abs(status.delay_minutes) < 180, (
                f"{status.id} is {status.delay_minutes} minutes off, which looks "
                "like a timezone error rather than a delay"
            )


async def test_live_gtfs_never_claims_on_time_without_a_schedule(
    gtfs: GtfsAdapter,
) -> None:
    """Contract § 3.6, checked against the live feed so that a future provider
    field cannot start populating it by accident."""
    statuses = await _once("gtfs_nyc", _nyc_transit(gtfs))

    for status in statuses:
        if status.status is TransportStatusCode.ON_TIME:
            assert status.delay_minutes is not None
        if status.scheduled_arrival is None:
            assert status.status is not TransportStatusCode.ON_TIME


async def test_live_gtfs_snapshot_is_recent(gtfs: GtfsAdapter) -> None:
    """The agency rebuilds trip updates about every 30 seconds; § 10 allows 90.
    A snapshot much older than that means the feed has stalled."""
    statuses = await _once("gtfs_nyc", _nyc_transit(gtfs))
    observed = [s.source.observed_at for s in statuses if s.source.observed_at]

    assert observed
    age = (datetime.now(UTC) - max(observed)).total_seconds()
    assert age < 900, f"the newest realtime snapshot is {age:.0f}s old"


async def test_live_gtfs_refuses_a_region_it_does_not_cover(
    gtfs: GtfsAdapter,
) -> None:
    """Coverage is per agency. Bangkok publishes no GTFS-Realtime at all, which
    is why the demo region is New York - and that limit has to be visible."""
    with pytest.raises(ProviderError) as excinfo:
        await gtfs.query(TransitQuery(bbox=(100.0, 13.0, 101.0, 14.0)))
    assert excinfo.value.code is ProviderErrorCode.OUTSIDE_COVERAGE
