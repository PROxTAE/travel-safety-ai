"""Assessment run request and response models.

These mirror `run-ref.schema.json`, `run-state.schema.json` and `sse-events.schema.json`.
`tests/test_contract_parity.py` asserts the field names and required sets match, so the two
cannot drift.

Two conventions inherited from the rest of the contract and worth restating here, because a run is
where they are easiest to break:

* **A value nobody could measure is `null`, and the field is still required.** `percent` is null
  whenever the remaining work cannot be estimated honestly. Omitting it would let a client read
  "no estimate" as "zero per cent".
* **Text is a key, not a sentence.** `message_key` and `prompt_key` are translation keys. A
  rendered string would be one locale's, and the traveller's locale is not the agent's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.run import RunStage, RunStatus
from app.schemas.envelope import ResponseMeta

#: Matches `primitives.schema.json#/$defs/MessageKey`: dotted lower-case identifiers.
MessageKey = Annotated[str, Field(max_length=128, pattern=r"^[a-z][a-z0-9_.]*$")]

#: Matches `primitives.schema.json#/$defs/Locale`.
Locale = Annotated[str, Field(max_length=35, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")]


class CreateAssessmentRequest(BaseModel):
    """What a client may say when starting an assessment.

    Everything is optional and none of it describes the journey: the journey comes from the stored
    trip. A client cannot assess one trip while claiming another, because the trip id is in the
    path and the ownership check is a repository query.
    """

    model_config = ConfigDict(extra="forbid")

    question: Annotated[str | None, Field(max_length=2000)] = None
    conversation_id: UUID | None = None
    locale: Locale | None = None
    live_location_consent_id: UUID | None = None
    avoid_areas: Annotated[list[dict[str, Any]], Field(max_length=32)] = Field(default_factory=list)


class RunRefModel(BaseModel):
    """Returned by every endpoint that starts asynchronous work."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    trip_id: UUID | None = None
    conversation_id: UUID | None = None
    status: RunStatus
    events_url: Annotated[str, Field(max_length=512)]
    poll_url: Annotated[str, Field(max_length=512)]
    submitted_at: datetime


class DegradedServiceModel(BaseModel):
    """One dependency that was not fully available while the run was in progress."""

    model_config = ConfigDict(frozen=True)

    service: Annotated[str, Field(max_length=64)]
    reason: Annotated[str, Field(max_length=256)]
    since: datetime | None = None


class RunErrorModel(BaseModel):
    """The `ErrorBody` shape, carried inside a run state rather than an HTTP error envelope."""

    model_config = ConfigDict(frozen=True)

    code: Annotated[str, Field(max_length=64)]
    message: Annotated[str, Field(max_length=512)]
    field_errors: list[dict[str, Any]] = Field(default_factory=list)
    retryable: bool = False
    retry_after_seconds: int | None = None


class RunStateModel(BaseModel):
    """Pollable state of a run.

    It reports progress and where the result will appear. It never exposes the agent's reasoning,
    its prompts or a raw provider payload — those are not absent by accident, they are absent
    because this is the object a browser receives.
    """

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    trip_id: UUID | None = None
    conversation_id: UUID | None = None
    status: RunStatus
    stage: RunStage | None = None
    percent: Annotated[int | None, Field(ge=0, le=100)] = None
    message_key: MessageKey | None = None
    missing_fields: Annotated[list[str], Field(max_length=64)] = Field(default_factory=list)
    recommendation_id: UUID | None = None
    result_url: Annotated[str | None, Field(max_length=512)] = None
    error: RunErrorModel | None = None
    degraded_services: list[DegradedServiceModel] = Field(default_factory=list)
    submitted_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class RunRefResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: RunRefModel
    meta: ResponseMeta


class RunStateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: RunStateModel
    meta: ResponseMeta


# --- SSE payloads -------------------------------------------------------------------------------
#
# Every event the stream may carry has a model here, and the bridge validates against it before
# anything is written to the socket. That is the single place where "the agent said something odd"
# is stopped from becoming "the browser was told something odd".


class SseRunAccepted(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    status: RunStatus
    submitted_at: datetime


class SseRunProgress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    stage: RunStage
    percent: Annotated[int | None, Field(ge=0, le=100)] = None
    message_key: MessageKey
    occurred_at: datetime | None = None


class SseRunNeedsInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    missing_fields: Annotated[list[str], Field(max_length=64)]
    prompt_key: MessageKey


class SseRunDegraded(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    service: Annotated[str, Field(max_length=64)]
    reason: Annotated[str, Field(max_length=256)]
    retrying: bool


class SseRunCompleted(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    recommendation_id: UUID
    result_url: Annotated[str, Field(max_length=512)]
    status: Literal["COMPLETED", "PARTIAL"]


class SseRunFailed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    error: RunErrorModel


class SseHeartbeat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    server_time: datetime


#: Event name on the wire -> the model its `data` must satisfy. The bridge refuses to forward an
#: event whose name is not a key here, so a new event type from the agent is dropped rather than
#: passed through unvalidated.
SSE_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "run.accepted": SseRunAccepted,
    "run.progress": SseRunProgress,
    "run.needs_input": SseRunNeedsInput,
    "run.degraded": SseRunDegraded,
    "run.completed": SseRunCompleted,
    "run.failed": SseRunFailed,
    "heartbeat": SseHeartbeat,
}

#: Events after which the stream closes.
TERMINAL_EVENTS: frozenset[str] = frozenset({"run.completed", "run.failed"})
