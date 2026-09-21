"""Immutable, concurrency-safe persistence for dedup and conflict evidence."""

from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import SnapshotConflictError
from app.pipeline.dedup import MATCH_VERSION, Match, Resolution
from app.repositories.models import CanonicalRecord, DedupCluster
from app.repositories.snapshot_repo import canonical_hash


class DedupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        record_type: str,
        members: list[CanonicalRecord],
        matches: list[Match],
        conflicts: dict[str, Resolution],
    ) -> DedupCluster:
        if not members:
            raise ValueError("dedup cluster needs at least one member")
        member_data = sorted(
            (
                {
                    "record_id": str(item.id),
                    "source_id": item.source_id,
                    "content_hash": item.content_hash,
                }
                for item in members
            ),
            key=lambda item: (item["source_id"], item["content_hash"], item["record_id"]),
        )
        link_data = [asdict(link) for link in matches]
        conflict_data = {path: asdict(result) for path, result in sorted(conflicts.items())}
        key = canonical_hash({"record_type": record_type, "members": member_data})
        content_hash = canonical_hash(
            {
                "members": member_data,
                "matches": link_data,
                "conflicts": conflict_data,
            }
        )
        lookup = {"record_type": record_type, "cluster_key": key, "match_version": MATCH_VERSION}
        await self.session.execute(
            insert(DedupCluster)
            .values(
                id=uuid4(),
                **lookup,
                content_hash=content_hash,
                members_json=member_data,
                matches_json=link_data,
                conflicts_json=conflict_data,
            )
            .on_conflict_do_nothing(constraint="uq_dedup_cluster")
        )
        existing = (
            await self.session.execute(select(DedupCluster).filter_by(**lookup))
        ).scalar_one()
        if existing.content_hash != content_hash:
            raise SnapshotConflictError("same cluster and match version has different evidence")
        return existing
