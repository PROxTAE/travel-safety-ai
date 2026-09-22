from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import asyncpg
from pydantic import BaseModel, ConfigDict, Field


class AuditReplay(BaseModel):
    """Sanitized audit trace; deliberately excludes prose, prompts, and evidence payloads."""

    model_config = ConfigDict(extra="forbid")

    audit_id: UUID
    decision_id: UUID
    request_id: UUID
    snapshot_id: UUID
    action_code: str
    confidence: float = Field(ge=0, le=1)
    escalation_required: bool
    policy_version: str
    policy_checksum: str
    rules_fired: list[str]
    input_hash: str
    output_hash: str


def replay_audit_record(record: Mapping[str, Any]) -> AuditReplay:
    return AuditReplay.model_validate(dict(record))


async def load_audit_replay(pool: asyncpg.Pool, audit_id: UUID) -> AuditReplay | None:
    record = await pool.fetchrow(
        """
        SELECT audit_id, decision_id, request_id, snapshot_id, action_code,
               confidence, escalation_required, policy_version, policy_checksum,
               rules_fired, input_hash, output_hash
        FROM decision.audit_events
        WHERE audit_id = $1
        """,
        audit_id,
    )
    return replay_audit_record(record) if record else None
