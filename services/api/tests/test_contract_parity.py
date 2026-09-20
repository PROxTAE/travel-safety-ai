"""The service's own types must agree with the shared contract.

`app/errors/codes.py` and `app/schemas/envelope.py` are hand-written rather than imported from the
generated models, because the handlers construct them and a hand-written model can carry this
service's own invariants. The cost of that choice is drift, so it is paid for here: if the contract
gains an error code or renames a field, these tests fail in this service rather than in a consumer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.errors.codes import ErrorCode, FieldErrorCode
from app.schemas.envelope import ErrorBody, PageMeta, ResponseMeta


def _find_contracts() -> Path:
    """Locate `packages/contracts`, from a checkout or from inside the container.

    In the container the service lives at `/app` and the repository root is not an ancestor, so
    walking up the tree finds nothing; compose mounts the folder and sets `CONTRACTS_DIR` instead.
    Resolving this defensively rather than by index also means a future move of this file cannot
    turn the parity check into an import error.
    """
    configured = os.environ.get("CONTRACTS_DIR")
    if configured:
        return Path(configured)

    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "packages" / "contracts"
        if candidate.is_dir():
            return candidate
    return Path("packages/contracts")


CONTRACTS = _find_contracts()
COMMON = CONTRACTS / "jsonschema" / "common"

pytestmark = pytest.mark.skipif(
    not COMMON.exists(),
    reason="packages/contracts is not present in this checkout",
)


def _schema(name: str) -> dict[str, Any]:
    return json.loads((COMMON / name).read_text(encoding="utf-8"))


def test_error_codes_match_the_contract_exactly() -> None:
    """A code this service can emit but the contract does not name is one no client handles."""
    contract = set(_schema("enums.schema.json")["$defs"]["ErrorCode"]["enum"])
    implemented = {code.value for code in ErrorCode}

    assert implemented == contract, (
        f"only in the service: {sorted(implemented - contract)}; "
        f"only in the contract: {sorted(contract - implemented)}"
    )


def test_field_error_codes_match_the_contract_exactly() -> None:
    contract = set(
        _schema("envelope.schema.json")["$defs"]["FieldError"]["properties"]["code"]["enum"]
    )
    implemented = {code.value for code in FieldErrorCode}

    assert implemented == contract


def test_response_meta_requires_what_the_contract_requires() -> None:
    contract = set(_schema("envelope.schema.json")["$defs"]["ResponseMeta"]["required"])
    required = {name for name, field in ResponseMeta.model_fields.items() if field.is_required()}

    assert (
        contract <= required
    ), f"contract requires fields this service treats as optional: {contract - required}"


def test_error_body_requires_what_the_contract_requires() -> None:
    contract = set(_schema("envelope.schema.json")["$defs"]["ErrorBody"]["required"])
    required = {name for name, field in ErrorBody.model_fields.items() if field.is_required()}

    assert contract <= required


def test_envelope_field_names_match() -> None:
    """A renamed field is a breaking change even when the type is unchanged."""
    contract_meta = set(_schema("envelope.schema.json")["$defs"]["ResponseMeta"]["properties"])
    contract_page = set(_schema("envelope.schema.json")["$defs"]["PageMeta"]["properties"])

    assert contract_meta == set(ResponseMeta.model_fields)
    assert contract_page == set(PageMeta.model_fields)


def test_degradation_reasons_match() -> None:
    """The UI maps each reason onto its own wording, so an unmapped value renders as nothing."""
    from typing import get_args

    from app.schemas.envelope import DegradationReason

    contract = set(_schema("envelope.schema.json")["$defs"]["DegradationReason"]["enum"])

    assert set(get_args(DegradationReason)) == contract


def test_public_api_declares_the_health_endpoints_this_service_serves() -> None:
    """The contract promises `/health/live` and `/health/ready`; the runbook curls both."""
    import yaml

    spec_path = CONTRACTS / "openapi" / "public-api.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

    assert "/health/live" in spec["paths"]
    assert "/health/ready" in spec["paths"]


# --- phase 4: the trip domain ---------------------------------------------------------------------


def test_trip_fields_match_the_contract() -> None:
    """A field this service omits is one the web client will find missing at integration time."""
    from app.schemas.trip import TripModel

    contract = set(_schema("trip.schema.json")["properties"])

    assert set(TripModel.model_fields) == contract


def test_trip_requires_what_the_contract_requires() -> None:
    from app.schemas.trip import TripModel

    required = set(_schema("trip.schema.json")["required"])
    non_optional = {name for name, field in TripModel.model_fields.items() if field.is_required()}

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_location_ref_fields_match_the_contract() -> None:
    from app.schemas.location import LocationRef

    contract = set(_schema("location-ref.schema.json")["properties"])

    assert set(LocationRef.model_fields) == contract


def test_location_ref_requires_what_the_contract_requires() -> None:
    """`confirmed_by_user` especially: it is what stops an unreviewed pin becoming a trip."""
    from app.schemas.location import LocationRef

    required = set(_schema("location-ref.schema.json")["required"])

    assert required <= set(LocationRef.model_fields)


def test_travel_preference_fields_match_the_contract() -> None:
    from app.schemas.trip import TravelPreference

    contract = set(_schema("travel-preference.schema.json")["properties"])

    assert set(TravelPreference.model_fields) == contract


def test_travel_modes_match_the_contract() -> None:
    """A mode the service accepts but the contract does not name cannot be assessed downstream."""
    from app.domain.trip import TRAVEL_MODES

    contract = set(_schema("enums.schema.json")["$defs"]["TravelMode"]["enum"])

    assert contract == TRAVEL_MODES


def test_trip_statuses_match_the_contract() -> None:
    from app.domain.trip import TRIP_STATUSES

    contract = set(_schema("enums.schema.json")["$defs"]["TripStatus"]["enum"])

    assert contract == TRIP_STATUSES


def test_deletion_statuses_match_the_contract() -> None:
    from typing import get_args

    from app.schemas.trip import DeletionStatus

    contract = set(_schema("enums.schema.json")["$defs"]["DeletionStatus"]["enum"])

    assert set(get_args(DeletionStatus)) == contract


def test_accessibility_needs_match_the_contract() -> None:
    from typing import get_args

    from app.schemas.trip import AccessibilityNeed

    contract = set(
        _schema("travel-preference.schema.json")["properties"]["accessibility"]["items"]["enum"]
    )

    assert set(get_args(AccessibilityNeed)) == contract


def test_the_public_contract_declares_every_trip_route_this_service_serves() -> None:
    """The endpoints phase 4 implements must be the ones the frozen contract promised."""
    import yaml

    spec = yaml.safe_load((CONTRACTS / "openapi" / "public-api.yaml").read_text(encoding="utf-8"))

    assert set(spec["paths"]["/api/v1/trips"]) >= {"get", "post"}
    assert set(spec["paths"]["/api/v1/trips/{trip_id}"]) >= {"get", "patch", "delete"}
    assert "get" in spec["paths"]["/api/v1/locations/search"]
