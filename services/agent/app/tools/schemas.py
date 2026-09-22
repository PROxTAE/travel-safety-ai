"""Typed request/response models for the two tools that have a published OpenAPI contract:
`data_integration.create_snapshot@1` and `risk_knowledge.build_evidence_package@1`
(`packages/contracts/openapi/internal-data-integration.yaml`,
`packages/contracts/openapi/internal-risk-knowledge.yaml`, and the JSON Schema files they `$ref`).

**This is a hand transcription, not a generated client.** `packages/contracts/generated/python`
is the real source of truth once the shared codegen pipeline covers these two services (see
`packages/contracts/scripts/generate-python.sh`); this module exists only because that pipeline's
output lives outside `services/agent/` and this service's work is scoped to stay inside it. Once
generated clients exist, replace these classes with an import from there — the same interim
arrangement `app/graph/state.py` already documents for `TravelRequest`/`LocationRef`.

`external_data.query_context@1`, `decision_engine.create_decision@1` and
`recommendation.create_recommendation@1` have **no** published OpenAPI contract yet
(`packages/contracts/openapi/` has only the two files named above), so there are no schemas for
them here — see `app/tools/registry.py` for how the registry represents that gap.

**Depth is deliberately uneven.** Where the agent actually reads a field back out of a response
(`snapshot_id`, `assessment_id`, `risk_level`, ...), it is typed and validated. Deeply nested
provider content the agent only carries as a reference — `IntegratedTravelContext`'s weather/
transport/disaster arrays, a `RouteCandidate`'s `segments`/`geometry` — is `extra="allow"` /
loosely typed rather than fully modeled. This matches `app/graph/state.py`'s own rule for
`AgentState` ("เก็บเฉพาะ reference (id, ref) ห้ามเก็บ raw payload ของ provider"): the agent was never
meant to be the second place that owns the exact shape of a weather record. Fully modeling it here
would itself be the duplicate-schema problem the plan warns against, transcribed from the wrong
owner (data-integration's copy, not external-data's, which has not even published one yet).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared primitives (packages/contracts/jsonschema/common/, risk-knowledge-contract.schema.json)
# ---------------------------------------------------------------------------


class DataQuality(BaseModel):
    """`packages/contracts/jsonschema/common/data-quality.schema.json` /
    risk-knowledge-contract.schema.json `#/$defs/DataQuality` (the two are compatible)."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["FRESH", "STALE", "UNAVAILABLE", "CONFLICTING", "PARTIAL"]
    score: float | None = Field(default=None, ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    coverage: float | None = Field(default=None, ge=0, le=1)
    completeness: float | None = Field(default=None, ge=0, le=1)
    freshness_seconds: int | None = Field(default=None, ge=0)
    conflicts: list[dict[str, object]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SourceProvenance(BaseModel):
    """risk-knowledge-contract.schema.json `#/$defs/SourceProvenance`."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    provider: str
    provider_record_id: str | None = None
    authority: Literal["OFFICIAL", "INTERGOVERNMENTAL", "LICENSED_PROVIDER", "COMMUNITY", "UNKNOWN"]
    source_url: str
    license: str
    attribution: str | None = None
    observed_at: AwareDatetime | None = None
    published_at: AwareDatetime | None = None
    fetched_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    content_hash: str
    schema_version: Literal["1.0.0"]


class RouteExposure(BaseModel):
    """risk-knowledge-contract.schema.json `#/$defs/RouteExposure`."""

    model_config = ConfigDict(extra="forbid")

    score: float | None = Field(default=None, ge=0, le=1)
    hazard_event_ids: list[str] = Field(default_factory=list)
    weather_window_ids: list[str] = Field(default_factory=list)
    closed: bool
    hard_constraint_codes: list[str] = Field(default_factory=list)


class RouteCandidate(BaseModel):
    """risk-knowledge-contract.schema.json `#/$defs/RouteCandidate`
    (00_API_AND_DATA_CONTRACTS.md §3.8). `additionalProperties: true` upstream — geometry/segments
    stay opaque per this module's docstring."""

    model_config = ConfigDict(extra="allow")

    route_id: UUID
    provider_route_id: str
    label: Literal["ORIGINAL", "RECOMMENDED", "FASTEST", "LOWEST_RISK", "ALTERNATIVE"]
    mode: Literal["FLIGHT", "TRAIN", "BUS", "CAR", "WALK", "BICYCLE", "MULTIMODAL"]
    geometry: dict[str, object]
    segments: list[dict[str, object]] = Field(default_factory=list)
    distance_m: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    transfers: int = Field(ge=0)
    exposure: RouteExposure | None = None
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    quality: DataQuality
    sources: list[SourceProvenance] = Field(default_factory=list)


class ModelReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    feature_schema_version: Literal["1.0.0"]
    artifact_checksum: str | None = None


class SafetyOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "OFFICIAL_CLOSURE",
        "OFFICIAL_EVACUATION",
        "EXTREME_WARNING_CORRIDOR",
        "MISSING_CRITICAL_EVIDENCE",
        "OFFICIAL_SOURCE_CONFLICT",
    ]
    applied_risk_level: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    source_ids: list[UUID] = Field(default_factory=list)
    policy_version: str


class CapabilityState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: Literal["RISK_MODEL", "KNOWLEDGE_RETRIEVAL", "ROUTE_EVALUATION"]
    status: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE", "WARMING"]
    version: str | None = None
    reason: str | None = None


#: risk-knowledge-contract.schema.json `#/$defs/LimitationCode`.
LimitationCode = Annotated[
    Literal[
        "NO_RELIABLE_KNOWLEDGE_EVIDENCE",
        "MODEL_UNAVAILABLE",
        "MODEL_ARTIFACT_INVALID",
        "FEATURE_SCHEMA_UNSUPPORTED",
        "KNOWLEDGE_COLLECTION_UNAVAILABLE",
        "ROUTE_RANKING_UNAVAILABLE",
        "INSUFFICIENT_EVIDENCE",
        "DEPENDENCY_UNAVAILABLE",
    ],
    Field(),
]


class RiskAssessment(BaseModel):
    """risk-knowledge-contract.schema.json `#/$defs/RiskAssessment`."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: UUID
    snapshot_id: UUID
    route_id: UUID
    score: float | None = Field(default=None, ge=0, le=1)
    probability_high: float | None = Field(default=None, ge=0, le=1)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    uncertainty: float | None = Field(default=None, ge=0, le=1)
    reason_codes: list[str] = Field(min_length=1)
    safety_overrides: list[SafetyOverride] = Field(default_factory=list)
    model: ModelReference
    quality: DataQuality
    created_at: AwareDatetime


class RetrievedEvidence(BaseModel):
    """risk-knowledge-contract.schema.json `#/$defs/RetrievedEvidence`
    (00_API_AND_DATA_CONTRACTS.md §3.11)."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    document_id: str
    authority: Literal["OFFICIAL", "INTERGOVERNMENTAL", "LICENSED_PROVIDER", "COMMUNITY", "UNKNOWN"]
    title: str
    source_url: str
    page: int | None = None
    section: str | None = None
    language: str
    effective_at: AwareDatetime
    expires_at: AwareDatetime
    passage: str
    retrieval_score: float = Field(ge=0, le=1)
    rerank_score: float = Field(ge=0, le=1)
    collection_version: str
    content_hash: str


class StandardMeta(BaseModel):
    """risk-knowledge-contract.schema.json `#/$defs/StandardMeta`."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    correlation_id: UUID
    contract_version: Literal["1.0.0"]
    generated_at: AwareDatetime
    degraded_services: list[str] = Field(default_factory=list)


class ToolErrorBody(BaseModel):
    """Compatible with both services' error envelopes
    (`packages/contracts/jsonschema/common/envelope.schema.json#/$defs/ErrorBody` and
    risk-knowledge-contract.schema.json `#/$defs/ErrorEnvelope`)."""

    model_config = ConfigDict(extra="ignore")

    code: str
    message: str
    field_errors: list[dict[str, object]] = Field(default_factory=list)
    retryable: bool
    retry_after_seconds: int | None = None


class ToolErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: ToolErrorBody


# ---------------------------------------------------------------------------
# data_integration.create_snapshot@1 (internal-data-integration.yaml)
# ---------------------------------------------------------------------------


class TravelWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: AwareDatetime
    ends_at: AwareDatetime
    timezone: str


class SnapshotEvidence(BaseModel):
    """`internal-data-integration.yaml#/components/schemas/Evidence`. `null` means the source was
    unavailable; `[]` means it answered with nothing — the two are not the same and both must
    reach data-integration exactly as received, never substituted for each other. The canonical
    weather/transport/disaster record shapes belong to external-data (00_API_AND_DATA_CONTRACTS.md
    §3.5-§3.7); they are not this module's to model (see the module docstring)."""

    model_config = ConfigDict(extra="forbid")

    weather: list[dict[str, object]] | None
    disaster_events: list[dict[str, object]] | None
    transport: list[dict[str, object]] | None


class SnapshotCreateRequest(BaseModel):
    """`internal-data-integration.yaml#/components/schemas/SnapshotCreateRequest`. One route
    candidate per request — one snapshot describes one route, per the spec's own description."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    trip_id: UUID
    supersedes_snapshot_id: UUID | None = None
    travel_window: TravelWindow
    recommendation_at: AwareDatetime
    route: RouteCandidate
    evidence: SnapshotEvidence
    source_quality: dict[str, DataQuality]


class DataIntegrationMeta(BaseModel):
    """`envelope.schema.json#/$defs/ResponseMeta` — distinct from `StandardMeta`:
    `correlation_id` is nullable here and `degraded_services` defaults to empty rather than being
    required, matching data-integration's own contract exactly rather than risk-knowledge's."""

    model_config = ConfigDict(extra="ignore")

    request_id: UUID
    correlation_id: UUID | None = None
    contract_version: str
    generated_at: AwareDatetime
    degraded_services: list[dict[str, object]] = Field(default_factory=list)


class SnapshotResponseData(BaseModel):
    """The subset of `IntegratedTravelContext` this client actually reads. `extra="allow"` for
    everything else — see the module docstring."""

    model_config = ConfigDict(extra="allow")

    snapshot_id: UUID
    request_id: UUID
    trip_id: UUID
    schema_version: str
    content_hash: str
    quality_summary: DataQuality
    supersedes_snapshot_id: UUID | None = None
    created_at: AwareDatetime


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: SnapshotResponseData
    meta: DataIntegrationMeta


class SnapshotValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strict: bool = False


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    valid: bool
    schema_valid: bool
    content_hash_matches: bool
    gate: Literal["PASS", "DEGRADED", "BLOCK"]
    flags: list[str] = Field(default_factory=list)
    missing_critical: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class ValidationReportResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: ValidationReport
    meta: DataIntegrationMeta


# ---------------------------------------------------------------------------
# risk_knowledge.build_evidence_package@1 (internal-risk-knowledge.yaml)
# ---------------------------------------------------------------------------


class EvidencePackageRequest(BaseModel):
    """`internal-risk-knowledge.yaml#/components/schemas/EvidencePackageRequest`."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    locale: str
    route_ids: list[UUID] = Field(default_factory=list)


class EvidencePackageVersions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal["1.0.0"]
    feature_schema: str
    model: str | None = None
    thresholds: str | None = None
    route_policy: str
    knowledge_collection: str | None = None


class EvidencePackageData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    assessments: list[RiskAssessment]
    evidence: list[RetrievedEvidence]
    routes: list[RouteCandidate]
    capabilities: list[CapabilityState]
    limitations: list[LimitationCode] = Field(default_factory=list)
    versions: EvidencePackageVersions


class EvidencePackageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: EvidencePackageData
    meta: StandardMeta
