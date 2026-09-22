from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ActionCode(StrEnum):
    NORMAL = "NORMAL"
    CHANGE_ROUTE = "CHANGE_ROUTE"
    DELAY = "DELAY"
    AVOID = "AVOID"


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


class Quality(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: DataStatus
    score: float | None = Field(default=None, ge=0, le=1)
    coverage: float | None = Field(default=None, ge=0, le=1)
    completeness: float | None = Field(default=None, ge=0, le=1)
    flags: list[str] = []


class TravelWindow(BaseModel):
    starts_at: datetime
    ends_at: datetime
    timezone: str


class RouteCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    route_id: UUID
    closed: bool = False
    duration_seconds: int | None = Field(default=None, ge=0)
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    quality: Quality


class OfficialAlert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    title: str = "Official alert"
    official: bool = True
    active: bool = True
    closure: bool = False
    intersects_route: bool = True
    effective_at: datetime | None = None
    ends_at: datetime | None = None
    instruction: str | None = None


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    snapshot_id: UUID
    route_id: UUID
    risk_level: RiskLevel
    score: float = Field(ge=0, le=1)
    uncertainty: float | None = Field(default=None, ge=0, le=1)
    reason_codes: list[str] = []
    quality: Quality


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: UUID
    snapshot_id: UUID
    schema_version: str
    feature_schema_version: str
    contract_version: str = "1.0.0"
    travel_window: TravelWindow
    route_candidates: list[RouteCandidate]
    assessments: list[RiskAssessment]
    official_alerts: list[OfficialAlert] = []
    quality_summary: Quality
    selected_route_id: UUID | None = None
    locale: str = "en-US"
    created_at: datetime | None = None


class DecisionReason(BaseModel):
    code: str
    text: str
    source_ids: list[str] = []


class DecisionResult(BaseModel):
    decision_id: UUID
    request_id: UUID
    snapshot_id: UUID
    action_code: ActionCode
    risk_level: RiskLevel
    confidence: float = Field(ge=0, le=1)
    selected_route_id: UUID | None = None
    rules_fired: list[str]
    escalation_required: bool
    summary: str
    reasons: list[DecisionReason]
    citations: list[dict[str, Any]] = []
    limitations: list[dict[str, str | None]] = []
    versions: dict[str, str | None]
    validation: dict[str, bool]
    created_at: datetime
