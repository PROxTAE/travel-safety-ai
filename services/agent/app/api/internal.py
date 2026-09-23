"""Internal agent API (00_API_AND_DATA_CONTRACTS.md §5.1, owner คน 3).

Phase 1 scope and its limits, spelled out because both are easy to miss from the route bodies
alone:

* `POST /internal/v1/runs` executes the graph **synchronously** within the request (there is no
  worker/queue yet) and returns once the run reaches a terminal status or `NEEDS_INPUT`. Every run
  in this phase ends `FAILED` the moment it reaches `fetch_external_data` (see that node's
  docstring) — Phase 3/4 add the tool clients that let a run actually complete.
* `POST /internal/v1/runs/{id}/resume` only understands the one missing-field rule Phase 1's
  `check_required_fields` implements (`confirmed_by_user`). The general "resume with arbitrary
  missing-field answers" flow is Phase 5 scope (`feat/03-followup-degraded`,
  03_TRAVEL_AI_AGENT_IMPLEMENTATION.md Phase 5 step 5) once the per-`Intent` field matrix exists.
* `POST /internal/v1/runs/{id}/cancel` can only cancel a run parked at `NEEDS_INPUT` (or one that
  has not started yet). Because Phase 1 has no background execution, there is no run "in flight" to
  interrupt — cooperative cancellation of an active tool call is Phase 3 scope
  ("timeout, cancellation, retry").

`run.cancelled` has no SSE event in the contract's event table (00_API_AND_DATA_CONTRACTS.md §6) —
a cancelled run is observable only by polling `GET /internal/v1/runs/{id}`, not by subscribing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from langchain_core.runnables import RunnableConfig
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.graph.builder import GRAPH_VERSION
from app.graph.state import (
    AgentState,
    ControlSection,
    IdentitySection,
    InputSection,
    PlanSection,
    RunStatus,
    TravelRequest,
    VersionsSection,
)
from app.progress.events import (
    EventType,
    RunAcceptedPayload,
    RunCompletedPayload,
    RunFailedPayload,
    RunNeedsInputPayload,
)
from app.runtime import AppRuntime, get_runtime

router = APIRouter(prefix="/internal/v1/runs", tags=["runs"])


def _thread_id(request: TravelRequest) -> str:
    """Thread grouping per agent-state.md §7: conversation_id when the request has one, otherwise
    the request stands alone as its own thread."""
    return (
        str(request.conversation_id)
        if request.conversation_id is not None
        else str(request.request_id)
    )


def _thread_config(thread_id: str) -> RunnableConfig:
    return RunnableConfig(configurable={"thread_id": thread_id})


async def require_internal_auth(
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    settings = runtime.settings
    if settings.internal_service_token is None:
        if settings.app_env == "production":
            raise HTTPException(status_code=503, detail="Internal authentication is unavailable")
        return
    expected = f"Bearer {settings.internal_service_token.get_secret_value()}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="AUTHENTICATION_REQUIRED")


class RunRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: RunStatus
    events_url: str
    poll_url: str
    submitted_at: AwareDatetime


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    travel_request: TravelRequest
    correlation_id: UUID
    user_scope_hash: str
    approved_context_refs: list[str] = Field(default_factory=list)


class ResumeRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_scope_hash: str
    confirmed_origin: bool = False
    confirmed_destination: bool = False


class CancelRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


def _run_ref(state: AgentState) -> RunRef:
    request_id = state.identity.request_id
    return RunRef(
        request_id=request_id,
        status=state.control.status,
        events_url=f"/api/v1/runs/{request_id}/events",
        poll_url=f"/api/v1/runs/{request_id}",
        submitted_at=state.control.started_at,
    )


async def _publish_terminal_event(runtime: AppRuntime, state: AgentState) -> None:
    if runtime.publisher is None:
        return
    identity = state.identity
    status = state.control.status

    if status is RunStatus.NEEDS_INPUT:
        await runtime.publisher.publish(
            request_id=identity.request_id,
            correlation_id=identity.correlation_id,
            event_type=EventType.RUN_NEEDS_INPUT,
            payload=RunNeedsInputPayload(
                missing_fields=state.input.missing_fields, prompt_key="input.missing_fields"
            ),
            dedupe_key=f"run.needs_input:{state.control.step_count}",
        )
    elif status in (RunStatus.COMPLETED, RunStatus.PARTIAL) and state.result.recommendation_id:
        await runtime.publisher.publish(
            request_id=identity.request_id,
            correlation_id=identity.correlation_id,
            event_type=EventType.RUN_COMPLETED,
            payload=RunCompletedPayload(
                status=status,
                recommendation_id=state.result.recommendation_id,
                result_url=f"/api/v1/recommendations/{state.result.recommendation_id}",
            ),
            dedupe_key="run.completed",
        )
    elif status is RunStatus.FAILED:
        error_code = state.control.errors[-1] if state.control.errors else "INTERNAL_ERROR"
        await runtime.publisher.publish(
            request_id=identity.request_id,
            correlation_id=identity.correlation_id,
            event_type=EventType.RUN_FAILED,
            payload=RunFailedPayload(
                error_code=error_code,
                message_key=f"error.{error_code.lower()}",
                retryable=error_code in {"DEPENDENCY_TIMEOUT", "DEPENDENCY_UNAVAILABLE"},
            ),
            dedupe_key="run.failed",
        )
    # RunStatus.CANCELLED: no matching SSE event type in the contract — see module docstring.


@router.post("", response_model=RunRef, dependencies=[Depends(require_internal_auth)])
async def create_run(
    payload: CreateRunRequest | TravelRequest, runtime: Annotated[AppRuntime, Depends(get_runtime)]
) -> RunRef:
    settings = runtime.settings
    now = datetime.now(UTC)

    if isinstance(payload, CreateRunRequest):
        request = payload.travel_request
        correlation_id = payload.correlation_id
        user_scope_hash = payload.user_scope_hash
        approved_context_refs = payload.approved_context_refs
    else:
        request = payload
        correlation_id = request.request_id
        user_scope_hash = ""
        approved_context_refs = []

    state = AgentState(
        identity=IdentitySection(
            request_id=request.request_id,
            correlation_id=correlation_id,
            trip_id=request.trip_id,
            conversation_id=request.conversation_id,
            user_scope_hash=user_scope_hash,
        ),
        input=InputSection(travel_request=request, approved_context_refs=approved_context_refs),
        plan=PlanSection(graph_version=GRAPH_VERSION),
        control=ControlSection(
            started_at=now,
            deadline_at=now + timedelta(seconds=settings.agent_total_timeout_seconds),
            remaining_budget=settings.initial_budget(),
        ),
        versions=VersionsSection(contract=settings.contract_version, graph=GRAPH_VERSION),
    )
    thread_id = _thread_id(request)

    if runtime.runs is not None:
        await runtime.runs.create(state, settings, thread_id)
    if runtime.publisher is not None:
        await runtime.publisher.publish(
            request_id=state.identity.request_id,
            correlation_id=state.identity.correlation_id,
            event_type=EventType.RUN_ACCEPTED,
            payload=RunAcceptedPayload(
                request_id=state.identity.request_id, status=state.control.status, submitted_at=now
            ),
            dedupe_key="run.accepted",
        )

    config = _thread_config(thread_id)
    raw = await runtime.graph.ainvoke(state, config=config)
    final_state = AgentState.model_validate(raw)

    if runtime.runs is not None:
        await runtime.runs.update_final(final_state)
    await _publish_terminal_event(runtime, final_state)

    return _run_ref(final_state)


@router.get("/{request_id}", dependencies=[Depends(require_internal_auth)])
async def get_run(
    request_id: UUID, runtime: Annotated[AppRuntime, Depends(get_runtime)]
) -> dict[str, object]:
    if runtime.runs is None:
        raise HTTPException(status_code=503, detail="Run storage is unavailable")
    row = await runtime.runs.get(request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    final_state: dict[str, Any] = cast(dict[str, Any], row.get("final_state") or {})
    result: dict[str, Any] = cast(dict[str, Any], final_state.get("result", {}))
    quality: dict[str, Any] = cast(dict[str, Any], final_state.get("quality", {}))
    control: dict[str, Any] = cast(dict[str, Any], final_state.get("control", {}))
    errors = cast(list[str], control.get("errors", []))
    return {
        "request_id": str(request_id),
        "status": row["status"],
        "graph_version": row["graph_version"],
        "recommendation_id": result.get("recommendation_id"),
        "degraded_services": quality.get("degraded_services", []),
        "stage": control.get("stage"),
        "percent": (
            100
            if row["status"] in (RunStatus.COMPLETED.value, RunStatus.PARTIAL.value)
            else (control.get("step_count", 0) * 20)
        ),
        "error_code": errors[-1] if errors else None,
        "error_message": "Assessment failed" if row["status"] == RunStatus.FAILED.value else None,
        "state": final_state,
    }


@router.post(
    "/{request_id}/resume", response_model=RunRef, dependencies=[Depends(require_internal_auth)]
)
async def resume_run(
    request_id: UUID,
    payload: ResumeRunRequest,
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> RunRef:
    if runtime.runs is None or runtime.checkpointer is None:
        raise HTTPException(status_code=503, detail="Run storage is unavailable")
    row = await runtime.runs.get(request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if row["user_scope_hash"] != payload.user_scope_hash:
        raise HTTPException(status_code=403, detail="FORBIDDEN")
    if row["status"] != RunStatus.NEEDS_INPUT.value:
        raise HTTPException(status_code=409, detail="CONFLICT: run is not waiting for input")

    thread_id = row["thread_id"]
    assert isinstance(thread_id, str)
    config = _thread_config(thread_id)
    snapshot = await runtime.graph.aget_state(config)
    current = AgentState.model_validate(snapshot.values)
    current_request = current.input.travel_request

    updated_request = current_request.model_copy(
        update={
            "origin": current_request.origin.model_copy(
                update={
                    "confirmed_by_user": current_request.origin.confirmed_by_user
                    or payload.confirmed_origin
                }
            ),
            "destination": current_request.destination.model_copy(
                update={
                    "confirmed_by_user": current_request.destination.confirmed_by_user
                    or payload.confirmed_destination
                }
            ),
        }
    )
    resumed_state = current.model_copy(
        update={
            "input": current.input.model_copy(
                update={"travel_request": updated_request, "missing_fields": []}
            ),
            "control": current.control.model_copy(update={"status": RunStatus.RUNNING}),
        }
    )

    raw = await runtime.graph.ainvoke(resumed_state, config=config)
    final_state = AgentState.model_validate(raw)

    await runtime.runs.update_final(final_state)
    await _publish_terminal_event(runtime, final_state)

    return _run_ref(final_state)


@router.post("/{request_id}/cancel", dependencies=[Depends(require_internal_auth)])
async def cancel_run(
    request_id: UUID,
    payload: CancelRunRequest,
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> dict[str, object]:
    del payload  # reason is accepted for audit purposes only; nothing reads it back yet
    if runtime.runs is None:
        raise HTTPException(status_code=503, detail="Run storage is unavailable")
    row = await runtime.runs.get(request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    if row["status"] not in (RunStatus.QUEUED.value, RunStatus.NEEDS_INPUT.value):
        raise HTTPException(status_code=409, detail="CONFLICT: run is already terminal")

    if runtime.checkpointer is not None:
        thread_id = row["thread_id"]
        assert isinstance(thread_id, str)
        config = _thread_config(thread_id)
        snapshot = await runtime.graph.aget_state(config)
        if snapshot.values:
            current = AgentState.model_validate(snapshot.values)
            cancelled_control = current.control.model_copy(
                update={"cancelled": True, "status": RunStatus.CANCELLED}
            )
            await runtime.graph.aupdate_state(config, {"control": cancelled_control})

    await runtime.runs.mark_cancelled(request_id)
    return {"request_id": str(request_id), "status": RunStatus.CANCELLED.value}
