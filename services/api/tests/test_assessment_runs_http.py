"""Starting, polling and cancelling an assessment, over HTTP against a real PostgreSQL.

`respx` intercepts the outbound calls to modules 03 and 08. Nothing here fakes a *provider*: what
is faked is a sibling internal service that does not exist yet, and what is being tested is this
service's own behaviour when that service answers, refuses, or cannot be reached at all.

The behaviours worth the setup are the ones a reviewer cannot confirm by reading the handler:

* a run exists and is pollable even when the agent was never reachable — the commit-before-call
  ordering, which is the difference between a failure a traveller can see and a request that
  vanished;
* the same `Idempotency-Key` never starts a second assessment;
* a recommendation that does not match the contract is never exposed, and the run fails instead;
* one user's run is indistinguishable from a run that does not exist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]

AGENT_RUNS_URL = "http://agent:8001/internal/v1/runs"
RECOMMENDATION_BASE = "http://recommendation:8006/internal/v1/recommendations"


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
def authed_app(live_app: FastAPI, key: SigningKeyPair) -> FastAPI:
    live_app.state.jwks = StubJwks.containing(key)
    return live_app


@pytest.fixture
async def client(authed_app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=authed_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def token(key: SigningKeyPair) -> str:
    """One fresh user per test, so tests cannot see each other's runs."""
    return key.sign({"sub": f"phase5-{uuid.uuid4()}"})


@pytest.fixture
def other_token(key: SigningKeyPair) -> str:
    return key.sign({"sub": f"phase5-other-{uuid.uuid4()}"})


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


def trip_body() -> dict[str, Any]:
    departure = datetime.now(UTC) + timedelta(days=3)
    return {
        "title": "Bangkok to Chiang Mai",
        "origin": place("Bangkok", 100.5018, 13.7563),
        "destination": place("ChiangMai", 98.9853, 18.7883),
        "departure_time": departure.isoformat().replace("+00:00", "Z"),
        "return_time": (departure + timedelta(days=4)).isoformat().replace("+00:00", "Z"),
        "timezone": "Asia/Bangkok",
        "travel_modes": ["CAR"],
    }


async def make_trip(client: httpx.AsyncClient, token: str) -> str:
    response = await client.post("/api/v1/trips", json=trip_body(), headers=auth(token))
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["trip_id"])


def agent_envelope(**data: Any) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {
            "request_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "contract_version": "1.0.0",
            "generated_at": "2026-09-20T05:00:00Z",
            "degraded_services": [],
        },
    }


def recommendation_body(
    *, recommendation_id: str, request_id: str, trip_id: str, **overrides: Any
) -> dict[str, Any]:
    """A `RecommendationResponse` with every required field the contract lists."""
    payload: dict[str, Any] = {
        "recommendation_id": recommendation_id,
        "request_id": request_id,
        "trip_id": trip_id,
        "status": "COMPLETED",
        "action_code": "NORMAL",
        "risk_level": "LOW",
        "confidence": 0.82,
        "short_summary": "No significant hazards on this route.",
        "reasons": [{"code": "NO_ACTIVE_ALERTS", "weight": 1.0}],
        "sources": [{"provider": "usgs", "fetched_at": "2026-09-20T05:00:00Z"}],
        "freshness": {"fetched_at": "2026-09-20T05:00:00Z"},
        "limitations": [],
        "degraded_services": [],
        "versions": {"contract": "1.0.0"},
        "created_at": "2026-09-20T05:00:00Z",
    }
    payload.update(overrides)
    return {"data": payload, "meta": {"contract_version": "1.0.0"}}


# --- accepting the work ---------------------------------------------------------------------------


@respx.mock
async def test_starting_an_assessment_returns_202_with_both_follow_urls(
    client: httpx.AsyncClient, token: str
) -> None:
    """202, never 200: nothing has been assessed when this returns."""
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )

    response = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    request_id = data["request_id"]
    assert data["status"] in {"QUEUED", "RUNNING"}
    assert data["trip_id"] == trip_id
    assert data["events_url"] == f"/api/v1/runs/{request_id}/events"
    assert data["poll_url"] == f"/api/v1/runs/{request_id}"
    assert response.headers["location"] == f"/api/v1/runs/{request_id}"
    # Nothing about a run may be stored by anything between here and the browser.
    assert response.headers["cache-control"] == "no-store"


