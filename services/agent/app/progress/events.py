"""Progress event contract emitted by the agent (SSE / Redis Streams envelope).

Target location in repo: services/agent/app/progress/events.py

Source of truth: IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md
  - section 6 (SSE events and controlled stage values)
  - section 7 (Redis event envelope: event_id, event_type, occurred_at,
    producer, schema_version, correlation_id, payload)
and the "Progress events" rules in 03_TRAVEL_AI_AGENT_IMPLEMENTATION.md.

Safety rules enforced by the schema itself (extra="forbid" everywhere):
  - no chain-of-thought, prompt, raw provider body, token, exact coordinates
    or PII can be added to an event: unknown fields are rejected;
  - human-facing text is a `message_key`, never free text;
  - `event_id` is a per-run monotonic integer (>= 1) assigned by the publisher.

NOTE: `StageStatus` and the `request_id` field on the envelope are not spelled
out in the shared contract. They are proposed here and must be agreed with
module 02 (@02-api) before this contract PR is merged.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from app.graph.state import GraphStage, RunStatus

# Controlled vocabularies -----------------------------------------------------

# i18n key such as "stage.fetching_external_data" — never free text.
MessageKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]*$", max_length=100)]
# Stable error code such as "DEPENDENCY_TIMEOUT" (see contract section 2).
ErrorCode = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64)]
# Service name such as "external-data" — used for degraded banners only.
ServiceName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)]


class EventType(StrEnum):
    """SSE event names, verbatim from the contract."""

    RUN_ACCEPTED = "run.accepted"
    RUN_PROGRESS = "run.progress"
    RUN_NEEDS_INPUT = "run.needs_input"
    RUN_DEGRADED = "run.degraded"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    HEARTBEAT = "heartbeat"


class StageStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


# Payloads --------------------------------------------------------------------


class RunAcceptedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: RunStatus
    submitted_at: AwareDatetime


class RunProgressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: GraphStage
    status: StageStatus
    percent: int | None = Field(default=None, ge=0, le=100)
    message_key: MessageKey
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    service: ServiceName | None = None
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def _check_stage_lifecycle(self) -> RunProgressPayload:
        if self.status is StageStatus.STARTED and self.completed_at is not None:
            raise ValueError("completed_at must be empty while a stage is STARTED")
        if self.status is not StageStatus.STARTED and self.completed_at is None:
            raise ValueError("completed_at is required once a stage has ended")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        if self.status is StageStatus.FAILED and self.error_code is None:
            raise ValueError("error_code is required when a stage FAILED")
        return self


class RunNeedsInputPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    missing_fields: list[str] = Field(min_length=1)
    prompt_key: MessageKey


class RunDegradedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: ServiceName
    reason: ErrorCode
    retrying: bool


class RunCompletedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[RunStatus.COMPLETED, RunStatus.PARTIAL]
    recommendation_id: UUID
    result_url: str = Field(min_length=1, max_length=512)


class RunFailedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: ErrorCode
    message_key: MessageKey
    retryable: bool


class HeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_time: AwareDatetime


# Envelope + discriminated union ------------------------------------------------


class _EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Monotonic per run; the publisher assigns it, never the graph nodes.
    event_id: int = Field(ge=1)
    request_id: UUID
    correlation_id: UUID
    occurred_at: AwareDatetime
    producer: Literal["agent"] = "agent"
    schema_version: str = "1"


class RunAcceptedEvent(_EventEnvelope):
    event_type: Literal[EventType.RUN_ACCEPTED] = EventType.RUN_ACCEPTED
    payload: RunAcceptedPayload


class RunProgressEvent(_EventEnvelope):
    event_type: Literal[EventType.RUN_PROGRESS] = EventType.RUN_PROGRESS
    payload: RunProgressPayload


class RunNeedsInputEvent(_EventEnvelope):
    event_type: Literal[EventType.RUN_NEEDS_INPUT] = EventType.RUN_NEEDS_INPUT
    payload: RunNeedsInputPayload


class RunDegradedEvent(_EventEnvelope):
    event_type: Literal[EventType.RUN_DEGRADED] = EventType.RUN_DEGRADED
    payload: RunDegradedPayload


class RunCompletedEvent(_EventEnvelope):
    event_type: Literal[EventType.RUN_COMPLETED] = EventType.RUN_COMPLETED
    payload: RunCompletedPayload


class RunFailedEvent(_EventEnvelope):
    event_type: Literal[EventType.RUN_FAILED] = EventType.RUN_FAILED
    payload: RunFailedPayload


class HeartbeatEvent(_EventEnvelope):
    event_type: Literal[EventType.HEARTBEAT] = EventType.HEARTBEAT
    payload: HeartbeatPayload


AgentEvent = Annotated[
    RunAcceptedEvent
    | RunProgressEvent
    | RunNeedsInputEvent
    | RunDegradedEvent
    | RunCompletedEvent
    | RunFailedEvent
    | HeartbeatEvent,
    Field(discriminator="event_type"),
]

# Parse/validate any event coming off the wire (Redis Streams, tests):
#   AGENT_EVENT_ADAPTER.validate_json(raw_bytes)
AGENT_EVENT_ADAPTER: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)
