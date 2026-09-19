"""Internal API contract: envelopes, auth and the provider health endpoint.

Runs without Postgres or Redis. The dependencies are absent on purpose - it lets
these tests assert the degraded behaviour the team will actually meet first.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
HEALTH_PATH = "/internal/v1/providers/health"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_live_probe_touches_no_dependency(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "UP"}


def test_ready_reports_down_when_dependencies_are_missing(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "DOWN"
    assert body["checks"]["postgres"] == "DOWN"
    assert body["checks"]["internal_auth"] == "UP"


def test_metrics_endpoint_exposes_prometheus_text(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "external_data_http_requests_total" in response.text


def test_correlation_headers_are_echoed(client: TestClient) -> None:
    response = client.get(
        "/health/live",
        headers={"X-Request-ID": "req-1", "X-Correlation-ID": "corr-1"},
    )
    assert response.headers["X-Request-ID"] == "req-1"
    assert response.headers["X-Correlation-ID"] == "corr-1"
    assert response.headers["X-Contract-Version"] == "1.0.0"


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.headers["X-Request-ID"]


def test_internal_route_requires_a_credential(client: TestClient) -> None:
    response = client.get(HEALTH_PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_internal_route_rejects_a_wrong_credential(client: TestClient) -> None:
    response = client.get(HEALTH_PATH, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_internal_route_rejects_browser_cookies(client: TestClient) -> None:
    """Contract § 5: internal endpoints must not accept a browser token."""
    response = client.get(
        HEALTH_PATH, headers={**AUTH, "Cookie": "session=abc"}
    )
    assert response.status_code == 401


def test_missing_token_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.settings import get_settings

    monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
    get_settings.cache_clear()

    with TestClient(create_app()) as unconfigured:
        assert unconfigured.get(HEALTH_PATH, headers=AUTH).status_code == 401
        ready = unconfigured.get("/health/ready").json()
        assert ready["checks"]["internal_auth"] == "NOT_CONFIGURED"


def test_provider_health_uses_the_success_envelope(client: TestClient) -> None:
    body = client.get(HEALTH_PATH, headers=AUTH).json()

    assert set(body) == {"data", "meta"}
    meta = body["meta"]
    assert meta["contract_version"] == "1.0.0"
    assert meta["request_id"]
    assert "degraded_services" in meta


def test_provider_health_lists_every_registry_entry(client: TestClient) -> None:
    providers = client.get(HEALTH_PATH, headers=AUTH).json()["data"]["providers"]
    assert len(providers) == 9
    assert {p["provider"] for p in providers} >= {"usgs_earthquake", "gdacs"}


def test_blocked_providers_are_reported_as_degraded(client: TestClient) -> None:
    body = client.get(HEALTH_PATH, headers=AUTH).json()
    degraded = set(body["meta"]["degraded_services"])
    assert {"openrouteservice", "amadeus", "gtfs_registry", "ors_pois"} <= degraded


def test_health_names_missing_credentials_but_never_values(
    client: TestClient,
) -> None:
    providers = client.get(HEALTH_PATH, headers=AUTH).json()["data"]["providers"]
    ors = next(p for p in providers if p["provider"] == "openrouteservice")

    assert ors["effective_status"] == "PENDING_CREDENTIAL"
    assert ors["missing_credentials"] == ["ORS_API_KEY"]
    assert ors["health"] == "NOT_CONFIGURED"


def test_health_response_contains_no_secret_material(client: TestClient) -> None:
    raw = client.get(HEALTH_PATH, headers=AUTH).text
    assert TEST_TOKEN not in raw
    assert "password" not in raw.lower()


def test_health_reports_quota_as_unverified(client: TestClient) -> None:
    providers = client.get(HEALTH_PATH, headers=AUTH).json()["data"]["providers"]
    assert all(p["quota_verified"] is False for p in providers)


def test_unknown_route_returns_the_error_envelope(client: TestClient) -> None:
    body = client.get("/internal/v1/does-not-exist", headers=AUTH).json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["meta"]["contract_version"] == "1.0.0"


def test_active_provider_without_observation_is_unknown_not_up(
    client: TestClient,
) -> None:
    """An ACTIVE provider that has never been reached is UNKNOWN, not UP.

    Reporting UP from configuration alone is an assumption about the outside
    world, and modules 03/05 route requests on this answer.
    """
    providers = client.get(HEALTH_PATH, headers=AUTH).json()["data"]["providers"]
    usgs = next(p for p in providers if p["provider"] == "usgs_earthquake")

    assert usgs["effective_status"] == "ACTIVE"
    assert usgs["health"] == "UNKNOWN"
    assert usgs["last_checked_at"] is None


def test_unobserved_providers_count_as_degraded(client: TestClient) -> None:
    body = client.get(HEALTH_PATH, headers=AUTH).json()
    degraded = set(body["meta"]["degraded_services"])
    # Nothing has been probed in this suite, so every provider is degraded.
    assert degraded == {p["provider"] for p in body["data"]["providers"]}


def test_every_provider_reports_a_last_checked_field(client: TestClient) -> None:
    providers = client.get(HEALTH_PATH, headers=AUTH).json()["data"]["providers"]
    assert all("last_checked_at" in p for p in providers)


def test_unmatched_paths_share_one_metric_label(client: TestClient) -> None:
    """Regression: the route label was read before the router resolved it, so
    it fell back to the raw URL and every scanned path minted a new series."""
    for suffix in ("zzz-1", "zzz-2", "zzz-3"):
        client.get(f"/internal/v1/{suffix}", headers=AUTH)

    metrics = client.get("/metrics").text
    assert 'route="unmatched"' in metrics
    for suffix in ("zzz-1", "zzz-2", "zzz-3"):
        assert f'route="/internal/v1/{suffix}"' not in metrics


def test_matched_routes_keep_their_templated_path(client: TestClient) -> None:
    client.get(HEALTH_PATH, headers=AUTH)
    metrics = client.get("/metrics").text
    assert f'route="{HEALTH_PATH}"' in metrics


def test_readiness_reports_the_registry_mirror_as_down_without_a_database(
    client: TestClient,
) -> None:
    """Loading providers.yaml says nothing about whether its rows reached the
    database. Until they have, every health observation fails its foreign key,
    so reporting ready would be a lie."""
    body = client.get("/health/ready").json()

    assert body["checks"]["provider_registry"] == "UP"  # the file parsed
    assert body["checks"]["registry_mirror"] == "DOWN"  # the rows did not land
    assert body["status"] == "DOWN"


def test_readiness_retries_the_mirror_instead_of_waiting_for_a_restart(
    client: TestClient,
) -> None:
    """On a first boot the tables do not exist yet, so the startup sync fails.
    Readiness has to keep trying, or the mirror stays empty for the life of the
    process and provider health can only ever answer UNKNOWN."""

    class _RepoOnceMigrated:
        def __init__(self) -> None:
            self.syncs = 0

        async def sync_registry(self, registry: object) -> int:
            self.syncs += 1
            return 9

        async def list_health(self) -> list[object]:
            return []

    repo = _RepoOnceMigrated()
    client.app.state.repo = repo  # type: ignore[attr-defined]

    assert client.get("/health/ready").json()["checks"]["registry_mirror"] == "UP"
    assert repo.syncs == 1

    # Once it has succeeded it is not re-run on every probe.
    assert client.get("/health/ready").json()["checks"]["registry_mirror"] == "UP"
    assert repo.syncs == 1
