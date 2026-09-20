from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class DataStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICTING = "CONFLICTING"
    PARTIAL = "PARTIAL"


class Severity(StrEnum):
    INFO = "INFO"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class DataQuality(StrictModel):
    status: DataStatus
    score: float | None = Field(ge=0, le=1)
    flags: list[
        Literal[
            "MISSING",
            "STALE",
            "CONFLICTING",
            "INFERRED",
            "INCOMPLETE",
            "OUTSIDE_COVERAGE",
        ]
    ]
    coverage: float | None = Field(ge=0, le=1)
    completeness: float | None = Field(ge=0, le=1)
    freshness_seconds: int | None = Field(ge=0)
    conflicts: list[str]
    notes: list[str]


class SourceProvenance(StrictModel):
    source_id: UUID
    provider: str
    provider_record_id: str | None
    authority: Literal["OFFICIAL", "INTERGOVERNMENTAL", "LICENSED_PROVIDER", "COMMUNITY", "UNKNOWN"]
    source_url: HttpUrl
    license: str
    observed_at: datetime | None
    published_at: datetime | None
    fetched_at: datetime
    expires_at: datetime | None
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    schema_version: Literal["1.0.0"]


class RouteExposure(StrictModel):
    score: float | None = Field(ge=0, le=1)
    hazard_event_ids: list[str]
    weather_window_ids: list[str]
    closed: bool
    hard_constraint_codes: list[
        Literal["OFFICIAL_CLOSURE", "OFFICIAL_NO_GO", "EVACUATION_DIRECTION_CONFLICT"]
    ] = Field(default_factory=list)


class RouteCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    route_id: UUID
    provider_route_id: str
    label: Literal["ORIGINAL", "RECOMMENDED", "FASTEST", "LOWEST_RISK", "ALTERNATIVE"]
    mode: Literal["FLIGHT", "TRAIN", "BUS", "CAR", "WALK", "BICYCLE", "MULTIMODAL"]
    geometry: dict[str, Any]
    segments: list[dict[str, Any]]
    distance_m: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    transfers: int = Field(ge=0)
    exposure: RouteExposure
    risk_level: RiskLevel
    quality: DataQuality
    sources: list[SourceProvenance]


