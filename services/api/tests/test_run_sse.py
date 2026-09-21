"""The SSE bridge, against a real Redis stream.

What is worth testing here is not that bytes arrive — it is the behaviour a client depends on when
the connection is imperfect:

* ownership is settled **before** the stream opens, while a status code can still say so;
* an event published while the client was away is delivered on reconnect with `Last-Event-ID`,
  because the terminal event is the one that must never be lost;
* the stream closes after a terminal event rather than hanging;
* an event that does not match the contract is dropped and the rest of the stream survives.

These use the compose Redis. Where it is not reachable they skip rather than fail: the bridge is
built to degrade to polling when Redis is down, so a missing Redis is not a broken test.

One constraint shapes every test here: httpx's `ASGITransport` buffers a response body and hands it
over only once the stream ends. So each test drives the stream to a close — with a terminal event,
or with the duration cap — rather than reading from one that stays open. The behaviours being
checked are unaffected; what cannot be asserted this way is *timing*, and none of these do.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis

from app.services import run_events
from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]

COMPOSE_REDIS = "redis://redis:6379/9"


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
async def redis() -> Any:
    """A real Redis on a scratch database, flushed around each test."""
    client: Redis = Redis.from_url(COMPOSE_REDIS, decode_responses=True)
    try:
        await client.ping()
    except Exception:  # Redis is optional for this file
        await client.aclose()
        pytest.skip(f"no Redis at {COMPOSE_REDIS}")
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture
async def sse_app(live_app: FastAPI, key: SigningKeyPair, redis: Redis) -> FastAPI:
    """The live app with its Redis replaced by the reachable one, and a short heartbeat.

    `Settings` is frozen, so the timings are replaced by swapping in a fresh instance rather than
    mutating the existing one — the immutability is deliberate and worth keeping in tests too.
    """
    from app.settings import Settings

    live_app.state.jwks = StubJwks.containing(key)
    live_app.state.redis = redis

    current: Settings = live_app.state.settings
    live_app.state.settings = current.model_copy(
        update={"sse_heartbeat_seconds": 0.3, "sse_max_duration_seconds": 6.0}
    )
    return live_app


@pytest.fixture
async def client(sse_app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=sse_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def token(key: SigningKeyPair) -> str:
    return key.sign({"sub": f"phase5-sse-{uuid.uuid4()}"})


@pytest.fixture
def other_token(key: SigningKeyPair) -> str:
    return key.sign({"sub": f"phase5-sse-other-{uuid.uuid4()}"})


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def place(name: str, lon: float, lat: float) -> dict[str, Any]:
    return {
        "place_id": f"omg-{name.lower()}",
        "display_name": name,
        "coordinates": {"type": "Point", "coordinates": [lon, lat]},
        "country_code": "TH",
        "timezone": "Asia/Bangkok",
        "provider": "open_meteo",
        "confirmed_by_user": True,
    }


async def make_run(client: httpx.AsyncClient, sse_app: FastAPI, token: str) -> str:
    """A trip and a committed run, without going near the agent.

    The assessment endpoint is covered in `test_assessment_runs_http.py`; here the run is written
    directly so these tests are about the stream and nothing else.
    """
    departure = datetime.now(UTC) + timedelta(days=3)
    trip = await client.post(
        "/api/v1/trips",
        json={
            "origin": place("Bangkok", 100.5018, 13.7563),
            "destination": place("ChiangMai", 98.9853, 18.7883),
            "departure_time": departure.isoformat().replace("+00:00", "Z"),
            "timezone": "Asia/Bangkok",
            "travel_modes": ["CAR"],
        },
        headers=auth(token),
    )
    assert trip.status_code == 201, trip.text
    trip_id = uuid.UUID(trip.json()["data"]["trip_id"])

    from app.db.engine import session_scope
    from app.repositories import requests as requests_repo
    from app.repositories import user_profiles

    async with session_scope(sse_app.state.session_factory) as session:
        profiles = await session.execute(
            __import__("sqlalchemy")
            .text("SELECT user_id FROM travel.trips WHERE id = :id")
            .bindparams(id=trip_id)
        )
        owner_id = profiles.scalar_one()
        assert await user_profiles.get_owned(session, owner_id=owner_id) is not None
        row = await requests_repo.create(
            session,
            owner_id=owner_id,
            trip_id=trip_id,
            conversation_id=None,
            input_digest="0" * 64,
            contract_version="1.0.0",
            locale="en-US",
            timezone="Asia/Bangkok",
        )
        return str(row.id)


async def collect(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    *,
    headers: dict[str, str] | None = None,
    stop_after: int = 1,
    deadline_seconds: float = 8.0,
) -> list[tuple[str, dict[str, Any]]]:
    """Read frames until `stop_after` non-heartbeat events have arrived, or the stream closes."""
    events: list[tuple[str, dict[str, Any]]] = []
    request_headers = {**auth(token), **(headers or {})}

    async def _read() -> None:
        async with client.stream("GET", url, headers=request_headers) as response:
            assert response.status_code == 200, await response.aread()
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    name = None
                    data = None
                    for line in frame.splitlines():
                        if line.startswith("event: "):
                            name = line.removeprefix("event: ")
                        elif line.startswith("data: "):
                            data = json.loads(line.removeprefix("data: "))
                    if name is None:
                        continue
                    events.append((name, data or {}))
                    if len([e for e in events if e[0] != "heartbeat"]) >= stop_after:
                        return

    with __import__("contextlib").suppress(TimeoutError, asyncio.TimeoutError):
        await asyncio.wait_for(_read(), timeout=deadline_seconds)
    return events


# --- authorization --------------------------------------------------------------------------------


async def test_a_stream_for_another_users_run_is_404_before_it_opens(
    client: httpx.AsyncClient, sse_app: FastAPI, token: str, other_token: str
) -> None:
    """Settled while a status code can still say so.

    Once the response has begun, a refusal can only be an event, and a browser's `EventSource`
    retries those for ever.
    """
    request_id = await make_run(client, sse_app, token)

    response = await client.get(f"/api/v1/runs/{request_id}/events", headers=auth(other_token))

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


async def test_a_stream_needs_a_token(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/runs/{uuid.uuid4()}/events")
    assert response.status_code == 401


# --- headers --------------------------------------------------------------------------------------


async def test_the_stream_forbids_caching_and_proxy_buffering(
    client: httpx.AsyncClient, sse_app: FastAPI, token: str
) -> None:
    """`X-Accel-Buffering: no` is what stops nginx turning progress into one long silence."""
    request_id = await make_run(client, sse_app, token)

    async with client.stream(
        "GET", f"/api/v1/runs/{request_id}/events", headers=auth(token)
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"].startswith("no-store")
        assert response.headers["x-accel-buffering"] == "no"
        assert "Authorization" in response.headers["vary"]


# --- delivery -------------------------------------------------------------------------------------


async def test_a_published_event_reaches_the_stream(
    client: httpx.AsyncClient, sse_app: FastAPI, redis: Redis, token: str
) -> None:
    request_id = await make_run(client, sse_app, token)
    settings = sse_app.state.settings

    await run_events.publish(
        redis,
        settings,
        request_id=uuid.UUID(request_id),
        event_type="run.progress",
        payload={
            "request_id": request_id,
            "stage": "FETCHING_EXTERNAL_DATA",
            "percent": 20,
            "message_key": "run.fetching_external_data",
        },
    )

    events = await collect(client, f"/api/v1/runs/{request_id}/events", token, stop_after=1)

    named = [event for event in events if event[0] != "heartbeat"]
    assert named, f"no event arrived; got {events}"
    assert named[0][0] == "run.progress"
    assert named[0][1]["stage"] == "FETCHING_EXTERNAL_DATA"


async def test_the_stream_closes_after_a_terminal_event(
    client: httpx.AsyncClient, sse_app: FastAPI, redis: Redis, token: str
) -> None:
    """A stream that stayed open after the answer arrived would hold a worker for nothing."""
    request_id = await make_run(client, sse_app, token)
    settings = sse_app.state.settings

    await run_events.publish(
        redis,
        settings,
        request_id=uuid.UUID(request_id),
        event_type="run.failed",
        payload={
            "request_id": request_id,
            "error": {
                "code": "DEPENDENCY_UNAVAILABLE",
                "message": "The assessment service is unavailable.",
                "field_errors": [],
                "retryable": True,
                "retry_after_seconds": None,
            },
        },
    )

    # No `stop_after` short-circuit needed: if the server does not close, the timeout catches it.
    events = await collect(client, f"/api/v1/runs/{request_id}/events", token, stop_after=99)

    assert [name for name, _ in events if name != "heartbeat"] == ["run.failed"]


async def test_a_reconnect_with_last_event_id_gets_what_it_missed(
    client: httpx.AsyncClient, sse_app: FastAPI, redis: Redis, token: str
) -> None:
    """The reason the bridge uses a stream and not pub/sub.

    The client reads one event, drops, and reconnects. The event published while it was away —
    here the terminal one — must still be delivered, not lost to the gap.
    """
    request_id = await make_run(client, sse_app, token)
    settings = sse_app.state.settings
    run_uuid = uuid.UUID(request_id)

    first_id = await run_events.publish(
        redis,
        settings,
        request_id=run_uuid,
        event_type="run.progress",
        payload={
            "request_id": request_id,
            "stage": "VALIDATING",
            "percent": 5,
            "message_key": "run.validating",
        },
    )
    assert first_id is not None

    await run_events.publish(
        redis,
        settings,
        request_id=run_uuid,
        event_type="run.completed",
        payload={
            "request_id": request_id,
            "recommendation_id": str(uuid.uuid4()),
            "result_url": f"/api/v1/recommendations/{uuid.uuid4()}",
            "status": "COMPLETED",
        },
    )

    resumed = await collect(
        client,
        f"/api/v1/runs/{request_id}/events",
        token,
        headers={"Last-Event-ID": first_id},
        stop_after=99,
    )

    names = [name for name, _ in resumed if name != "heartbeat"]
    assert names == ["run.completed"], f"expected only the missed event, got {names}"


async def test_an_event_that_fails_the_contract_is_dropped_and_the_stream_survives(
    client: httpx.AsyncClient, sse_app: FastAPI, redis: Redis, token: str
) -> None:
    """The leak guard, end to end.

    An event carrying a prompt is written straight to the stream, bypassing `publish`'s own
    validation the way a different service's bug would. The bridge must drop it and still deliver
    the good event behind it.
    """
    request_id = await make_run(client, sse_app, token)
    settings = sse_app.state.settings
    run_uuid = uuid.UUID(request_id)
    key = run_events.stream_key(settings, run_uuid)

    await redis.xadd(
        key,
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "run.progress",
            "occurred_at": datetime.now(UTC).isoformat(),
            "producer": "agent",
            "schema_version": "1",
            "correlation_id": "",
            "payload": json.dumps(
                {
                    "request_id": request_id,
                    "stage": "MAKING_DECISION",
                    "message_key": "run.making_decision",
                    "prompt": "SYSTEM: the traveller's home address is 42 Sukhumvit...",
                }
            ),
        },
    )
    await run_events.publish(
        redis,
        settings,
        request_id=run_uuid,
        event_type="run.failed",
        payload={
            "request_id": request_id,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "The assessment could not be completed.",
                "field_errors": [],
                "retryable": False,
                "retry_after_seconds": None,
            },
        },
    )

    events = await collect(client, f"/api/v1/runs/{request_id}/events", token, stop_after=99)

    names = [name for name, _ in events if name != "heartbeat"]
    assert names == ["run.failed"], f"the invalid event was forwarded: {names}"
    assert "Sukhumvit" not in json.dumps(events)


async def test_an_idle_stream_sends_heartbeats_then_closes_at_the_cap(
    client: httpx.AsyncClient, sse_app: FastAPI, token: str
) -> None:
    """Two behaviours that only show up when nothing is happening.

    Heartbeats, because without them an intermediary closes an idle connection and the client sees
    a failure where there was none. And the duration cap, because an abandoned tab would otherwise
    hold a worker open for ever — the client reconnects with `Last-Event-ID` and loses nothing.
    """
    from app.settings import Settings

    current: Settings = sse_app.state.settings
    sse_app.state.settings = current.model_copy(update={"sse_max_duration_seconds": 1.0})
    request_id = await make_run(client, sse_app, token)

    events = await collect(
        client, f"/api/v1/runs/{request_id}/events", token, stop_after=99, deadline_seconds=6.0
    )

    heartbeats = [name for name, _ in events if name == "heartbeat"]
    assert heartbeats, f"no heartbeat in {events}"
    # The cap closed it: nothing terminal was ever published for this run.
    assert not [name for name, _ in events if name != "heartbeat"]