@respx.mock
async def test_the_agent_receives_the_stored_journey_not_the_request_body(
    client: httpx.AsyncClient, token: str
) -> None:
    """The journey comes from the trip.

    A client cannot assess one trip while describing another, because the body carries no origin
    and no destination at all.
    """
    trip_id = await make_trip(client, token)
    route = respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(
            202, json=agent_envelope(request_id=str(uuid.uuid4()), status="QUEUED")
        )
    )

    await client.post(
        f"/api/v1/trips/{trip_id}/assessments",
        json={"question": "Is the road safe?", "locale": "th-TH"},
        headers=auth(token),
    )

    sent = route.calls[0].request
    body = httpx.Response(200, content=sent.content).json()
    assert body["trip_id"] == trip_id
    assert body["origin"]["display_name"] == "Bangkok"
    assert body["destination"]["display_name"] == "ChiangMai"
    assert body["timezone"] == "Asia/Bangkok"
    assert body["locale"] == "th-TH"
    # This service's run id is the agent's idempotency key, so an HTTP-level retry of the accept
    # call cannot start a second assessment.
    assert sent.headers["idempotency-key"]
    assert sent.headers["x-correlation-id"]


# --- the commit-before-call ordering --------------------------------------------------------------


@respx.mock
async def test_a_run_survives_an_agent_that_cannot_be_reached(
    client: httpx.AsyncClient, token: str
) -> None:
    """The property the ordering exists for.

    The agent is unreachable, so nothing was assessed. The run must still exist, be pollable, and
    say plainly that it failed — rather than the request disappearing and leaving the traveller
    with nothing to retry and nothing to look at.
    """
    trip_id = await make_trip(client, token)
    respx.post(AGENT_RUNS_URL).mock(side_effect=httpx.ConnectError("no agent here"))

    response = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    assert response.status_code == 202, response.text
    request_id = response.json()["data"]["request_id"]

    polled = await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))
    assert polled.status_code == 200
    state = polled.json()["data"]
    assert state["status"] == "FAILED"
    assert state["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert state["error"]["retryable"] is True
    # Nothing was assessed, so nothing may be offered as a result.
    assert state["recommendation_id"] is None
    assert state["result_url"] is None


@respx.mock
async def test_an_agent_timeout_is_reported_as_a_timeout(
    client: httpx.AsyncClient, token: str
) -> None:
    trip_id = await make_trip(client, token)
    respx.post(AGENT_RUNS_URL).mock(side_effect=httpx.ReadTimeout("too slow"))

    response = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = response.json()["data"]["request_id"]

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "FAILED"
    assert state["error"]["code"] == "DEPENDENCY_TIMEOUT"


# --- idempotency ----------------------------------------------------------------------------------


@respx.mock
async def test_the_same_key_and_body_returns_the_original_run(
    client: httpx.AsyncClient, token: str
) -> None:
    """A retry after a network timeout must not start a second assessment.

    A second run would cost a second set of provider calls and could reach a different verdict
    from the same question, which is the worst possible answer to "did my request go through".
    """
    trip_id = await make_trip(client, token)
    route = respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(
            202, json=agent_envelope(request_id=str(uuid.uuid4()), status="QUEUED")
        )
    )
    headers = {**auth(token), "Idempotency-Key": f"key-{uuid.uuid4()}"}
    body = {"question": "Is the road safe?"}

    first = await client.post(f"/api/v1/trips/{trip_id}/assessments", json=body, headers=headers)
    second = await client.post(f"/api/v1/trips/{trip_id}/assessments", json=body, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["data"]["request_id"] == second.json()["data"]["request_id"]
    assert route.call_count == 1, "the agent was asked twice for one accepted request"


@respx.mock
async def test_the_same_key_with_a_different_body_is_a_conflict(
    client: httpx.AsyncClient, token: str
) -> None:
    """Returning the first run would be answering a question the client did not ask."""
    trip_id = await make_trip(client, token)
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(
            202, json=agent_envelope(request_id=str(uuid.uuid4()), status="QUEUED")
        )
    )
    headers = {**auth(token), "Idempotency-Key": f"key-{uuid.uuid4()}"}

    await client.post(
        f"/api/v1/trips/{trip_id}/assessments", json={"question": "A?"}, headers=headers
    )
    second = await client.post(
        f"/api/v1/trips/{trip_id}/assessments", json={"question": "B?"}, headers=headers
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# --- ownership ------------------------------------------------------------------------------------


@respx.mock
async def test_another_users_run_is_indistinguishable_from_one_that_does_not_exist(
    client: httpx.AsyncClient, token: str, other_token: str
) -> None:
    trip_id = await make_trip(client, token)
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(
            202, json=agent_envelope(request_id=str(uuid.uuid4()), status="QUEUED")
        )
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    mine = await client.get(f"/api/v1/runs/{request_id}", headers=auth(other_token))
    invented = await client.get(f"/api/v1/runs/{uuid.uuid4()}", headers=auth(other_token))

    assert mine.status_code == 404
    assert invented.status_code == 404
    assert mine.json()["error"]["code"] == invented.json()["error"]["code"] == "NOT_FOUND"


async def test_assessing_a_trip_you_do_not_own_is_404(
    client: httpx.AsyncClient, token: str, other_token: str
) -> None:
    trip_id = await make_trip(client, token)
    response = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(other_token))
    assert response.status_code == 404


