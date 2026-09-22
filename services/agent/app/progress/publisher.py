"""Redis Streams progress publisher (00_API_AND_DATA_CONTRACTS.md §7, "Redis key/event
conventions").

Two properties the plan requires explicitly (Phase 1 step 5, "Redis progress publisher ที่
idempotent และ event ordering"):

* **Idempotent.** Each call passes a `dedupe_key` unique to that occurrence (e.g. a node name plus
  `StageStatus`, since a node starting is a distinct occurrence from the same node completing). A
  repeated call with the same `dedupe_key` — a retried request, a re-delivered task — is a no-op:
  it does not advance the sequence counter or append a second stream entry.
* **Ordered.** `event_id` comes from `INCR` on a per-run counter key, which Redis guarantees is
  atomic even under concurrent publishers for the same run. A skipped `dedupe_key` can leave a gap
  in the sequence (acceptable: the `AgentEvent` contract requires monotonic increasing values, not
  gapless ones), but two different events for the same run never receive the same id or go out of
  order.

Every key carries the `sta:{env}:...` prefix and a TTL, per contract §7 ("ห้ามสร้าง key ถาวรโดยไม่
review"; "กำหนด TTL ทุก key"). The idempotency key's shape
(`sta:{env}:idempotency:{request_id}:{key}`) adapts the contract's
`sta:{env}:idempotency:{user_id}:{key}` pattern to a run-scoped occurrence rather than a
user-scoped mutation — there is no user id available at this layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

from app.progress.events import AGENT_EVENT_ADAPTER, AgentEvent, EventType

_DEDUPE_TTL_SECONDS = 3600
_STREAM_TTL_SECONDS = 3600


class ProgressPublisher:
    def __init__(self, redis: Redis, env: str) -> None:
        self._redis = redis
        self._env = env

    def _key(self, *parts: str) -> str:
        return ":".join(("sta", self._env, *parts))

    async def publish(
        self,
        *,
        request_id: UUID,
        correlation_id: UUID,
        event_type: EventType,
        payload: object,
        dedupe_key: str,
    ) -> int | None:
        """Publish one event, or skip it if `dedupe_key` was already published for this run.

        Returns the assigned `event_id`, or `None` if this call was a duplicate.
        """
        dedupe_redis_key = self._key("idempotency", str(request_id), dedupe_key)
        reserved = await self._redis.set(dedupe_redis_key, "1", nx=True, ex=_DEDUPE_TTL_SECONDS)
        if not reserved:
            return None

        seq_key = self._key("run", str(request_id), "event_seq")
        event_id = await self._redis.incr(seq_key)
        await self._redis.expire(seq_key, _STREAM_TTL_SECONDS)

        envelope_data: dict[str, object] = {
            "event_id": event_id,
            "request_id": str(request_id),
            "correlation_id": str(correlation_id),
            "occurred_at": datetime.now(UTC).isoformat(),
            "event_type": event_type.value,
            "payload": payload,
        }
        event: AgentEvent = AGENT_EVENT_ADAPTER.validate_python(envelope_data)

        stream_key = self._key("run", str(request_id), "events")
        await self._redis.xadd(
            stream_key,
            {"data": event.model_dump_json()},
            maxlen=1000,
            approximate=True,
        )
        await self._redis.expire(stream_key, _STREAM_TTL_SECONDS)
        return int(event_id)
