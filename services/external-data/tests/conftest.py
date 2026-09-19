"""Shared test fixtures.

Nothing here reaches the network or a real database. Tests that would hit a live
provider are marked `canary` and excluded from the default run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.settings import Settings, get_settings

SERVICE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = SERVICE_ROOT / "tests" / "fixtures" / "real-sanitized"
REGISTRY_PATH = SERVICE_ROOT / "config" / "providers.yaml"

TEST_TOKEN = "test-internal-token"  # not a credential: a fixed value for tests


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Deterministic environment.

    Provider credentials are explicitly cleared so the default test run always
    exercises the "credential missing" path - that is the state the team is
    actually deployed in.
    """
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("GTFS_PROVIDER_CONFIG", str(REGISTRY_PATH))
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")
    # Point the dependencies at a closed local port rather than the compose
    # hostnames. They are still unreachable - which is what the degraded-path
    # tests want - but they fail on connect instead of waiting out a DNS lookup
    # for "postgres" and "redis" on every single cache call.
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "1")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    for name in ("ORS_API_KEY", "AMADEUS_CLIENT_ID", "AMADEUS_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


def load_fixture(relative: str) -> Any:
    """Read a captured provider response by its path in MANIFEST.json."""
    return json.loads((FIXTURE_ROOT / relative).read_text(encoding="utf-8"))


@pytest.fixture
def manifest() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