async def test_a_run_needs_a_token(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/runs/{uuid.uuid4()}")
    assert response.status_code == 401


# --- the recommendation gate ----------------------------------------------------------------------


@respx.mock
async def test_a_completed_run_exposes_the_result_once_it_validates(
    client: httpx.AsyncClient, token: str
) -> None:
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    recommendation_id = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200,
            json=agent_envelope(
                request_id=agent_run, status="COMPLETED", recommendation_id=recommendation_id
            ),
        )
    )
    respx.get(f"{RECOMMENDATION_BASE}/{recommendation_id}").mock(
        return_value=httpx.Response(
            200,
            json=recommendation_body(
                recommendation_id=recommendation_id, request_id=request_id, trip_id=trip_id
            ),
        )
    )

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "COMPLETED"
    assert state["recommendation_id"] == recommendation_id
    assert state["result_url"] == f"/api/v1/recommendations/{recommendation_id}"
    assert state["percent"] == 100


@respx.mock
@pytest.mark.parametrize(
    ("label", "override"),
    [
        ("unknown action code", {"action_code": "TELEPORT"}),
        ("confidence out of range", {"confidence": 4.2}),
        ("no sources", {"sources": []}),
        ("missing freshness", {"freshness": None}),
        ("missing versions", {"versions": None}),
    ],
)
async def test_a_recommendation_that_fails_validation_is_never_exposed(
    client: httpx.AsyncClient, token: str, label: str, override: dict[str, Any]
) -> None:
    """The gate phase 5 item 5 asks for.

    The agent says the run finished and names a result. If that result does not match the
    contract, the run fails and the id is never handed out — an id leading to something this
    service could not parse is worse than no id at all, because the traveller would act on it.
    """
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    recommendation_id = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200,
            json=agent_envelope(
                request_id=agent_run, status="COMPLETED", recommendation_id=recommendation_id
            ),
        )
    )
    respx.get(f"{RECOMMENDATION_BASE}/{recommendation_id}").mock(
        return_value=httpx.Response(
            200,
            json=recommendation_body(
                recommendation_id=recommendation_id,
                request_id=request_id,
                trip_id=trip_id,
                **override,
            ),
        )
    )

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "FAILED", f"{label} was exposed"
    assert state["error"]["code"] == "POLICY_VALIDATION_FAILED"
    assert state["recommendation_id"] is None
    assert state["result_url"] is None


@respx.mock
async def test_a_recommendation_belonging_to_another_run_is_refused(
    client: httpx.AsyncClient, token: str
) -> None:
    """A mismatch here would show one traveller another traveller's journey."""
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    recommendation_id = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200,
            json=agent_envelope(
                request_id=agent_run, status="COMPLETED", recommendation_id=recommendation_id
            ),
        )
    )
    respx.get(f"{RECOMMENDATION_BASE}/{recommendation_id}").mock(
        return_value=httpx.Response(
            200,
            json=recommendation_body(
                recommendation_id=recommendation_id,
                request_id=str(uuid.uuid4()),  # a different run entirely
                trip_id=trip_id,
            ),
        )
    )

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "FAILED"
    assert state["recommendation_id"] is None


@respx.mock
async def test_an_unreachable_recommendation_service_leaves_the_run_in_flight(
    client: httpx.AsyncClient, token: str
) -> None:
    """Neither completed on an unverified result nor failed on a result that may be fine."""
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    recommendation_id = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200,
            json=agent_envelope(
                request_id=agent_run, status="COMPLETED", recommendation_id=recommendation_id
            ),
        )
    )
    respx.get(f"{RECOMMENDATION_BASE}/{recommendation_id}").mock(
        side_effect=httpx.ConnectError("module 08 is down")
    )

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] in {"QUEUED", "RUNNING"}
    assert state["recommendation_id"] is None


# --- progress and state transitions ---------------------------------------------------------------


