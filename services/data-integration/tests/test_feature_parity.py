"""Online API and offline batch features must be identical for the same request.

Requests are built from module 04 captures in tests/fixtures/m04-*.json
(Open-Meteo Bangkok, USGS, openrouteservice route, MTA GTFS-RT). Route lines are
test-only geometries on captured coordinates.
"""

import json
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import make_url

from app.cli.features import BatchInputError, main, run
from app.main import create_app
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"
LINE = [[100.495865, 13.743409], [100.505865, 13.743409]]


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def request(**changes: Any) -> dict[str, Any]:
    route = record("m04-route-candidates.json") | {
        "geometry": {"type": "LineString", "coordinates": LINE}
    }
    weather, quake = record("m04-weather-forecast-points.json"), record("m04-usgs-event.json")
    body = {
        "request_id": str(uuid4()),
        "trip_id": str(uuid4()),
        "travel_window": {
            "starts_at": "2026-09-19T00:00:00Z",
            "ends_at": "2026-09-19T01:00:00Z",
            "timezone": "Asia/Bangkok",
        },
        "recommendation_at": "2026-09-20T18:00:00Z",
        "route": route,
        "evidence": {"weather": [weather], "disaster_events": [quake], "transport": []},
        "source_quality": {
            "route": route["quality"],
            "weather": weather["quality"],
            "disaster": quake["quality"],
        },
    }
    return body | changes


def cases() -> list[dict[str, Any]]:
    weather = record("m04-weather-forecast-points.json")
    return [
        request(),
        request(evidence={"weather": None, "disaster_events": None, "transport": None}),
        request(recommendation_at="2026-09-20T17:00:00Z"),
        request(
            evidence={
                "weather": [weather | {"severity": "SEVERE"}],
                "disaster_events": [],
                "transport": [],
            }
        ),
    ]


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@pytest.fixture
async def client(
    isolated_database: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("POSTGRES_DB", make_url(isolated_database).database or "")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", secrets.token_urlsafe(32))
    get_settings.cache_clear()
    app = create_app()
    token = get_settings().internal_service_token
    assert token is not None
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        ) as http:
            yield http
    get_settings.cache_clear()


async def test_batch_features_equal_online_snapshot_features(client: httpx.AsyncClient) -> None:
    bodies = cases()
    rows = [json.loads(row) for row in run([json.dumps(b) for b in bodies], get_settings())]
    assert len(rows) == len(bodies)
    for body, row in zip(bodies, rows, strict=True):
        online = (await client.post("/internal/v1/snapshots", json=body)).json()["data"]
        # Bitwise: the serialized feature maps must be byte-identical.
        assert canonical(row["features"]) == canonical(online["features"])
        assert row["feature_schema_version"] == online["feature_schema_version"]
        # PostgreSQL JSONB reorders object keys, so compare the null set, not its order.
        assert set(row["null_features"]) == {k for k, v in online["features"].items() if v is None}


def test_batch_is_deterministic_and_keeps_nulls() -> None:
    lines = [json.dumps(b) for b in cases()]
    first, second = run(lines, get_settings()), run(lines, get_settings())
    assert first == second
    unavailable = json.loads(first[1])
    assert unavailable["features"]["max_weather_severity_ordinal"] is None
    assert "corridor_official_closure_active" in unavailable["null_features"]


def test_invalid_line_names_the_line_but_not_its_values() -> None:
    secret = "do-not-echo-" + secrets.token_hex(8)
    lines = [json.dumps(request()), json.dumps(request(trip_id=secret))]
    with pytest.raises(BatchInputError) as failure:
        run(lines, get_settings())
    assert "line 2" in str(failure.value)
    assert secret not in str(failure.value)


def test_failed_batch_writes_no_output(tmp_path: Path) -> None:
    source, target = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    source.write_text(json.dumps(request()) + "\n{not json}\n", encoding="utf-8")
    assert main(["--input", str(source), "--output", str(target)]) == 2
    assert not target.exists()
    source.write_text(json.dumps(request()) + "\n", encoding="utf-8")
    assert main(["--input", str(source), "--output", str(target)]) == 0
    assert len(target.read_text(encoding="utf-8").splitlines()) == 1
