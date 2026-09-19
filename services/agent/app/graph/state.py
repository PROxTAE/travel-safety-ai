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
contract), replace these two classes with an import from there instead of
keeping a second copy, per the "generate once, don't hand-copy" rule in the
contracts doc.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


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


class LocationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: str
    display_name: str
    # GeoJSON Point: coordinates = [longitude, latitude]
    coordinates: dict[str, Any]
    country_code: str
    admin1: str | None = None
    timezone: str
    provider: str
    confirmed_by_user: bool = False


class TravelPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefer_safer_route: bool = True
    prefer_lower_cost: bool = False
    prefer_lower_emissions: bool = False
    max_extra_duration_minutes: int | None = None
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
    departure_time: datetime
    return_time: datetime | None = None
    travel_modes: list[TravelMode] = Field(min_length=1)
    preferences: TravelPreferences = Field(default_factory=TravelPreferences)
    question: str | None = Field(default=None, max_length=2000)
    locale: str
    timezone: str
    live_location_consent_id: UUID | None = None


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
    MAX_ESTIMATED_COST_USD on every node transition (see tool_io_matrix.md
    section 3). This is what guarantees "no unlimited loop".
    """

    model_config = ConfigDict(extra="forbid")

    status: RunStatus = RunStatus.QUEUED
    errors: list[str] = Field(default_factory=list)
    step_count: int = 0
    tool_call_count: int = 0
    token_usage: int = 0
    estimated_cost: float = 0.0
    started_at: datetime
    deadline_at: datetime
    cancelled: bool = False
    remaining_budget: dict[str, int] = Field(default_factory=dict)


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
