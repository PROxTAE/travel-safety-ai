from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Domain models for Recommendation Delivery


class Citation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    document_id: str
    title: str
    source_url: str
    page: int | None = None
    section: str | None = None
    passage: str
    authority: str = "OFFICIAL"


class EmergencyInstruction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(..., max_length=2000)
    evidence_id: str
    hazard_type: str | None = None
    citation: Citation | None = None


class DecisionReason(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    text: str
    severity: str = "INFO"
    source_ids: list[str] = Field(default_factory=list)


class ImmediateAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    priority: int = 5
    evidence_id: str | None = None


class Limitation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    text: str | None = None


class DegradedService(BaseModel):
    model_config = ConfigDict(extra="ignore")

    service: str
    reason: str
    impact: str = "MINOR"


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    provider: str
    provider_record_id: str | None = None
    authority: str = "OFFICIAL"
    source_url: str | None = None
    license: str | None = None
    observed_at: datetime | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    content_hash: str | None = None
    schema_version: str = "1.0.0"


class OfficialContact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contact_id: str
    country_code: str = Field(..., min_length=2, max_length=2)
    subdivision: str | None = None
    service_type: str
    label: str
    phone: str
    languages: list[str] = Field(default_factory=lambda: ["th-TH", "en-US"])
    source_url: str
    authority: str = "OFFICIAL"
    effective_at: datetime
    verified_at: datetime
    review_due_at: datetime | None = None


class RouteCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    route_id: str
    provider_route_id: str | None = None
    label: str = "RECOMMENDED"
    mode: str = "CAR"
    geometry: dict[str, Any] | None = None
    distance_m: float | None = None
    duration_seconds: float | None = None
    transfers: int | None = None
    exposure: dict[str, Any] | None = None
    risk_level: str = "LOW"
    quality: dict[str, Any] | None = None
    sources: list[SourceProvenance] = Field(default_factory=list)


class DisasterEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    event_type: str
    title: str
    description: str | None = None
    severity: str = "MODERATE"
    geometry: dict[str, Any] | None = None
    effective_at: datetime | None = None
    ends_at: datetime | None = None
    instruction: str | None = None
    official: bool = True
    quality: dict[str, Any] | None = None
    source: SourceProvenance | None = None


class Freshness(BaseModel):
    model_config = ConfigDict(extra="ignore")

    observed_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


class ResponseVersions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contract: str = "1.0.0"
    policy: str | None = "1.0.0"
    prompt: str | None = "1.0.0"
    llm_model: str | None = None
    risk_model: str | None = None
    knowledge_collection: str | None = None


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recommendation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    trip_id: str
    conversation_id: str | None = None
    decision_id: str | None = None
    snapshot_id: str | None = None
    status: Literal["COMPLETED", "PARTIAL"] = "COMPLETED"
    action_code: Literal["NORMAL", "CHANGE_ROUTE", "DELAY", "AVOID"]
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    short_summary: str = Field(..., max_length=1000)
    immediate_actions: list[ImmediateAction] = Field(default_factory=list)
    reasons: list[DecisionReason] = Field(default_factory=list)
    primary_route: RouteCandidate | None = None
    alternatives: list[RouteCandidate] = Field(default_factory=list)
    alerts: list[DisasterEvent] = Field(default_factory=list)
    emergency_instructions: list[EmergencyInstruction] = Field(default_factory=list)
    official_contacts: list[OfficialContact] = Field(default_factory=list)
    sources: list[SourceProvenance] = Field(default_factory=list)
    freshness: Freshness
    limitations: list[Limitation] = Field(default_factory=list)
    degraded_services: list[DegradedService] = Field(default_factory=list)
    versions: ResponseVersions = Field(default_factory=ResponseVersions)
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