@respx.mock
async def test_progress_from_the_agent_is_reflected_in_the_poll(
    client: httpx.AsyncClient, token: str
) -> None:
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200,
            json=agent_envelope(
                request_id=agent_run,
                status="RUNNING",
                stage="FETCHING_EXTERNAL_DATA",
                percent=30,
                message_key="run.fetching_external_data",
            ),
        )
    )

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "RUNNING"
    assert state["stage"] == "FETCHING_EXTERNAL_DATA"
    assert state["percent"] == 30
    assert state["message_key"] == "run.fetching_external_data"


@respx.mock
async def test_an_unknown_status_from_the_agent_leaves_the_record_alone(
    client: httpx.AsyncClient, token: str
) -> None:
    """Version skew must not be guessed at. `SUCCEEDED` is not `COMPLETED` until someone says so."""
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200, json=agent_envelope(request_id=agent_run, status="SUCCEEDED")
        )
    )

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "QUEUED"
    assert state["recommendation_id"] is None


@respx.mock
async def test_a_run_the_agent_never_heard_of_fails_rather_than_hanging(
    client: httpx.AsyncClient, token: str
) -> None:
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(return_value=httpx.Response(404))

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "FAILED"
    assert state["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


# --- cancellation ---------------------------------------------------------------------------------


@respx.mock
async def test_cancelling_a_run_stops_it_and_cannot_be_repeated(
    client: httpx.AsyncClient, token: str
) -> None:
    """409 the second time: there is nothing left to cancel, and saying otherwise would be a lie."""
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    cancel_route = respx.post(f"{AGENT_RUNS_URL}/{agent_run}/cancel").mock(
        return_value=httpx.Response(200, json=agent_envelope(status="CANCELLED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    first = await client.delete(f"/api/v1/runs/{request_id}", headers=auth(token))
    second = await client.delete(f"/api/v1/runs/{request_id}", headers=auth(token))

    assert first.status_code == 200
    assert first.json()["data"]["status"] == "CANCELLED"
    assert first.headers["cache-control"] == "no-store"
    assert second.status_code == 409
    assert cancel_route.call_count == 1


@respx.mock
async def test_cancellation_is_recorded_even_when_the_agent_cannot_be_told(
    client: httpx.AsyncClient, token: str
) -> None:
    """Best effort outward, definite inward.

    A cancellation that blocked on an unreachable agent would leave the traveller unsure whether
    they had cancelled anything, which is worse than some wasted compute upstream.
    """
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    respx.post(f"{AGENT_RUNS_URL}/{agent_run}/cancel").mock(
        side_effect=httpx.ConnectError("agent gone")
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    response = await client.delete(f"/api/v1/runs/{request_id}", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "CANCELLED"


@respx.mock
async def test_a_cancelled_run_is_not_revived_by_a_later_agent_report(
    client: httpx.AsyncClient, token: str
) -> None:
    """The state machine's most important promise, end to end over HTTP."""
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    respx.post(f"{AGENT_RUNS_URL}/{agent_run}/cancel").mock(
        return_value=httpx.Response(200, json=agent_envelope(status="CANCELLED"))
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]
    await client.delete(f"/api/v1/runs/{request_id}", headers=auth(token))

    # The agent, not knowing, reports that the work finished successfully.
    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200,
            json=agent_envelope(
                request_id=agent_run, status="COMPLETED", recommendation_id=str(uuid.uuid4())
            ),
        )
    )

    state = (await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))).json()["data"]
    assert state["status"] == "CANCELLED"
    assert state["recommendation_id"] is None


# --- caching --------------------------------------------------------------------------------------


@respx.mock
async def test_a_polled_run_is_private_and_varies_on_authorization(
    client: httpx.AsyncClient, token: str
) -> None:
    """A run's state is one person's journey. No shared cache may hold it."""
    trip_id = await make_trip(client, token)
    agent_run = str(uuid.uuid4())
    respx.post(AGENT_RUNS_URL).mock(
        return_value=httpx.Response(202, json=agent_envelope(request_id=agent_run, status="QUEUED"))
    )
    respx.get(f"{AGENT_RUNS_URL}/{agent_run}").mock(
        return_value=httpx.Response(
            200, json=agent_envelope(request_id=agent_run, status="RUNNING")
        )
    )
    created = await client.post(f"/api/v1/trips/{trip_id}/assessments", headers=auth(token))
    request_id = created.json()["data"]["request_id"]

    response = await client.get(f"/api/v1/runs/{request_id}", headers=auth(token))

    cache_control = response.headers["cache-control"]
    assert "private" in cache_control or cache_control == "no-store"
    assert "public" not in cache_control
    assert "Authorization" in response.headers["vary"]
