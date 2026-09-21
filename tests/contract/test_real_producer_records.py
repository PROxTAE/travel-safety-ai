"""Records built by a real producer, validated against the canonical schemas.

The other tests in this folder check the contract against fixtures this repository wrote, which
proves the schemas are self-consistent and proves nothing about whether a producer can actually
satisfy them. This file closes that gap: it imports module 04's own Pydantic models — the ones its
adapters return — constructs records with them, and validates the result.

It was written after review found that every module-04 record was rejected by the frozen schemas.
Four disagreements, none of which any existing test could have caught:

* `source_id` and the record ids were typed as UUIDs. Module 04 mints stable, reproducible ids like
  `usgs:us7000abcd`, and it is right to: deduplication in module 05 needs the same fact to produce
  the same id twice, and a fresh UUID per fetch makes that impossible.
* `content_hash` demanded bare hex. Module 04 emits `sha256:<hex>`, which is better — an unprefixed
  digest silently compares unequal to a prefixed one the day a second algorithm appears.
* `DataQuality` required a `score` and a `formula_version`. Module 04 deliberately leaves the score
  null until module 05 agrees the formula, because a placeholder number is indistinguishable from a
  measured one once it is downstream.
* `DisasterEvent.magnitude` had no unit, so 5.8 Mw and 5.8 mb were the same value in the contract.

Module 04 is not a dependency of this test environment, so the import is guarded: where its source
is not present the file skips rather than failing. Everywhere it *is* present — a full checkout, and
CI — these assertions run.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from conftest import CONTRACTS, validator_for

EXTERNAL_DATA = CONTRACTS.parents[1] / "services" / "external-data"

pytestmark = pytest.mark.skipif(
    not (EXTERNAL_DATA / "app" / "domain" / "canonical.py").exists(),
    reason="services/external-data is not present in this checkout",
)

if EXTERNAL_DATA.exists() and str(EXTERNAL_DATA) not in sys.path:
    # Only the domain modules are imported, and those depend on pydantic alone. Nothing here
    # reaches module 04's settings, database or HTTP layer, so its dependencies are not needed.
    sys.path.insert(0, str(EXTERNAL_DATA))


def _module_04() -> Any:
    from app.domain import canonical, enums, records  # noqa: PLC0415

    return canonical, enums, records


NOW = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def m04() -> Any:
    return _module_04()


@pytest.fixture
def provenance(m04: Any) -> Any:
    """Provenance shaped exactly as `adapters/base.py` builds it."""
    canonical, enums, _ = m04
    return canonical.SourceProvenance(
        # The real composite: provider key, then the provider's own record id.
        source_id="usgs:us7000abcd",
        provider="usgs",
        provider_record_id="us7000abcd",
        authority=enums.SourceAuthority.OFFICIAL,
        source_url="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
        license="public-domain",
        observed_at=NOW - timedelta(minutes=8),
        fetched_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        content_hash=canonical.content_hash({"mag": 5.8}),
        schema_version="1.0.0",
    )


def assert_valid(schema_name: str, payload: dict[str, Any], pointer: str | None = None) -> None:
    validator = validator_for(schema_name, pointer)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    assert not errors, "\n".join(
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    )


# --- provenance ---------------------------------------------------------------------------------


def test_real_provenance_validates(provenance: Any) -> None:
    assert_valid("source-provenance.schema.json", provenance.model_dump(mode="json"))


def test_a_stable_composite_source_id_is_accepted(provenance: Any) -> None:
    """The id module 04 actually mints, and the reason it is not a UUID.

    Module 05 deduplicates by source id. A UUID generated per fetch would make the same earthquake
    arrive as a new event every ten minutes.
    """
    assert provenance.source_id == "usgs:us7000abcd"
    assert_valid("source-provenance.schema.json", provenance.model_dump(mode="json"))


def test_the_same_fact_fetched_twice_keeps_one_identity(m04: Any) -> None:
    """A RecordId that is not reproducible is not doing its job."""
    canonical, enums, _ = m04

    def build() -> Any:
        return canonical.SourceProvenance(
            source_id="usgs:us7000abcd",
            provider="usgs",
            authority=enums.SourceAuthority.OFFICIAL,
            source_url="https://earthquake.usgs.gov/x",
            fetched_at=NOW,
            content_hash=canonical.content_hash({"mag": 5.8}),
        )

    first, second = build(), build()

    assert first.source_id == second.source_id
    assert first.content_hash == second.content_hash


def test_the_algorithm_prefixed_hash_is_accepted(m04: Any, provenance: Any) -> None:
    canonical, _, _ = m04

    assert provenance.content_hash.startswith("sha256:")
    assert_valid("source-provenance.schema.json", provenance.model_dump(mode="json"))
    assert canonical.content_hash({"a": 1}) != canonical.content_hash({"a": 2})


def test_a_provenance_without_a_content_hash_validates(m04: Any) -> None:
    """A record assembled from several responses has no single payload to hash."""
    canonical, enums, _ = m04
    record = canonical.SourceProvenance(
        source_id="open_meteo:forecast:13.7563,100.5018",
        provider="open_meteo",
        authority=enums.SourceAuthority.LICENSED_PROVIDER,
        source_url="https://api.open-meteo.com/v1/forecast",
        fetched_at=NOW,
        content_hash=None,
    )

    assert_valid("source-provenance.schema.json", record.model_dump(mode="json"))


def test_a_forecast_carries_no_observation_time(m04: Any) -> None:
    """A prediction was never observed. `fetched_at` in its place would age it wrongly."""
    canonical, enums, _ = m04
    record = canonical.SourceProvenance(
        source_id="open_meteo:forecast:13.7563,100.5018",
        provider="open_meteo",
        authority=enums.SourceAuthority.LICENSED_PROVIDER,
        source_url="https://api.open-meteo.com/v1/forecast",
        fetched_at=NOW,
        observed_at=None,
    )

    payload = record.model_dump(mode="json")
    assert payload["observed_at"] is None
    assert_valid("source-provenance.schema.json", payload)


# --- quality ------------------------------------------------------------------------------------


def test_quality_without_a_score_validates(m04: Any) -> None:
    """The disagreement that rejected every module-04 record.

    No scoring formula has been agreed with module 05, so module 04 leaves the score null. Requiring
    a number here would have forced a placeholder, and a placeholder score is indistinguishable from
    a real one by the time a decision is made on it.
    """
    canonical, _, _ = m04
    quality = canonical.DataQuality.from_age(age_seconds=120, fresh_within_seconds=3600)

    payload = quality.model_dump(mode="json")
    assert payload["score"] is None
    assert_valid("data-quality.schema.json", payload)


def test_a_stale_record_says_so_in_both_places(m04: Any) -> None:
    canonical, _, _ = m04
    quality = canonical.DataQuality.from_age(age_seconds=7200, fresh_within_seconds=3600)

    payload = quality.model_dump(mode="json")
    assert payload["status"] == "STALE"
    assert "STALE" in payload["flags"]
    assert_valid("data-quality.schema.json", payload)


def test_unavailable_quality_validates(m04: Any) -> None:
    """The shape a provider outage produces. It must not be the shape that fails validation."""
    canonical, _, _ = m04
    quality = canonical.DataQuality.unavailable("provider returned no coverage for this area")

    payload = quality.model_dump(mode="json")
    assert payload["status"] == "UNAVAILABLE"
    assert_valid("data-quality.schema.json", payload)


def test_a_score_without_its_version_is_rejected() -> None:
    """Both ends of the rule. A number nobody can attribute to a formula cannot be compared."""
    validator = validator_for("data-quality.schema.json")
    scored = {"status": "FRESH", "score": 0.91, "score_version": None, "flags": []}

    assert list(validator.iter_errors(scored)), (
        "a score with a null score_version must not validate"
    )

    scored["score_version"] = "1.0.0"
    assert not list(validator.iter_errors(scored))


def test_module_04_does_not_populate_conflicts(m04: Any) -> None:
    """`conflicts` carries structured objects; module 04 types it as a list of strings.

    It never fills one in — conflict detection belongs to module 05 — so the two do not collide
    today. This test fails the day that stops being true, which is the day the two representations
    have to be reconciled rather than discovered at integration time.
    """
    canonical, _, _ = m04
    quality = canonical.DataQuality.from_age(age_seconds=60, fresh_within_seconds=3600)

    assert quality.conflicts == [], (
        "module 04 now emits conflicts as plain strings; the canonical schema expects "
        "QualityConflict objects and the two must be reconciled"
    )


# --- records ------------------------------------------------------------------------------------


def test_a_real_forecast_point_validates(m04: Any, provenance: Any) -> None:
    canonical, _, records = m04
    point = records.WeatherForecastPoint(
        id="open_meteo:forecast:13.7563,100.5018:2026-09-20T07:00:00Z",
        location=records.GeoPoint.from_lat_lon(13.7563, 100.5018),
        valid_at=NOW + timedelta(hours=1),
        temperature_c=31.2,
        apparent_temperature_c=38.1,
        precipitation_mm=0.0,
        precipitation_probability=12,
        snowfall_cm=0.0,
        wind_speed_kmh=9.4,
        wind_gust_kmh=18.7,
        visibility_m=24000.0,
        weather_code=1,
        quality=canonical.DataQuality.from_age(age_seconds=120, fresh_within_seconds=3600),
        source=provenance,
    )

    assert_valid("weather.schema.json", point.model_dump(mode="json"), "$defs/WeatherForecastPoint")


def test_a_forecast_with_a_missing_measurement_validates(m04: Any, provenance: Any) -> None:
    """A value the provider did not supply is null, never zero.

    Zero precipitation and unknown precipitation are different facts, and the second one rendered as
    the first reads as "no rain".
    """
    canonical, _, records = m04
    point = records.WeatherForecastPoint(
        id="open_meteo:forecast:13.7563,100.5018:2026-09-20T07:00:00Z",
        location=records.GeoPoint.from_lat_lon(13.7563, 100.5018),
        valid_at=NOW + timedelta(hours=1),
        temperature_c=31.2,
        precipitation_mm=None,
        visibility_m=None,
        quality=canonical.DataQuality.unavailable("provider omitted precipitation"),
        source=provenance,
    )

    payload = point.model_dump(mode="json")
    assert payload["precipitation_mm"] is None
    assert_valid("weather.schema.json", payload, "$defs/WeatherForecastPoint")


def test_a_real_earthquake_validates_with_its_magnitude_unit(m04: Any, provenance: Any) -> None:
    """The unit disagreement, in the record that motivated it.

    Without `magnitude_unit` the contract said 5.8 and left the scale to be guessed. Comparing a
    moment magnitude against a body-wave magnitude as though they were the same number is a safety
    error, not a rounding one.
    """
    canonical, enums, records = m04
    event = records.DisasterEvent(
        event_id="usgs:us7000abcd",
        event_type=enums.EventType.EARTHQUAKE,
        title="M 5.8 - 120 km ESE of Example",
        description="Shallow earthquake offshore.",
        geometry=records.GeoPoint.from_lat_lon(13.0, 101.0),
        effective_at=NOW - timedelta(minutes=8),
        official=True,
        magnitude=5.8,
        magnitude_unit="Mw",
        depth_km=10.0,
        quality=canonical.DataQuality.from_age(age_seconds=480, fresh_within_seconds=600),
        source=provenance,
    )

    payload = event.model_dump(mode="json")
    assert payload["magnitude_unit"] == "Mw"
    assert_valid("disaster-event.schema.json", payload)


def test_a_magnitude_without_a_unit_is_rejected() -> None:
    validator = validator_for("disaster-event.schema.json")
    event = {
        "event_id": "usgs:us7000abcd",
        "event_type": "EARTHQUAKE",
        "title": "M 5.8",
        "description": None,
        "severity": "UNKNOWN",
        "geometry": {"type": "Point", "coordinates": [101.0, 13.0]},
        "effective_at": "2026-09-20T05:52:00Z",
        "ends_at": None,
        "instruction": None,
        "official": True,
        "magnitude": 5.8,
        "magnitude_unit": None,
        "quality": {"status": "FRESH", "score": None, "score_version": None, "flags": []},
        "source": {
            "source_id": "usgs:us7000abcd",
            "provider": "usgs",
            "authority": "OFFICIAL",
            "source_url": "https://earthquake.usgs.gov/x",
            "fetched_at": "2026-09-20T06:00:00Z",
            "content_hash": None,
            "schema_version": "1.0.0",
        },
    }

    assert list(validator.iter_errors(event)), (
        "a magnitude with no unit must not validate: the scale is not optional context"
    )


def test_a_real_geocode_result_validates(m04: Any) -> None:
    """What `/internal/v1/geocode/search` returns, which module 02 proxies to the browser."""
    _, _, records = m04
    location = records.LocationRef(
        place_id="open-meteo-1609350",
        display_name="Bangkok",
        coordinates=records.GeoPoint.from_lat_lon(13.7563, 100.5018),
        country_code="TH",
        admin1="Bangkok",
        timezone="Asia/Bangkok",
        provider="open_meteo",
    )

    payload = location.model_dump(mode="json")
    # Module 04 never asserts confirmation on a traveller's behalf.
    assert payload["confirmed_by_user"] is False
    assert_valid("location-ref.schema.json", payload)
