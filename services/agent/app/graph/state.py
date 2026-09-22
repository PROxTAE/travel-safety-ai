"""AgentState schema for the LangGraph finite state machine.

Target location in repo: services/agent/app/graph/state.py

Design rules (from IMPLEMENTATION_PLANS/03_TRAVEL_AI_AGENT_IMPLEMENTATION.md):
  - Must be serializable (checkpointer persists this). No DataFrames, no
    client objects, no secrets.
  - Store references/metadata (snapshot_id, evidence_package_ref, ...),
    never duplicate provider raw payloads or sensitive profile data here.
  - `status` values and other enums must match
    IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md exactly so the public
    API (module 02) and this agent never disagree on wire values.

NOTE: TravelRequest / LocationRef below are minimal local re-declarations of
the shared contract so this module is self-contained for Phase 0/1. Once
`packages/contracts/generated/python` exists (after @02-api merges the
contract), replace these classes with an import from there instead of
keeping a second copy, per the "generate once, don't hand-copy" rule in the
contracts doc.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Shared enums (mirrors 00_API_AND_DATA_CONTRACTS.md section 2 verbatim —
# values must stay uppercase and byte-for-byte identical to the contract).
# ---------------------------------------------------------------------------


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class ActionCode(StrEnum):
    NORMAL = "NORMAL"
    CHANGE_ROUTE = "CHANGE_ROUTE"
    DELAY = "DELAY"
    AVOID = "AVOID"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    NEEDS_INPUT = "NEEDS_INPUT"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TravelMode(StrEnum):
    FLIGHT = "FLIGHT"
    TRAIN = "TRAIN"
    BUS = "BUS"
    CAR = "CAR"
    WALK = "WALK"
    BICYCLE = "BICYCLE"
    MULTIMODAL = "MULTIMODAL"


class DataStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICTING = "CONFLICTING"
    PARTIAL = "PARTIAL"


class QualityFlag(StrEnum):
    MISSING = "MISSING"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"
    INFERRED = "INFERRED"
    INCOMPLETE = "INCOMPLETE"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"


class Intent(StrEnum):
    """Agent-specific intent taxonomy (03_TRAVEL_AI_AGENT_IMPLEMENTATION.md,
    Phase 0 step 3). Not part of the cross-service contract — internal to
    this service only."""

    PLAN_TRIP = "PLAN_TRIP"
    CHECK_SAFETY = "CHECK_SAFETY"
    ASK_INFORMATION = "ASK_INFORMATION"
    FOLLOW_UP = "FOLLOW_UP"
    EMERGENCY = "EMERGENCY"


class GraphStage(StrEnum):
    """SSE-visible stage values, must match 00_API_AND_DATA_CONTRACTS.md
    section 6 (SSE contract) exactly — module 02 forwards these to the
    browser as run.progress.stage."""

    VALIDATING = "VALIDATING"
    FETCHING_EXTERNAL_DATA = "FETCHING_EXTERNAL_DATA"
    INTEGRATING_DATA = "INTEGRATING_DATA"
    ASSESSING_RISK = "ASSESSING_RISK"
    RETRIEVING_GUIDANCE = "RETRIEVING_GUIDANCE"
    EVALUATING_ROUTES = "EVALUATING_ROUTES"
    MAKING_DECISION = "MAKING_DECISION"
    EXPLAINING = "EXPLAINING"
    FORMATTING_RESPONSE = "FORMATTING_RESPONSE"


# ---------------------------------------------------------------------------
# Minimal contract re-declarations — replace with generated import later.
# ---------------------------------------------------------------------------


class GeoPoint(BaseModel):
    """GeoJSON Point (RFC 7946): coordinates = (longitude, latitude)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def _check_lon_lat_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        longitude, latitude = value
        if not -180.0 <= longitude <= 180.0:
            raise ValueError("longitude must be within [-180, 180]")
        if not -90.0 <= latitude <= 90.0:
            raise ValueError("latitude must be within [-90, 90]")
        return value


class LocationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: str
    display_name: str
    coordinates: GeoPoint
    # ISO-3166-1 alpha-2, uppercase
    country_code: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    admin1: str | None = None
    timezone: str
    provider: str
    confirmed_by_user: bool = False


class TravelPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer_safer_route: bool = True
    prefer_lower_cost: bool = False
    prefer_lower_emissions: bool = False
    max_extra_duration_minutes: int | None = Field(default=None, ge=0)
    avoid_tolls: bool = False
    accessibility: list[str] = Field(default_factory=list)


