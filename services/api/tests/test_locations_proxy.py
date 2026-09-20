"""The geocoding proxy, and what it does when module 04 misbehaves.

`respx` intercepts the outbound HTTP call. What is being tested is this service's own behaviour —
how it shapes the request, what it does with the answer, and which failure becomes which status —
not the geocoding provider, which has its own tests in module 04 and must not be called from a unit
suite at all.

The bodies below are shaped like module 04's real `GeocodeResult` envelope. They are fixtures for
deterministic tests and never reach runtime: nothing in `app/` reads this file.

The most important test here is the last group. A provider that is down must not look like a search
that found nothing — a traveller told "no results for Chiang Mai" concludes something very
different from one told "search is unavailable".
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI

from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]

GEOCODE_URL = "http://external-data:8002/internal/v1/geocode/search"


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
    return key.sign({"sub": f"phase4-geo-{uuid.uuid4()}"})


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def geocode_body(*results: dict[str, Any]) -> dict[str, Any]:
    """Module 04's envelope, as `app/api/internal.py` builds it."""
    return {
        "data": {"results": list(results), "attribution": []},
        "meta": {
            "request_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "contract_version": "1.0.0",
            "generated_at": "2026-09-20T05:00:00Z",
            "degraded_services": [],
        },
    }


def result(name: str, lon: float, lat: float, **overrides: Any) -> dict[str, Any]:
    location = {
        "place_id": f"open-meteo-{name.lower()}",
        "display_name": name,
        "coordinates": {"type": "Point", "coordinates": [lon, lat]},
        "country_code": "TH",
        "admin1": name,
        "timezone": "Asia/Bangkok",
        "provider": "open_meteo",
        "confirmed_by_user": False,
    }
    location.update(overrides)
    return {
        "location": location,
        "quality": {"status": "FRESH", "flags": []},
        "source": {"provider": "open_meteo", "fetched_at": "2026-09-20T05:00:00Z"},
    }


# --- the happy path -------------------------------------------------------------------------------


@respx.mock
async def test_matches_are_returned(client: httpx.AsyncClient, token: str) -> None:
    respx.post(GEOCODE_URL).mock(
        return_value=httpx.Response(200, json=geocode_body(result("Chiang Mai", 98.98, 18.78)))
    )

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Chiang Mai"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["display_name"] == "Chiang Mai"
    assert data[0]["coordinates"]["coordinates"] == [98.98, 18.78]


@respx.mock
async def test_a_result_is_never_marked_confirmed(client: httpx.AsyncClient, token: str) -> None:
    """Confirmation is a person looking at a map. No upstream service may assert it for them.

    Even if module 04 sent `true`, this endpoint must not pass it through: the value is what stops
    an unreviewed guess becoming the coordinates every hazard lookup is run against.
    """
    respx.post(GEOCODE_URL).mock(
        return_value=httpx.Response(
            200, json=geocode_body(result("Bangkok", 100.5, 13.75, confirmed_by_user=True))
        )
    )

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
    )

    assert response.json()["data"][0]["confirmed_by_user"] is False


@respx.mock
async def test_no_match_is_an_empty_list(client: httpx.AsyncClient, token: str) -> None:
    respx.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geocode_body()))

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Qqqqqqqq"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == []


@respx.mock
async def test_the_caller_never_supplies_a_url(client: httpx.AsyncClient, token: str) -> None:
    """The base URL is configuration and the path is a constant.

    Anything else would make this service, which sits on the internal network holding a service
    credential, an SSRF proxy for everything behind the firewall.
    """
    route = respx.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geocode_body()))

    await client.get(
        "/api/v1/locations/search",
        headers=auth(token),
        params={"q": "http://169.254.169.254/latest/meta-data/"},
    )

    assert route.called
    assert str(route.calls.last.request.url) == GEOCODE_URL


@respx.mock
async def test_the_profile_locale_chooses_the_language(
    client: httpx.AsyncClient, token: str
) -> None:
    """Someone whose account is Thai gets Thai place names without asking each time."""
    route = respx.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geocode_body()))
    await client.patch("/api/v1/me", headers=auth(token), json={"locale": "th-TH"})

    await client.get("/api/v1/locations/search", headers=auth(token), params={"q": "กรุงเทพ"})

    assert route.calls.last.request.read().decode().count('"language":"th"') == 1


@respx.mock
async def test_an_explicit_locale_overrides_the_profile(
    client: httpx.AsyncClient, token: str
) -> None:
    route = respx.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geocode_body()))
    await client.patch("/api/v1/me", headers=auth(token), json={"locale": "th-TH"})

    await client.get(
        "/api/v1/locations/search",
        headers=auth(token),
        params={"q": "Bangkok", "locale": "en-GB"},
    )

    assert '"language":"en"' in route.calls.last.request.read().decode()


@respx.mock
async def test_the_response_is_privately_cacheable(client: httpx.AsyncClient, token: str) -> None:
    """Private: the query is something a person typed, and the answer follows their locale."""
    respx.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geocode_body()))

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
    )

    assert response.headers["Cache-Control"].startswith("private")
    assert "Authorization" in response.headers["Vary"]


