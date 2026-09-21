"""Routes and emergency places built by module 04, validated against the canonical schemas.

A companion to `test_real_producer_records.py`, added after module 04 validated their real records
against the frozen v1 and found six disagreements that the tests here could not have caught:

* nothing built a `RouteCandidate` or an `EmergencyPOI` from module 04's own models at all, so the
  two entities were only ever checked against fixtures this repository wrote;
* `format` was not being checked, so `route_id: {format: uuid}` happily accepted
  `openrouteservice:3ca4459b8d41b503` in every test while failing against a validator that does
  check it. `conftest.validator_for` now passes a `FormatChecker`.

Module 04 is not a dependency of this test environment, so the import is guarded: where its source
is absent the file skips rather than failing.
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
    sys.path.insert(0, str(EXTERNAL_DATA))

NOW = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def m04() -> Any:
    from app.domain import canonical, enums, records  # noqa: PLC0415

    return canonical, enums, records


def _schema(name: str) -> dict[str, Any]:
    import json  # noqa: PLC0415

    path = Path(CONTRACTS) / "jsonschema" / "common" / name
    return dict(json.loads(path.read_text(encoding="utf-8")))


def assert_valid(schema_name: str, payload: dict[str, Any], pointer: str | None = None) -> None:
    validator = validator_for(schema_name, pointer)
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    assert not errors, "\n".join(
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in errors
    )


@pytest.fixture
def provenance(m04: Any) -> Any:
    """Provenance as the routing adapter builds it. No observation time: a route is not observed."""
    canonical, enums, _ = m04
    return canonical.SourceProvenance(
        source_id="openrouteservice:3ca4459b8d41b503",
        provider="openrouteservice",
        provider_record_id="0@3ca4459b8d41b503",
        authority=enums.SourceAuthority.COMMUNITY,
        source_url="https://api.openrouteservice.org/v2/directions/driving-car",
        license="ODbL-1.0",
        observed_at=None,
        fetched_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
        content_hash=canonical.content_hash({"waypoints": 2, "mode": "CAR"}),
        schema_version="1.0.0",
    )


def _route_payload(record: Any) -> dict[str, Any]:
    """Module 04's RouteCandidate, now under the contract's own field names.

    This used to rename `source` to `sources` while module 04 caught up. That
    shim is gone: the producer emits `sources` itself, so the test is once again
    about the schema rather than about a translation written here.
    """
    return record.model_dump(mode="json")


# --- routes ---------------------------------------------------------------------------------------


def test_a_real_route_validates_with_a_reproducible_id(m04: Any, provenance: Any) -> None:
    """The id disagreement, in the record that motivated it.

    `route_id` was `format: uuid`. Module 04 mints `openrouteservice:<fingerprint of the question>`
    so that asking for the same route twice yields the same id — otherwise a route served from
    cache and one fetched fresh look like two different routes. Same reasoning already accepted
    for `source_id` and `event_id`.
    """
    canonical, enums, records = m04
    geometry = records.GeoLineString(
        type="LineString", coordinates=[[100.5383, 13.7649], [100.5878, 14.3532]]
    )
    route = records.RouteCandidate(
        route_id="openrouteservice:3ca4459b8d41b503",
        provider_route_id="0@3ca4459b8d41b503",
        label=enums.RouteLabel.ORIGINAL,
        mode=enums.TravelMode.CAR,
        geometry=geometry,
        segments=[
            records.RouteSegment(
                segment_id="openrouteservice:3ca4459b8d41b503:0",
                mode=enums.TravelMode.CAR,
                geometry=geometry,
                distance_m=73688.3,
                duration_seconds=3183.8,
            )
        ],
        distance_m=73688.3,
        duration_seconds=3183.8,
        transfers=0,
        quality=canonical.DataQuality.from_age(age_seconds=5, fresh_within_seconds=1800),
        sources=[provenance],
        bbox=(100.5, 13.7, 100.6, 14.4),
    )

    payload = _route_payload(route)
    assert ":" in payload["route_id"], "this test is pointless against a UUID"
    assert_valid("route-candidate.schema.json", payload)


def test_a_raw_route_carries_no_exposure_and_unknown_risk(m04: Any, provenance: Any) -> None:
    """A routing provider cannot measure hazard exposure, so it must be able to say nothing.

    The alternative the old schema left module 04 with was `score: 0, closed: false` — a route
    across a closed bridge arriving at module 07 asserting, in the contract's own vocabulary, that
    nothing is wrong.
    """
    canonical, enums, records = m04
    geometry = records.GeoLineString(
        type="LineString", coordinates=[[100.5383, 13.7649], [100.5878, 14.3532]]
    )
    route = records.RouteCandidate(
        route_id="openrouteservice:3ca4459b8d41b503",
        label=enums.RouteLabel.ORIGINAL,
        mode=enums.TravelMode.CAR,
        geometry=geometry,
        distance_m=73688.3,
        duration_seconds=3183.8,
        quality=canonical.DataQuality.from_age(age_seconds=5, fresh_within_seconds=1800),
        sources=[provenance],
    )

    payload = _route_payload(route)
    assert payload["exposure"] is None
    assert payload["risk_level"] == "UNKNOWN"
    assert_valid("route-candidate.schema.json", payload)


def test_an_unevaluated_route_may_not_claim_a_risk_level() -> None:
    """The invariant that keeps the nullability from becoming a hole of its own.

    `exposure: null` beside `risk_level: LOW` reads to any consumer as "checked, and fine". The
    schema refuses the pair, so a null exposure can only ever mean "not evaluated yet".
    """
    validator = validator_for("route-candidate.schema.json")
    route = {
        "route_id": "openrouteservice:3ca4459b8d41b503",
        "label": "ORIGINAL",
        "mode": "CAR",
        "geometry": {
            "type": "LineString",
            "coordinates": [[100.5383, 13.7649], [100.5878, 14.3532]],
        },
        "distance_m": 73688.3,
        "duration_seconds": 3183.8,
        "exposure": None,
        "risk_level": "LOW",
        "quality": {"status": "FRESH", "flags": []},
        "sources": [
            {
                "source_id": "openrouteservice:x",
                "provider": "openrouteservice",
                "authority": "COMMUNITY",
                "source_url": "https://api.openrouteservice.org/x",
                "fetched_at": "2026-09-20T06:00:00Z",
                "content_hash": None,
                "schema_version": "1.0.0",
            }
        ],
    }

    assert list(validator.iter_errors(route)), (
        "an unmeasured corridor beside a confident risk level must not validate"
    )


def test_an_evaluated_route_still_requires_its_exposure() -> None:
    """Nullability is for the raw producer, not a general licence to omit the measurement."""
    validator = validator_for("route-candidate.schema.json")
    route = {
        "route_id": "openrouteservice:3ca4459b8d41b503",
        "label": "RECOMMENDED",
        "mode": "CAR",
        "geometry": {
            "type": "LineString",
            "coordinates": [[100.5383, 13.7649], [100.5878, 14.3532]],
        },
        "distance_m": 73688.3,
        "duration_seconds": 3183.8,
        "risk_level": "LOW",
        "quality": {"status": "FRESH", "flags": []},
        "sources": [],
    }

    assert list(validator.iter_errors(route)), "exposure is required, present as null or measured"


# --- emergency places -----------------------------------------------------------------------------


def _poi_payload(record: Any) -> dict[str, Any]:
    """Module 04's EmergencyPlace, now under the contract's own field names.

    The `place_id`/`place_type` shim is gone - the producer emits `poi_id` and
    `poi_type` directly.
    """
    return record.model_dump(mode="json")


def test_a_hospital_with_no_name_in_openstreetmap_validates(m04: Any, provenance: Any) -> None:
    """The record this change exists for.

    Two of nineteen emergency POIs around Victory Monument carry no `name` tag, and both are real
    hospitals — one of them 335 m away, nearer than several that are named. A required non-null
    name left two options and both were bad: drop the record, and hide the nearest hospital from
    somebody who needs one; or synthesise "Unnamed hospital", and put words the provider never said
    into a data field.
    """
    canonical, enums, records = m04
    place = records.EmergencyPlace(
        poi_id="ors_pois:osm:156924967",
        poi_type=enums.PlaceType.HOSPITAL,
        name=None,
        location=records.GeoPoint.from_lat_lon(13.7649, 100.5383),
        distance_m=335.0,
        quality=canonical.DataQuality.from_age(age_seconds=60, fresh_within_seconds=86_400),
        source=provenance,
        provider_category="hospital",
    )

    payload = _poi_payload(place)
    assert payload["name"] is None
    assert_valid("emergency-poi.schema.json", payload)


def test_a_place_without_a_distance_validates(m04: Any, provenance: Any) -> None:
    """Null rather than zero, which would read as "you are here"."""
    canonical, enums, records = m04
    place = records.EmergencyPlace(
        poi_id="ors_pois:osm:1",
        poi_type=enums.PlaceType.POLICE,
        name="Phaya Thai Police Station",
        location=records.GeoPoint.from_lat_lon(13.7649, 100.5383),
        distance_m=None,
        quality=canonical.DataQuality.unavailable("provider omitted distance"),
        source=provenance,
    )

    payload = _poi_payload(place)
    assert payload["distance_m"] is None
    assert_valid("emergency-poi.schema.json", payload)


@pytest.mark.parametrize("place_type", ["DOCTOR", "TOWNHALL", "OTHER"])
def test_the_poi_types_module_04_produces_are_in_the_contract(
    m04: Any, provenance: Any, place_type: str
) -> None:
    """`OTHER` especially.

    Every other enum in the contract has a way to say "not one we model" — `EventType` has OTHER,
    `Severity`, `RiskLevel`, `DataStatus` and `SourceAuthority` have UNKNOWN. Without one here, the
    rule "map an unknown enum onto the unknown member, never invent a string at runtime" had
    nothing to map onto, so a provider category we had not modelled could only be discarded or
    given a neighbouring label that was wrong.
    """
    canonical, enums, records = m04
    place = records.EmergencyPlace(
        poi_id=f"ors_pois:osm:{place_type.lower()}",
        poi_type=enums.PlaceType(place_type),
        name="Somewhere",
        location=records.GeoPoint.from_lat_lon(13.7649, 100.5383),
        distance_m=120.0,
        quality=canonical.DataQuality.from_age(age_seconds=60, fresh_within_seconds=86_400),
        source=provenance,
    )

    assert_valid("emergency-poi.schema.json", _poi_payload(place))


def test_every_poi_type_module_04_can_emit_is_accepted(m04: Any) -> None:
    """The whole producer enum against the whole contract enum, so neither can drift alone."""
    _, enums, _ = m04
    contract = set(_schema("emergency-poi.schema.json")["properties"]["poi_type"]["enum"])
    produced = {member.value for member in enums.PlaceType}

    missing = produced - contract
    assert not missing, f"module 04 emits POI types the contract cannot express: {sorted(missing)}"