class TravelRequest(BaseModel):
    """Normalized request as received from module 02 (public API)."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    trip_id: UUID
    conversation_id: UUID | None = None
    origin: LocationRef
    destination: LocationRef
    # Timezone-aware: the contract sends an offset (e.g. +07:00) with every time.
    departure_time: AwareDatetime
    return_time: AwareDatetime | None = None
    travel_modes: list[TravelMode] = Field(min_length=1)
    preferences: TravelPreferences = Field(default_factory=TravelPreferences)
    question: str | None = Field(default=None, max_length=2000)
    locale: str
    timezone: str
    live_location_consent_id: UUID | None = None

    @model_validator(mode="after")
    def _return_after_departure(self) -> Self:
        if self.return_time is not None and self.return_time <= self.departure_time:
            raise ValueError("return_time must be later than departure_time")
        return self


# ---------------------------------------------------------------------------
# AgentState — the checkpointed graph state, grouped exactly as specced.
# ---------------------------------------------------------------------------


class IdentitySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    correlation_id: UUID
    trip_id: UUID
    conversation_id: UUID | None = None
    # Hash, never the raw subject/user id, per redaction rules.
    user_scope_hash: str


class InputSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    travel_request: TravelRequest
    approved_context_refs: list[str] = Field(default_factory=list)
    intent: Intent | None = None
    missing_fields: list[str] = Field(default_factory=list)


class PlanSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_version: str
    required_tools: list[str] = Field(default_factory=list)
    current_stage: GraphStage | None = None


class ObservationsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_context_ref: str | None = None
    snapshot_id: UUID | None = None
    evidence_package_ref: str | None = None


class ResultSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_assessments: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    route_ids: list[UUID] = Field(default_factory=list)
    decision_id: UUID | None = None
    recommendation_id: UUID | None = None


class QualitySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quality_flags: list[QualityFlag] = Field(default_factory=list)
    degraded_services: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    freshness: DataStatus = DataStatus.FRESH


class ControlSection(BaseModel):
    """Everything the budget/stop-condition logic reads and writes.

    step_count / tool_call_count / token_usage / estimated_cost are compared
    against MAX_AGENT_STEPS / MAX_TOOL_CALLS / MAX_LLM_CALLS /
    MAX_ESTIMATED_COST_USD on every node transition (plan section "Budgets
    and stop conditions"). This is what guarantees "no unlimited loop".

    `errors` holds stable error codes only (never raw provider messages).
    """

    model_config = ConfigDict(extra="forbid")

    status: RunStatus = RunStatus.QUEUED
    errors: list[str] = Field(default_factory=list)
    step_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    token_usage: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0.0)
    #: How many times `validate_evidence` has found the evidence package insufficient (Phase 4,
    #: app/graph/nodes/validate_evidence.py). Distinct from `step_count`: this counts only trips
    #: around the graph's one back-edge (`validate_evidence -> build_evidence`), which is what lets
    #: `Settings.evidence_retry_max` bound that loop specifically rather than borrowing a counter
    #: meant for something else (see the Phase 1 docstring this field replaces, in git history).
    evidence_retry_count: int = Field(default=0, ge=0)
    started_at: AwareDatetime
    deadline_at: AwareDatetime
    cancelled: bool = False
    remaining_budget: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _deadline_after_start(self) -> Self:
        if self.deadline_at <= self.started_at:
            raise ValueError("deadline_at must be later than started_at")
        return self


class VersionsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str
    graph: str
    prompt: str | None = None
    policy: str | None = None
    provider_configs: dict[str, str] = Field(default_factory=dict)


class AgentState(BaseModel):
    """Top-level checkpointed state for a single agent run.

    One instance per `agent.runs` row / LangGraph thread. Must round-trip
    through the PostgreSQL checkpointer with model_dump_json() /
    model_validate_json() with no loss — do not add non-serializable fields.
    """

    model_config = ConfigDict(extra="forbid")

    identity: IdentitySection
    input: InputSection
    plan: PlanSection
    observations: ObservationsSection = Field(default_factory=ObservationsSection)
    result: ResultSection = Field(default_factory=ResultSection)
    quality: QualitySection = Field(default_factory=QualitySection)
    control: ControlSection
    versions: VersionsSection