@respx.mock
async def test_the_correlation_id_reaches_the_internal_call(
    client: httpx.AsyncClient, token: str
) -> None:
    """A trace that stops at this service cannot answer why a search was slow."""
    route = respx.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geocode_body()))
    correlation = str(uuid.uuid4())

    await client.get(
        "/api/v1/locations/search",
        headers={**auth(token), "X-Correlation-ID": correlation},
        params={"q": "Bangkok"},
    )

    assert route.calls.last.request.headers["X-Correlation-ID"] == correlation


# --- validation -----------------------------------------------------------------------------------


async def test_a_one_character_query_is_rejected(client: httpx.AsyncClient, token: str) -> None:
    response = await client.get("/api/v1/locations/search", headers=auth(token), params={"q": "x"})

    assert response.status_code == 400, response.text


async def test_search_requires_a_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/locations/search", params={"q": "Bangkok"})

    assert response.status_code == 401, response.text


# --- degraded behaviour ---------------------------------------------------------------------------


@respx.mock
async def test_an_unreachable_provider_is_not_an_empty_result(
    client: httpx.AsyncClient, token: str
) -> None:
    """The distinction this endpoint exists to preserve.

    "No results for Chiang Mai" and "search is broken" lead a traveller to do completely different
    things, and an empty list says the first while meaning the second.
    """
    respx.post(GEOCODE_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Chiang Mai"}
    )

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True


@respx.mock
async def test_a_timeout_is_reported_as_a_timeout(client: httpx.AsyncClient, token: str) -> None:
    respx.post(GEOCODE_URL).mock(side_effect=httpx.ReadTimeout("too slow"))

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
    )

    assert response.status_code == 504, response.text
    assert response.json()["error"]["code"] == "DEPENDENCY_TIMEOUT"


@respx.mock
async def test_an_upstream_server_error_does_not_reach_the_caller(
    client: httpx.AsyncClient, token: str
) -> None:
    respx.post(GEOCODE_URL).mock(
        return_value=httpx.Response(500, json={"error": {"message": "psycopg: host=provider-db"}})
    )

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
    )

    assert response.status_code == 503, response.text
    assert "psycopg" not in response.text
    assert "provider-db" not in response.text


@respx.mock
async def test_an_upstream_4xx_is_our_bug_not_the_callers(
    client: httpx.AsyncClient, token: str
) -> None:
    """We built that request, so a 400 from it is a contract drift between two services.

    Passing it through would tell a user their search was invalid when it was not.
    """
    respx.post(GEOCODE_URL).mock(return_value=httpx.Response(422, json={"error": {}}))

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
    )

    assert response.status_code == 503, response.text


@respx.mock
async def test_an_unrecognisable_body_is_a_dependency_failure(
    client: httpx.AsyncClient, token: str
) -> None:
    """Schema drift is reported, not half-parsed."""
    respx.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
    )

    assert response.status_code == 503, response.text


@respx.mock
async def test_one_malformed_entry_does_not_lose_the_good_ones(
    client: httpx.AsyncClient, token: str
) -> None:
    """A single bad record should not fail a search that returned a usable answer.

    It is dropped rather than passed through, so nothing half-validated reaches the browser.
    """
    respx.post(GEOCODE_URL).mock(
        return_value=httpx.Response(
            200,
            json=geocode_body(
                result("Bangkok", 100.5, 13.75),
                # Latitude 800 does not exist; module 04 should never send it, and if it does the
                # entry must not become a pin on a map.
                result("Nowhere", 100.5, 800.0),
            ),
        )
    )

    response = await client.get(
        "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
    )

    assert response.status_code == 200, response.text
    assert [item["display_name"] for item in response.json()["data"]] == ["Bangkok"]


async def test_a_missing_service_credential_reports_unavailable(
    live_settings: Any, key: SigningKeyPair, token: str
) -> None:
    """Fail closed and say so, without sending an unauthenticated request first.

    Calling without the credential would earn a 401 from module 04 and be reported as that service
    being broken, which sends an operator to look at the wrong thing.

    `assert_all_mocked=False` lets the app's own start-up reach the (unreachable) identity provider
    as it normally would; the assertion is only about what was *not* sent to module 04.
    """
    from app.main import create_app

    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        route = mock.post(GEOCODE_URL).mock(return_value=httpx.Response(200, json=geocode_body()))
        unconfigured = create_app(live_settings.model_copy(update={"internal_service_token": None}))
        unconfigured.state.jwks = StubJwks.containing(key)

        async with unconfigured.router.lifespan_context(unconfigured):
            unconfigured.state.jwks = StubJwks.containing(key)
            transport = httpx.ASGITransport(app=unconfigured, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as bare:
                response = await bare.get(
                    "/api/v1/locations/search", headers=auth(token), params={"q": "Bangkok"}
                )

        assert not route.called, "a request was sent without the service credential"

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
