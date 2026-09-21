"""Internal snapshot endpoints (packages/contracts/openapi/internal-data-integration.yaml)."""

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import InternalAuth
from app.api.envelope import error, success
from app.domain.canonical import StrictRecord
from app.domain.errors import SnapshotConflictError, SnapshotNotFoundError
from app.domain.snapshot import IntegratedTravelContext, SnapshotCreateRequest
from app.observability.metrics import (
    evidence_age_unknown,
    evidence_conflicts,
    evidence_coverage,
    evidence_freshness,
    quality_flags,
    snapshot_build_seconds,
    snapshot_replays,
    snapshots_created,
)
from app.pipeline.build import build_route_snapshot, evidence_from_request
from app.pipeline.snapshot import SNAPSHOT_SCHEMA_VERSION, UNHASHED
from app.repositories.db import build_session_factory, unit_of_work
from app.repositories.models import Snapshot
from app.repositories.snapshot_repo import SnapshotRepository, canonical_hash
from app.settings import get_settings

router = APIRouter(prefix="/internal/v1/snapshots")


class SnapshotValidateRequest(StrictRecord):
    strict: bool = Field(default=False)


def _factory(request: Request):
    return build_session_factory(request.app.state.engine)


async def _stored(session: Any, request_id: UUID) -> list[Snapshot]:
    rows = await session.execute(
        select(Snapshot).where(
            Snapshot.request_id == request_id,
            Snapshot.schema_version == SNAPSHOT_SCHEMA_VERSION,
        )
    )
    return list(rows.scalars())


def _observe(snapshot: IntegratedTravelContext, seconds: float) -> None:
    """Record one stored snapshot; labels come from closed enums only."""
    quality = snapshot.quality_summary
    snapshots_created.labels(gate=_gate(quality.notes) or "UNKNOWN").inc()
    snapshot_build_seconds.observe(seconds)
    for flag in quality.flags:
        quality_flags.labels(flag=flag).inc()
    evidence_conflicts.inc(len(snapshot.conflict_summary))
    coverage = snapshot.features.get("critical_evidence_coverage")
    if isinstance(coverage, int | float):
        evidence_coverage.observe(coverage)
    age = snapshot.features.get("critical_evidence_freshness_seconds")
    if isinstance(age, int | float):
        evidence_freshness.observe(age)
    else:
        evidence_age_unknown.inc()


@router.post("", response_model=None)
async def create_snapshot(
    body: SnapshotCreateRequest, request: Request, _: InternalAuth
) -> JSONResponse:
    request_json = body.model_dump(mode="json")
    input_hash = canonical_hash(request_json)
    try:
        async with unit_of_work(_factory(request)) as session:
            existing = await _stored(session, body.request_id)
            for row in existing:
                if row.input_content_hash == input_hash:
                    snapshot_replays.inc()
                    return JSONResponse(status_code=200, content=success(row.evidence_json))
            if existing:
                return error("IDEMPOTENCY_CONFLICT", "request_id was used with other content", 409)
            started = time.perf_counter()
            snapshot = await build_route_snapshot(
                session,
                snapshot_id=uuid4(),
                request_id=body.request_id,
                trip_id=body.trip_id,
                supersedes_snapshot_id=body.supersedes_snapshot_id,
                travel_window=body.travel_window,
                recommendation_at=body.recommendation_at,
                evidence=evidence_from_request(body),
                settings=get_settings(),
                created_at=datetime.now(UTC),
            )
            stored = await SnapshotRepository(session).save(
                snapshot, input_content_hash=input_hash, request_json=request_json
            )
            stored_json = stored.evidence_json
    except SnapshotNotFoundError:
        return error("NOT_FOUND", "superseded snapshot does not exist", 404)
    except SnapshotConflictError:
        return error("IDEMPOTENCY_CONFLICT", "request_id was used with other content", 409)
    except ValueError:
        return error("VALIDATION_ERROR", "evidence cannot form a valid snapshot", 422)
    except SQLAlchemyError:
        return error("DEPENDENCY_UNAVAILABLE", "Storage unavailable", 503)
    # Observed only after the transaction committed.
    _observe(snapshot, time.perf_counter() - started)
    return JSONResponse(status_code=201, content=success(stored_json))


@router.get("/{snapshot_id}", response_model=None)
async def get_snapshot(
    snapshot_id: UUID, request: Request, _: InternalAuth
) -> JSONResponse | dict[str, Any]:
    try:
        async with unit_of_work(_factory(request)) as session:
            row = await SnapshotRepository(session).get(snapshot_id)
    except SQLAlchemyError:
        return error("DEPENDENCY_UNAVAILABLE", "Storage unavailable", 503)
    if row is None:
        return error("NOT_FOUND", "snapshot does not exist", 404)
    return success(row.evidence_json)


def _gate(notes: list[str]) -> str | None:
    gates = [note.split("=", 1)[1] for note in notes if note.startswith("gate=")]
    return gates[0] if len(gates) == 1 else None


@router.post("/{snapshot_id}/validate", response_model=None)
async def validate_snapshot(
    snapshot_id: UUID,
    request: Request,
    _: InternalAuth,
    body: SnapshotValidateRequest | None = None,
) -> JSONResponse | dict[str, Any]:
    strict = body.strict if body else False
    try:
        async with unit_of_work(_factory(request)) as session:
            row = await SnapshotRepository(session).get(snapshot_id)
    except SQLAlchemyError:
        return error("DEPENDENCY_UNAVAILABLE", "Storage unavailable", 503)
    if row is None:
        return error("NOT_FOUND", "snapshot does not exist", 404)
    problems: list[str] = []
    try:
        snapshot = IntegratedTravelContext.model_validate(row.evidence_json)
    except ValidationError as failure:
        problems += [f"schema:{'.'.join(map(str, e['loc']))}" for e in failure.errors()]
        snapshot = None
    recomputed = canonical_hash({k: v for k, v in row.evidence_json.items() if k not in UNHASHED})
    hash_matches = recomputed == row.content_hash == row.evidence_json.get("content_hash")
    if not hash_matches:
        problems.append("content_hash does not match the stored content")
    quality = snapshot.quality_summary if snapshot else None
    gate = _gate(quality.notes) if quality else None
    if gate is None:
        problems.append("quality gate is missing from quality_summary.notes")
    elif strict and gate != "PASS":
        problems.append(f"strict validation requires PASS, gate is {gate}")
    report = {
        "snapshot_id": str(snapshot_id),
        "valid": not problems and gate != "BLOCK",
        "schema_valid": snapshot is not None,
        "content_hash_matches": hash_matches,
        "gate": gate or "BLOCK",
        "flags": list(quality.flags) if quality else [],
        "missing_critical": [
            note.split("=", 1)[1]
            for note in (quality.notes if quality else [])
            if note.startswith("missing_critical=")
        ],
        "problems": problems,
    }
    return success(report)
