"""Immutable, idempotent snapshot persistence."""

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import SnapshotConflictError, SnapshotNotFoundError
from app.domain.snapshot import IntegratedTravelContext
from app.repositories.models import Snapshot


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        request_id: UUID,
        input_content_hash: str,
        schema_version: str,
        evidence: dict,
        feature_schema_version: str | None = None,
        supersedes_id: UUID | None = None,
    ) -> Snapshot:
        payload_hash = canonical_hash(evidence)
        proposed_id = uuid4()
        statement = (
            insert(Snapshot)
            .values(
                id=proposed_id,
                request_id=request_id,
                input_content_hash=input_content_hash,
                content_hash=payload_hash,
                schema_version=schema_version,
                feature_schema_version=feature_schema_version,
                evidence_json=evidence,
                supersedes_id=supersedes_id,
            )
            .on_conflict_do_nothing(constraint="uq_snapshot_input")
            .returning(Snapshot.id)
        )
        await self.session.execute(statement)
        existing = (
            await self.session.execute(
                select(Snapshot).where(
                    Snapshot.request_id == request_id,
                    Snapshot.input_content_hash == input_content_hash,
                    Snapshot.schema_version == schema_version,
                )
            )
        ).scalar_one()
        if existing.content_hash != payload_hash:
            raise SnapshotConflictError("idempotency key refers to different immutable content")
        return existing

    async def get(self, snapshot_id: UUID) -> Snapshot | None:
        return await self.session.get(Snapshot, snapshot_id)

    async def save(
        self,
        snapshot: IntegratedTravelContext,
        *,
        input_content_hash: str,
        request_json: dict | None = None,
    ) -> Snapshot:
        """Store once per idempotency key; a replay returns the first stored snapshot."""
        supersedes = snapshot.supersedes_snapshot_id
        if supersedes is not None and await self.get(supersedes) is None:
            raise SnapshotNotFoundError(f"superseded snapshot {supersedes} does not exist")
        corridor = json.dumps(snapshot.route_corridor_geojson.model_dump(mode="json"))
        statement = (
            insert(Snapshot)
            .values(
                id=snapshot.snapshot_id,
                request_id=snapshot.request_id,
                input_content_hash=input_content_hash,
                content_hash=snapshot.content_hash,
                schema_version=snapshot.schema_version,
                feature_schema_version=snapshot.feature_schema_version,
                evidence_json=snapshot.model_dump(mode="json"),
                request_json=request_json,
                route_corridor=func.ST_SetSRID(func.ST_GeomFromGeoJSON(corridor), 4326),
                supersedes_id=supersedes,
                created_at=snapshot.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_snapshot_input")
        )
        await self.session.execute(statement)
        stored = (
            await self.session.execute(
                select(Snapshot).where(
                    Snapshot.request_id == snapshot.request_id,
                    Snapshot.input_content_hash == input_content_hash,
                    Snapshot.schema_version == snapshot.schema_version,
                )
            )
        ).scalar_one()
        if stored.content_hash != snapshot.content_hash:
            raise SnapshotConflictError("idempotency key refers to different immutable content")
        return stored
