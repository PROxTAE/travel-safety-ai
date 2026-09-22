import asyncio
from pathlib import Path

import pytest
from test_evaluator import make_request

from app.cache import DecisionCache, IdempotencyConflict, input_hash
from app.policy.loader import load_policy

SERVICE_ROOT = Path(__file__).parents[1]
POLICY, _ = load_policy(SERVICE_ROOT / "policies/v1/decision-table.yaml")


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, **kwargs: object) -> bool:
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True


def test_input_hash_changes_with_locale_and_policy_inputs() -> None:
    first = input_hash(make_request(0.1, locale="en-US"), POLICY, "1.0.0", "model-a")
    locale_changed = input_hash(make_request(0.1, locale="th-TH"), POLICY, "1.0.0", "model-a")
    model_changed = input_hash(make_request(0.1), POLICY, "1.0.0", "model-b")
    assert len(first) == 64
    assert first != locale_changed
    assert first != model_changed


def test_explanation_cache_round_trips_a_decision_result() -> None:
    from app.policy.evaluator import build_result, evaluate

    result = build_result(make_request(0.1), POLICY, evaluate(make_request(0.1), POLICY))
    cache = DecisionCache(FakeRedis(), 300)
    asyncio.run(cache.set_explanation("hash", result))
    cached = asyncio.run(cache.get_explanation("hash"))
    assert cached is not None
    assert cached.action_code == result.action_code
    assert cached.decision_id == result.decision_id


def test_idempotency_rejects_different_payload_and_replays_same_result() -> None:
    from app.policy.evaluator import build_result, evaluate

    cache = DecisionCache(FakeRedis(), 300)
    request = make_request(0.1)
    request_hash = input_hash(request, POLICY, "1.0.0", None)
    assert asyncio.run(cache.reserve_idempotency("key", request_hash)) is None
    with pytest.raises(IdempotencyConflict):
        asyncio.run(cache.reserve_idempotency("key", "different"))
    result = build_result(request, POLICY, evaluate(request, POLICY))
    asyncio.run(cache.save_idempotency("key", request_hash, result))
    replay = asyncio.run(cache.reserve_idempotency("key", request_hash))
    assert replay is not None
    assert replay.decision_id == result.decision_id
