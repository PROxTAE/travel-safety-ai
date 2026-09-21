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


# --- phase 5: assessment runs ---------------------------------------------------------------------


def test_run_statuses_match_the_contract() -> None:
    """A status the state machine knows but the contract does not name is one no client handles."""
    from typing import get_args

    from app.domain.run import RunStatus

    contract = set(_schema("enums.schema.json")["$defs"]["RunStatus"]["enum"])

    assert set(get_args(RunStatus)) == contract


def test_run_stages_match_the_contract() -> None:
    from typing import get_args

    from app.domain.run import RunStage

    contract = set(_schema("enums.schema.json")["$defs"]["RunStage"]["enum"])

    assert set(get_args(RunStage)) == contract


def test_run_ref_fields_match_the_contract() -> None:
    from app.schemas.run import RunRefModel

    contract = set(_schema("run-ref.schema.json")["properties"])

    assert set(RunRefModel.model_fields) == contract


def test_run_ref_requires_what_the_contract_requires() -> None:
    from app.schemas.run import RunRefModel

    required = set(_schema("run-ref.schema.json")["required"])
    non_optional = {name for name, field in RunRefModel.model_fields.items() if field.is_required()}

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_run_state_fields_match_the_contract() -> None:
    from app.schemas.run import RunStateModel

    contract = set(_schema("run-state.schema.json")["properties"])

    assert set(RunStateModel.model_fields) == contract