class OfficialAlert(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    event_type: str | None = None
    severity: Severity
    official: Literal[True]
    effective_at: datetime
    ends_at: datetime | None
    affected_route_ids: list[UUID] = Field(default_factory=list)
    closure: bool = False
    evacuation: bool = False
    source: SourceProvenance

    def is_active_during(self, starts_at: datetime, ends_at: datetime) -> bool:
        alert_end = self.ends_at or datetime.max.replace(tzinfo=starts_at.tzinfo)
        return self.effective_at <= ends_at and alert_end >= starts_at


class TravelWindow(StrictModel):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_order(self) -> TravelWindow:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class IntegratedTravelContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    snapshot_id: UUID
    request_id: UUID
    trip_id: UUID
    schema_version: Literal["1.0.0"]
    feature_schema_version: Literal["1.0.0"]
    travel_window: TravelWindow
    route_candidates: list[RouteCandidate] = Field(min_length=1)
    route_corridor_geojson: dict[str, Any]
    weather: list[dict[str, Any]]
    transport: list[dict[str, Any]]
    disaster_events: list[dict[str, Any]]
    official_alerts: list[OfficialAlert]
    features: dict[str, float | int | bool | str | None]
    quality_summary: DataQuality
    conflict_summary: list[str]
    source_ids: list[UUID]
    created_at: datetime
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    supersedes_snapshot_id: UUID | None = None


def validate_route_selection(snapshot: IntegratedTravelContext, route_ids: list[UUID]) -> None:
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("route_ids must not contain duplicates")

    candidates = {route.route_id for route in snapshot.route_candidates}
    if set(route_ids) - candidates:
        raise ValueError("route_ids must all exist in snapshot.route_candidates")


class RiskAssessRequest(StrictModel):
    snapshot: IntegratedTravelContext
    route_ids: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_route_ids(self) -> RiskAssessRequest:
        validate_route_selection(self.snapshot, self.route_ids)
        return self


class KnowledgeRetrieveRequest(StrictModel):
    hazards: list[str] = Field(min_length=1)
    country_codes: list[str] = Field(min_length=1)
    admin1: str | None = None
    action_code: Literal["NORMAL", "CHANGE_ROUTE", "DELAY", "AVOID"]
    locale: str = Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    at: datetime
    limit: int = Field(default=5, ge=1, le=20)


class RouteEvaluateRequest(StrictModel):
    snapshot: IntegratedTravelContext
    route_ids: list[UUID] = Field(min_length=1)
    avoid_geometries: list[dict[str, Any]]
    preferences: dict[str, Any]

    @model_validator(mode="after")
    def validate_route_ids(self) -> RouteEvaluateRequest:
        validate_route_selection(self.snapshot, self.route_ids)
        return self


class EvidencePackageRequest(StrictModel):
    snapshot_id: UUID
    locale: str = Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    route_ids: list[UUID] = Field(default_factory=list)


class SafetyOverride(StrictModel):
    code: Literal[
        "OFFICIAL_CLOSURE",
        "OFFICIAL_EVACUATION",
        "EXTREME_WARNING_CORRIDOR",
        "MISSING_CRITICAL_EVIDENCE",
        "OFFICIAL_SOURCE_CONFLICT",
    ]
    applied_risk_level: RiskLevel
    source_ids: list[UUID]
    policy_version: str


class ModelReference(StrictModel):
    name: str
    version: str
    feature_schema_version: Literal["1.0.0"]
    artifact_checksum: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class RiskAssessment(StrictModel):
    assessment_id: UUID
    snapshot_id: UUID
    route_id: UUID
    score: float | None = Field(ge=0, le=1)
    probability_high: float | None = Field(ge=0, le=1)
    risk_level: RiskLevel
    uncertainty: float | None = Field(ge=0, le=1)
    reason_codes: list[
        Literal[
            "OFFICIAL_CLOSURE",
            "OFFICIAL_EVACUATION",
            "EXTREME_WARNING_CORRIDOR",
            "SEVERE_WEATHER_CORRIDOR",
            "DISASTER_CORRIDOR_INTERSECTION",
            "TRANSPORT_DISRUPTION",
            "LIMITED_CRITICAL_COVERAGE",
            "STALE_CRITICAL_EVIDENCE",
            "CONFLICTING_OFFICIAL_EVIDENCE",
            "MODEL_UNAVAILABLE",
            "FEATURE_SCHEMA_MISMATCH",
            "NO_USABLE_ROUTE",
            "FALLBACK_RULE_APPLIED",
        ]
    ]
    safety_overrides: list[SafetyOverride]
    model: ModelReference
    quality: DataQuality
    created_at: datetime


class CapabilityState(StrictModel):
    capability: Literal["RISK_MODEL", "KNOWLEDGE_RETRIEVAL", "ROUTE_EVALUATION"]
    status: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE", "WARMING"]
    version: str | None
    reason: str | None


class StandardMeta(StrictModel):
    request_id: UUID
    correlation_id: UUID
    contract_version: Literal["1.0.0"] = "1.0.0"
    generated_at: datetime
    degraded_services: list[str]


class RiskAssessData(StrictModel):
    assessments: list[RiskAssessment]
    capability: CapabilityState
    limitations: list[str]


class RiskAssessResponse(StrictModel):
    data: RiskAssessData
    meta: StandardMeta


class KnowledgeRetrieveData(StrictModel):
    evidence: list[dict[str, Any]]
    capability: CapabilityState
    limitations: list[str]


class KnowledgeRetrieveResponse(StrictModel):
    data: KnowledgeRetrieveData
    meta: StandardMeta


class RouteEvaluateData(StrictModel):
    routes: list[RouteCandidate]
    unusable_route_ids: list[UUID]
    capability: CapabilityState
    policy_version: str
    limitations: list[str]


class RouteEvaluateResponse(StrictModel):
    data: RouteEvaluateData
    meta: StandardMeta


class ModelStatusData(StrictModel):
    status: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE", "WARMING"]
    reason: str | None
    model: ModelReference | None


class ModelStatusResponse(StrictModel):
    data: ModelStatusData
    meta: StandardMeta


class KnowledgeStatusData(StrictModel):
    status: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE", "WARMING"]
    reason: str | None
    collection_version: str | None
    document_cutoff: datetime | None


class KnowledgeStatusResponse(StrictModel):
    data: KnowledgeStatusData
    meta: StandardMeta
