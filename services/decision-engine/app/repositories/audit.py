from __future__ import annotations

import asyncpg

from app.domain.models import DecisionResult


async def write_audit(pool: asyncpg.Pool, result: DecisionResult, policy_checksum: str) -> None:
    await pool.execute(
        """
        INSERT INTO decision.audit_events
          (decision_id, request_id, snapshot_id, action_code, confidence,
           escalation_required, policy_version, policy_checksum, rules_fired,
           input_hash, output_hash)
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9,
                    encode(sha256(convert_to($10, 'UTF8')), 'hex'),
                    encode(sha256(convert_to($11, 'UTF8')), 'hex')
                )
        """,
        result.decision_id,
        result.request_id,
        result.snapshot_id,
        result.action_code.value,
        result.confidence,
        result.escalation_required,
        result.versions["policy"],
        policy_checksum,
        result.rules_fired,
        str(result.request_id),
        result.model_dump_json(),
    )
