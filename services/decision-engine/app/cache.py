from __future__ import annotations

import hashlib
import json

from redis.asyncio import Redis

from app.domain.models import DecisionRequest, DecisionResult
from app.policy.loader import Policy


class IdempotencyConflict(RuntimeError):
    pass


def input_hash(
    payload: DecisionRequest, policy: Policy, prompt_version: str, model: str | None
) -> str:
    canonical = {
        "request": json.loads(payload.model_dump_json()),
        "policy_version": policy.version,
        "policy_contract": policy.contract_version,
        "prompt_version": prompt_version,
        "model": model,
        "locale": payload.locale,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class DecisionCache:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def get_explanation(self, cache_key: str) -> DecisionResult | None:
        value = await self.redis.get(f"decision:explanation:{cache_key}")
        return DecisionResult.model_validate_json(value) if value else None

    async def set_explanation(self, cache_key: str, result: DecisionResult) -> None:
        await self.redis.set(
            f"decision:explanation:{cache_key}", result.model_dump_json(), ex=self.ttl_seconds
        )

    async def reserve_idempotency(self, key: str, request_hash: str) -> DecisionResult | None:
        redis_key = f"decision:idempotency:{key}"
        existing = await self.redis.get(redis_key)
        if existing:
            record = json.loads(existing)
            if record["input_hash"] != request_hash:
                raise IdempotencyConflict("Idempotency-Key was reused for a different request")
            if record.get("result") is None:
                raise IdempotencyConflict("An identical decision is already in progress")
            return DecisionResult.model_validate(record["result"])
        reserved = await self.redis.set(
            redis_key,
            json.dumps({"input_hash": request_hash, "result": None}),
            ex=self.ttl_seconds,
            nx=True,
        )
        if not reserved:
            return await self.reserve_idempotency(key, request_hash)
        return None

    async def save_idempotency(self, key: str, request_hash: str, result: DecisionResult) -> None:
        await self.redis.set(
            f"decision:idempotency:{key}",
            json.dumps(
                {"input_hash": request_hash, "result": json.loads(result.model_dump_json())}
            ),
            ex=self.ttl_seconds,
        )