def test_run_state_requires_what_the_contract_requires() -> None:
    from app.schemas.run import RunStateModel

    required = set(_schema("run-state.schema.json")["required"])
    non_optional = {
        name for name, field in RunStateModel.model_fields.items() if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_every_sse_event_in_the_contract_has_a_model() -> None:
    """An event with no model is an event the bridge would drop, silently, at runtime."""
    import re

    from app.schemas.run import SSE_PAYLOAD_MODELS

    defs = _schema("sse-events.schema.json")["$defs"]

    def wire_name(schema_name: str) -> str:
        """`RunNeedsInput` in the schema is `run.needs_input` on the wire."""
        if schema_name == "Heartbeat":
            return "heartbeat"
        rest = schema_name.removeprefix("Run")
        return "run." + re.sub(r"(?<!^)(?=[A-Z])", "_", rest).lower()

    expected = {wire_name(name) for name in defs}

    assert set(SSE_PAYLOAD_MODELS) == expected


@pytest.mark.parametrize(
    ("event_name", "model_name"),
    [
        ("run.accepted", "RunAccepted"),
        ("run.progress", "RunProgress"),
        ("run.needs_input", "RunNeedsInput"),
        ("run.degraded", "RunDegraded"),
        ("run.completed", "RunCompleted"),
        ("run.failed", "RunFailed"),
        ("heartbeat", "Heartbeat"),
    ],
)
def test_sse_payload_fields_match_the_contract(event_name: str, model_name: str) -> None:
    from app.schemas.run import SSE_PAYLOAD_MODELS

    contract = set(_schema("sse-events.schema.json")["$defs"][model_name]["properties"])
    model = SSE_PAYLOAD_MODELS[event_name]

    assert set(model.model_fields) == contract


def test_recommendation_response_fields_match_the_contract() -> None:
    """What this service revalidates must be the whole object, not a convenient subset."""
    from app.schemas.recommendation import RecommendationResponseModel

    contract = set(_schema("recommendation-response.schema.json")["properties"])

    assert set(RecommendationResponseModel.model_fields) == contract


def test_recommendation_response_requires_what_the_contract_requires() -> None:
    from app.schemas.recommendation import RecommendationResponseModel

    required = set(_schema("recommendation-response.schema.json")["required"])
    non_optional = {
        name
        for name, field in RecommendationResponseModel.model_fields.items()
        if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_action_codes_and_risk_levels_match_the_contract() -> None:
    from typing import get_args

    from app.schemas.recommendation import ActionCode, RiskLevel

    enums = _schema("enums.schema.json")["$defs"]

    assert set(get_args(ActionCode)) == set(enums["ActionCode"]["enum"])
    assert set(get_args(RiskLevel)) == set(enums["RiskLevel"]["enum"])


def test_the_public_contract_declares_every_run_route_this_service_serves() -> None:
    """The endpoints phase 5 implements must be the ones the frozen contract promised."""
    import yaml

    spec = yaml.safe_load((CONTRACTS / "openapi" / "public-api.yaml").read_text(encoding="utf-8"))

    assert "post" in spec["paths"]["/api/v1/trips/{trip_id}/assessments"]
    assert set(spec["paths"]["/api/v1/runs/{request_id}"]) >= {"get", "delete"}
    assert "get" in spec["paths"]["/api/v1/runs/{request_id}/events"]


# --- phase 6: remaining facades -------------------------------------------------------------------


def test_conversation_fields_match_the_contract() -> None:
    from app.schemas.conversation import ConversationModel

    contract = set(_schema("conversation.schema.json")["properties"])

    assert set(ConversationModel.model_fields) == contract


def test_conversation_requires_what_the_contract_requires() -> None:
    from app.schemas.conversation import ConversationModel

    required = set(_schema("conversation.schema.json")["required"])
    non_optional = {
        name for name, field in ConversationModel.model_fields.items() if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_safety_event_fields_match_the_contract() -> None:
    from app.schemas.safety import SafetyEventModel

    contract = set(_schema("safety-event.schema.json")["properties"])

    assert set(SafetyEventModel.model_fields) == contract


def test_safety_event_requires_what_the_contract_requires() -> None:
    from app.schemas.safety import SafetyEventModel

    required = set(_schema("safety-event.schema.json")["required"])
    non_optional = {
        name for name, field in SafetyEventModel.model_fields.items() if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_official_contact_fields_match_the_contract() -> None:
    from app.schemas.emergency import OfficialContactModel

    contract = set(_schema("official-contact.schema.json")["properties"])

    assert set(OfficialContactModel.model_fields) == contract


def test_official_contact_requires_what_the_contract_requires() -> None:
    from app.schemas.emergency import OfficialContactModel

    required = set(_schema("official-contact.schema.json")["required"])
    non_optional = {
        name for name, field in OfficialContactModel.model_fields.items() if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_emergency_poi_fields_match_the_contract() -> None:
    from app.schemas.emergency import EmergencyPoiModel

    contract = set(_schema("emergency-poi.schema.json")["properties"])

    assert set(EmergencyPoiModel.model_fields) == contract


def test_emergency_poi_requires_what_the_contract_requires() -> None:
    from app.schemas.emergency import EmergencyPoiModel

    required = set(_schema("emergency-poi.schema.json")["required"])
    non_optional = {
        name for name, field in EmergencyPoiModel.model_fields.items() if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_feedback_event_fields_match_the_contract() -> None:
    from app.schemas.feedback import FeedbackEventModel

    contract = set(_schema("feedback-event.schema.json")["properties"])

    assert set(FeedbackEventModel.model_fields) == contract


def test_feedback_event_requires_what_the_contract_requires() -> None:
    from app.schemas.feedback import FeedbackEventModel

    required = set(_schema("feedback-event.schema.json")["required"])
    non_optional = {
        name for name, field in FeedbackEventModel.model_fields.items() if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_alert_subscription_fields_match_the_contract() -> None:
    from app.schemas.feedback import AlertSubscriptionModel

    contract = set(_schema("alert-subscription.schema.json")["properties"])

    assert set(AlertSubscriptionModel.model_fields) == contract


def test_alert_subscription_requires_what_the_contract_requires() -> None:
    from app.schemas.feedback import AlertSubscriptionModel

    required = set(_schema("alert-subscription.schema.json")["required"])
    non_optional = {
        name for name, field in AlertSubscriptionModel.model_fields.items() if field.is_required()
    }

    missing = required - non_optional
    assert not missing, f"optional here but required by the contract: {sorted(missing)}"


def test_phase6_enums_match_the_contract() -> None:
    from typing import get_args

    from app.schemas.emergency import EmergencyPoiType, EmergencyServiceType, SourceAuthority
    from app.schemas.feedback import DeliveryChannel, FeedbackCategory, SubscriptionStatus
    from app.schemas.safety import SafetyLayer

    enums = _schema("enums.schema.json")["$defs"]

    assert set(get_args(SafetyLayer)) == set(enums["SafetyLayer"]["enum"])
    assert set(get_args(EmergencyServiceType)) == set(enums["EmergencyServiceType"]["enum"])
    poi_schema = _schema("emergency-poi.schema.json")
    assert set(get_args(EmergencyPoiType)) == set(poi_schema["properties"]["poi_type"]["enum"])
    assert set(get_args(SourceAuthority)) == set(enums["SourceAuthority"]["enum"])
    assert set(get_args(FeedbackCategory)) == set(enums["FeedbackCategory"]["enum"])
    assert set(get_args(DeliveryChannel)) == set(enums["DeliveryChannel"]["enum"])
    assert set(get_args(SubscriptionStatus)) == set(enums["SubscriptionStatus"]["enum"])


def test_the_public_contract_declares_every_phase6_route_this_service_serves() -> None:
    import yaml

    spec = yaml.safe_load((CONTRACTS / "openapi" / "public-api.yaml").read_text(encoding="utf-8"))

    assert "get" in spec["paths"]["/api/v1/recommendations/{recommendation_id}"]
    assert "post" in spec["paths"]["/api/v1/trips/{trip_id}/apply-route"]
    assert "get" in spec["paths"]["/api/v1/conversations"]
    assert "post" in spec["paths"]["/api/v1/conversations/{conversation_id}/messages"]
    assert "get" in spec["paths"]["/api/v1/safety/events"]
    assert "get" in spec["paths"]["/api/v1/emergency/contacts"]
    assert "get" in spec["paths"]["/api/v1/emergency/nearby"]
    assert "post" in spec["paths"]["/api/v1/feedback"]
    assert "post" in spec["paths"]["/api/v1/alert-subscriptions"]
    assert "delete" in spec["paths"]["/api/v1/alert-subscriptions/{subscription_id}"]
