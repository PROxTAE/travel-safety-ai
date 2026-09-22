"""Integration tests for app/progress/publisher.py against a real Redis — the idempotency and
ordering properties Phase 1 step 5 requires, which a mock cannot meaningfully prove.
"""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis

from app.progress.events import EventType, RunAcceptedPayload
from app.progress.publisher import ProgressPublisher
from tests.integration.redis_helper import provision_redis, requires_docker


def _payload() -> RunAcceptedPayload:
    from datetime import UTC, datetime

    from app.graph.state import RunStatus

    return RunAcceptedPayload(
        request_id=uuid.uuid4(), status=RunStatus.QUEUED, submitted_at=datetime.now(UTC)
    )


@requires_docker
@pytest.mark.integration
async def test_publish_assigns_a_monotonic_event_id() -> None:
    with provision_redis() as redis_url:
        redis: Redis = Redis.from_url(redis_url)
        try:
            publisher = ProgressPublisher(redis, "test")
            request_id = uuid.uuid4()
            correlation_id = uuid.uuid4()

            first = await publisher.publish(
                request_id=request_id,
                correlation_id=correlation_id,
                event_type=EventType.RUN_ACCEPTED,
                payload=_payload(),
                dedupe_key="run.accepted",
            )
            second = await publisher.publish(
                request_id=request_id,
                correlation_id=correlation_id,
                event_type=EventType.RUN_ACCEPTED,
                payload=_payload(),
                dedupe_key="run.progress:1",
            )
            assert first == 1
            assert second == 2
        finally:
            await redis.aclose()


@requires_docker
@pytest.mark.integration
async def test_publish_is_idempotent_on_the_same_dedupe_key() -> None:
    with provision_redis() as redis_url:
        redis: Redis = Redis.from_url(redis_url)
        try:
            publisher = ProgressPublisher(redis, "test")
            request_id = uuid.uuid4()
            correlation_id = uuid.uuid4()

            first = await publisher.publish(
                request_id=request_id,
                correlation_id=correlation_id,
                event_type=EventType.RUN_ACCEPTED,
                payload=_payload(),
                dedupe_key="run.accepted",
            )
            duplicate = await publisher.publish(
                request_id=request_id,
                correlation_id=correlation_id,
                event_type=EventType.RUN_ACCEPTED,
                payload=_payload(),
                dedupe_key="run.accepted",
            )
            assert first == 1
            assert duplicate is None

            stream_key = f"sta:test:run:{request_id}:events"
            entries = await redis.xrange(stream_key)
            assert len(entries) == 1
        finally:
            await redis.aclose()


@requires_docker
@pytest.mark.integration
async def test_published_keys_carry_a_ttl() -> None:
    with provision_redis() as redis_url:
        redis: Redis = Redis.from_url(redis_url)
        try:
            publisher = ProgressPublisher(redis, "test")
            request_id = uuid.uuid4()
            await publisher.publish(
                request_id=request_id,
                correlation_id=uuid.uuid4(),
                event_type=EventType.RUN_ACCEPTED,
                payload=_payload(),
                dedupe_key="run.accepted",
            )
            stream_key = f"sta:test:run:{request_id}:events"
            seq_key = f"sta:test:run:{request_id}:event_seq"
            assert await redis.ttl(stream_key) > 0
            assert await redis.ttl(seq_key) > 0
        finally:
            await redis.aclose()
