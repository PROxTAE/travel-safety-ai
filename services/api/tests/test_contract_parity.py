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
