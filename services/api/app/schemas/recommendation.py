"""The final recommendation, as this service revalidates it.

Mirrors `recommendation-response.schema.json`. Module 08 produces the object; this service checks
it before a traveller is told the result exists, which is the promise the schema's own description
makes — "the public API revalidates this against the schema before it reaches the browser".

**Why revalidate something a trusted internal service produced.** Because the failure being guarded
against is not a hostile service, it is a drifting one. Module 08 ships on its own cadence; a field
that changes type, an enum that gains a value, a nullable that starts arriving absent — each one
reaches a traveller as a safety verdict, and a half-parsed verdict is indistinguishable from a
confident one. Refusing to expose a recommendation this service cannot vouch for is the whole point.

**Scope of this model, deliberately.** The top level is modelled completely: every required field,
every enum, every range. The nested contract entities — `RouteCandidate`, `DisasterEvent`,
`OfficialContact`, `SourceProvenance`, `DecisionReason` — are accepted as structured objects and
not yet field-checked, because phase 5 exposes only the recommendation's **id** and never its body.
Phase 6 adds `GET /api/v1/recommendations/{id}`, which serves those nested objects to a browser,
and they get modelled there where a mistake would actually be displayed.

What is checked now is what phase 5 can act on: that the recommendation exists, that it belongs to
the run and the trip that asked for it, that its decision-critical values are inside the contract,
and that it carries the provenance and freshness every safety-relevant answer must carry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.run import RunStatus

ActionCode = Literal["NORMAL", "CHANGE_ROUTE", "DELAY", "AVOID"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]


class FreshnessModel(BaseModel):
    """When the underlying facts were observed and fetched.

    `fetched_at` is required and the other two are not: a provider that does not say when it
    observed something still has to say when we asked it. A recommendation with no fetch time
    cannot be aged, and an answer that cannot be aged cannot be trusted to be current.
    """

    model_config = ConfigDict(frozen=True)

    observed_at: datetime | None = None
    fetched_at: datetime
    expires_at: datetime | None = None


class ResponseVersionsModel(BaseModel):
    """Which contract, policy, prompt and models produced this.

    Only `contract` is required. The rest are null when the producing stage did not exist for a
    given answer, and they are what makes a past recommendation explainable after the models behind
    it have moved on.
    """

    model_config = ConfigDict(frozen=True)

    contract: Annotated[str, Field(max_length=32)]
    policy: Annotated[str | None, Field(max_length=32)] = None
    prompt: Annotated[str | None, Field(max_length=32)] = None
    llm_model: Annotated[str | None, Field(max_length=64)] = None
    risk_model: Annotated[str | None, Field(max_length=64)] = None
    knowledge_collection: Annotated[str | None, Field(max_length=64)] = None


class RecommendationResponseModel(BaseModel):
    """The object module 08 returns and this service checks before acting on it.

    Extras are allowed rather than forbidden, and that is the one place this model is deliberately
    lenient. An added optional field is how the contract says a producer may evolve without a
    breaking change; rejecting it would take a working system down on a compatible release. What is
    *not* lenient is the required set, the enums and the ranges — the things a wrong value would
    turn into a wrong verdict.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    recommendation_id: UUID
    request_id: UUID
    trip_id: UUID
    conversation_id: UUID | None = None
    decision_id: UUID | None = None
    snapshot_id: UUID | None = None

    status: RunStatus
    action_code: ActionCode
    risk_level: RiskLevel
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    short_summary: Annotated[str, Field(max_length=1000)]

    immediate_actions: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[dict[str, Any]]
    primary_route: dict[str, Any] | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    emergency_instructions: list[dict[str, Any]] = Field(default_factory=list)
    official_contacts: list[dict[str, Any]] = Field(default_factory=list)

    sources: list[dict[str, Any]]
    freshness: FreshnessModel
    limitations: list[dict[str, Any]]
    degraded_services: list[dict[str, Any]]
    versions: ResponseVersionsModel

    expires_at: datetime | None = None
    created_at: datetime
