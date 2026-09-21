"""Validate what module 04 actually emits against the frozen contract.

This exists because the schema and the producer have drifted apart twice, and
both times nobody found out until someone validated real records by hand.

The first drift cost nine mismatches across `DisasterEvent`, `SourceProvenance`
and `DataQuality`; the second is still open on `RouteCandidate` and
`EmergencyPOI`. Neither showed up in a test, a type check or a review, because
the producer and the schema are both internally consistent - they simply
disagree with each other.

Records are built by running real captured provider responses through the real
adapters, so this checks what a consumer would receive, not what a handwritten
example says it should be.

Known mismatches are listed in `OPEN_CONTRACT_GAPS` with the issue that tracks
them. That list is a ratchet: a gap that gets fixed upstream makes its test
fail loudly rather than passing quietly, so nobody has to remember to come back
and delete it.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from app.domain.enums import ProviderStatus, TravelMode
from app.domain.queries import (
    DisasterQuery,
    NearbyPlacesQuery,
    RouteQuery,
    TransitQuery,
)
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import FIXTURE_ROOT, REGISTRY_PATH, SERVICE_ROOT

CONTRACTS = SERVICE_ROOT.parents[1] / "packages" / "contracts" / "jsonschema" / "common"

pytestmark = pytest.mark.skipif(
    not CONTRACTS.is_dir(),
    reason="packages/contracts is not present in this checkout",
)

# Empty, and that is the point.
#
# Every mismatch reported in issue #26 was accepted by module 02 and fixed in
# PR #29, which merged while this branch was being written - the ratchet test
# below is what noticed, by failing when each waiver stopped matching anything.
#
# Add an entry here only for a mismatch that is raised upstream and genuinely
# blocked, never to make a failing test pass.
OPEN_CONTRACT_GAPS: dict[str, tuple[str, ...]] = {}


def _registry_of_schemas() -> Any:
    from referencing import Registry, Resource

    resources = []
    for path in CONTRACTS.glob("*.schema.json"):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents)
        resources.append((path.name, resource))
        resources.append((f"common/{path.name}", resource))
    return Registry().with_resources(resources)


def _validate(schema_file: str, definition: str | None, payload: Any) -> list[str]:
    from jsonschema import Draft202012Validator, FormatChecker

    document = json.loads((CONTRACTS / schema_file).read_text(encoding="utf-8"))
    if definition is not None and definition in document.get("$defs", {}):
        schema = dict(document["$defs"][definition])
        schema["$defs"] = document["$defs"]
    else:
        schema = document

    validator = Draft202012Validator(
        schema, registry=_registry_of_schemas(), format_checker=FormatChecker()
    )
    messages = []
    for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in error.path) or "(root)"
        messages.append(f"{where}: {error.message}")
    return messages


def _unexpected(schema_file: str, messages: list[str]) -> list[str]:
    known = OPEN_CONTRACT_GAPS.get(schema_file, ())
    return [m for m in messages if not any(gap in m for gap in known)]


def _adapter(provider_id: str, adapter_class: type) -> Any:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == provider_id)
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return adapter_class(provider, ProviderTransport(Defaults()), env="test")


def _response(payload: Any = None, content: bytes | None = None) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://example.invalid/captured",
        fetched_at=time.time(),
        elapsed_seconds=0.3,
        content=content,
    )


def _fixture(relative: str) -> Any:
    return json.loads((FIXTURE_ROOT / relative).read_text(encoding="utf-8"))


# --------------------------------------------------------------- the records


@pytest.fixture(scope="module")
def disaster_event() -> dict[str, Any]:
    from app.adapters.usgs import UsgsAdapter

    adapter = _adapter("usgs_earthquake", UsgsAdapter)
    response = _response(_fixture("usgs/significant_month.json"))
    records = adapter.normalize(adapter.validate(response), response, DisasterQuery())
    return records[0].model_dump(mode="json")


@pytest.fixture(scope="module")
def location_ref() -> dict[str, Any]:
    from app.adapters.open_meteo_geocoding import GeocodeQuery, OpenMeteoGeocodingAdapter

    adapter = _adapter("open_meteo_geocoding", OpenMeteoGeocodingAdapter)
    response = _response(_fixture("open_meteo_geocoding/search_bangkok.json"))
    records = adapter.normalize(adapter.validate(response), response, GeocodeQuery(name="Bangkok"))
    return records[0].location.model_dump(mode="json")


@pytest.fixture(scope="module")
def route_candidate() -> dict[str, Any]:
    from app.adapters.openrouteservice import OpenRouteServiceAdapter

    adapter = _adapter("openrouteservice", OpenRouteServiceAdapter)
    response = _response(_fixture("openrouteservice/directions_bkk_ayutthaya.json"))
    query = RouteQuery(waypoints=[(100.5383, 13.7649), (100.5878, 14.3532)], mode=TravelMode.CAR)
    records = adapter.normalize(adapter.validate(response), response, query)
    return records[0].model_dump(mode="json")


@pytest.fixture(scope="module")
def emergency_places() -> list[dict[str, Any]]:
    """Every POI the adapter produced, not just the first.

    The first is a named hospital, which happens to satisfy the contract even
    where the contract is wrong. The records that matter are the two with no
    name in OpenStreetMap - validating only `records[0]` would have reported a
    clean pass on a schema that cannot represent them.
    """
    from app.adapters.ors_pois import OrsPoisAdapter

    adapter = _adapter("ors_pois", OrsPoisAdapter)
    response = _response(_fixture("openrouteservice/pois_emergency_bangkok.json"))
    query = NearbyPlacesQuery(longitude=100.5383, latitude=13.7649)
    records = adapter.normalize(adapter.validate(response), response, query)
    return [record.model_dump(mode="json") for record in records]


def _all_messages(schema_file: str, records: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for record in records:
        messages.extend(_validate(schema_file, None, record))
    return messages


@pytest.fixture(scope="module")
def transport_status() -> dict[str, Any]:
    from app.adapters.gtfs import GtfsAdapter, parse_schedule

    adapter = _adapter("gtfs_registry", GtfsAdapter)
    gtfs = FIXTURE_ROOT / "gtfs_mta"
    adapter.use_schedule(
        parse_schedule(
            (gtfs / "mta_subway_ace_static.zip").read_bytes(),
            feed_id="mta_nyct_subway",
            fetched_at=datetime.now(UTC),
            content_hash="sha256:" + "0" * 64,
        )
    )
    response = _response(content=(gtfs / "mta_subway_ace_tripupdates.pb").read_bytes())
    query = TransitQuery(bbox=(-74.1, 40.6, -73.8, 40.9), limit=5)
    records = adapter.normalize(adapter.validate(response), response, query)
    return records[0].model_dump(mode="json")


# ------------------------------------------------------- records that pass


def test_disaster_event_matches_the_contract(disaster_event: dict[str, Any]) -> None:
    assert (
        _unexpected(
            "disaster-event.schema.json",
            _validate("disaster-event.schema.json", "DisasterEvent", disaster_event),
        )
        == []
    )


def test_source_provenance_matches_the_contract(
    disaster_event: dict[str, Any],
) -> None:
    assert (
        _unexpected(
            "source-provenance.schema.json",
            _validate(
                "source-provenance.schema.json",
                "SourceProvenance",
                disaster_event["source"],
            ),
        )
        == []
    )


def test_data_quality_matches_the_contract(disaster_event: dict[str, Any]) -> None:
    assert (
        _unexpected(
            "data-quality.schema.json",
            _validate("data-quality.schema.json", "DataQuality", disaster_event["quality"]),
        )
        == []
    )


def test_location_ref_matches_the_contract(location_ref: dict[str, Any]) -> None:
    assert (
        _unexpected(
            "location-ref.schema.json",
            _validate("location-ref.schema.json", "LocationRef", location_ref),
        )
        == []
    )


def test_transport_status_matches_the_contract(
    transport_status: dict[str, Any],
) -> None:
    assert (
        _unexpected(
            "transport-status.schema.json",
            _validate("transport-status.schema.json", None, transport_status),
        )
        == []
    )


# -------------------------------------------------- records with known gaps


def test_route_candidate_matches_the_contract(
    route_candidate: dict[str, Any],
) -> None:
    messages = _validate("route-candidate.schema.json", None, route_candidate)
    assert _unexpected("route-candidate.schema.json", messages) == []


def test_an_unevaluated_route_cannot_claim_a_risk_level() -> None:
    """The invariant module 02 added in PR #29, checked from the producer side.

    `exposure: null` beside `risk_level: LOW` would read as "checked, and fine"
    - which is precisely the failure that made `exposure` non-nullable worth
    arguing about in the first place. Making it nullable alone would have moved
    the hole rather than closed it.
    """
    from app.domain.canonical import DataQuality, SourceProvenance
    from app.domain.enums import (
        DataStatus,
        RiskLevel,
        RouteLabel,
        SourceAuthority,
    )
    from app.domain.records import GeoLineString, RouteCandidate

    route = RouteCandidate(
        route_id="openrouteservice:abc123",
        label=RouteLabel.ORIGINAL,
        mode=TravelMode.CAR,
        geometry=GeoLineString(coordinates=[(100.5, 13.7), (100.6, 13.8)]),
        distance_m=1000.0,
        duration_seconds=600.0,
        exposure=None,
        risk_level=RiskLevel.UNKNOWN,
        quality=DataQuality(status=DataStatus.FRESH),
        sources=[
            SourceProvenance(
                source_id="openrouteservice:abc123",
                provider="openrouteservice",
                authority=SourceAuthority.LICENSED_PROVIDER,
                observed_at=None,
            )
        ],
    ).model_dump(mode="json")

    assert _validate("route-candidate.schema.json", None, route) == []

    # The same record claiming low risk must be refused by the contract.
    route["risk_level"] = "LOW"
    assert _validate("route-candidate.schema.json", None, route) != []


def test_emergency_places_match_the_contract(
    emergency_places: list[dict[str, Any]],
) -> None:
    messages = _all_messages("emergency-poi.schema.json", emergency_places)
    assert _unexpected("emergency-poi.schema.json", messages) == []


def test_at_least_one_captured_place_has_no_name() -> None:
    """Guards the test above.

    If the fixture ever loses its unnamed hospitals, the nullable-name waiver
    stops being exercised and this file goes quiet about the one thing it was
    written to watch.
    """
    payload = _fixture("openrouteservice/pois_emergency_bangkok.json")
    unnamed = [
        f for f in payload["features"] if not (f["properties"].get("osm_tags") or {}).get("name")
    ]
    assert unnamed, "the captured POI fixture no longer contains an unnamed place"


@pytest.mark.parametrize(
    ("schema_file", "fixture_name"),
    [
        ("route-candidate.schema.json", "route_candidate"),
        ("emergency-poi.schema.json", "emergency_places"),
    ],
)
def test_a_closed_gap_is_reported_rather_than_forgotten(
    schema_file: str, fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """The ratchet.

    When the contract is fixed upstream, the corresponding entry in
    `OPEN_CONTRACT_GAPS` stops matching anything - and this fails, so the
    waiver gets deleted instead of quietly outliving the problem it excused.
    """
    if schema_file not in OPEN_CONTRACT_GAPS:
        pytest.skip("no waivers recorded for this schema")
    value = request.getfixturevalue(fixture_name)
    records = value if isinstance(value, list) else [value]
    messages = _all_messages(schema_file, records)
    stale = [
        gap
        for gap in OPEN_CONTRACT_GAPS[schema_file]
        if not any(gap in message for message in messages)
    ]
    assert stale == [], (
        f"these waivers in OPEN_CONTRACT_GAPS no longer match anything and "
        f"should be removed: {stale}"
    )


# ------------------------------------------------------- shared vocabulary


def test_every_enum_module_04_emits_exists_in_the_contract() -> None:
    """A value this module produces that the contract does not know about is a
    value no generated client can deserialise."""
    from app.domain import enums as module_enums

    contract = json.loads((CONTRACTS / "enums.schema.json").read_text(encoding="utf-8"))
    defined = contract.get("$defs", {})

    checked = 0
    for name in (
        "DataStatus",
        "Severity",
        "QualityFlag",
        "SourceAuthority",
        "TravelMode",
        "RiskLevel",
    ):
        ours = getattr(module_enums, name, None)
        theirs = defined.get(name, {}).get("enum")
        if ours is None or theirs is None:
            continue
        checked += 1
        missing = {member.value for member in ours} - set(theirs)
        assert missing == set(), f"{name}: module 04 emits {missing}, contract does not"
    assert checked >= 4, "the contract defines far fewer shared enums than expected"


def test_the_contract_directory_is_where_the_test_thinks_it_is() -> None:
    """Guards the skip above: a moved contract directory would make every test
    in this file skip silently, which is worse than failing."""
    assert (CONTRACTS / "enums.schema.json").is_file()
    assert (CONTRACTS / "source-provenance.schema.json").is_file()


def test_every_schema_file_in_the_contract_parses() -> None:
    for path in CONTRACTS.glob("*.schema.json"):
        assert json.loads(path.read_text(encoding="utf-8")), path.name


def test_the_poi_type_enum_gap_is_still_what_was_reported() -> None:
    """Checked directly rather than through a record.

    The captured Bangkok POIs are all HOSPITAL and POLICE, both of which the
    contract already knows, so no amount of validating them would reveal that
    OTHER, DOCTOR and TOWNHALL have nowhere to go. A waiver on a record that
    never produces the value is a waiver that protects nothing.

    OTHER is the one that matters: every other enum in the contract has an
    escape, and the rule that an unrecognised provider value maps to a known
    unknown cannot be followed without one.
    """
    from app.domain.enums import PlaceType

    schema = json.loads((CONTRACTS / "emergency-poi.schema.json").read_text(encoding="utf-8"))
    contract_values = set(schema["properties"]["poi_type"]["enum"])
    ours = {member.value for member in PlaceType}

    missing = sorted(ours - contract_values)
    assert missing == [], (
        f"module 04 emits {missing}, which the contract has no value for - a "
        "record carrying one cannot be deserialised by any generated client"
    )
