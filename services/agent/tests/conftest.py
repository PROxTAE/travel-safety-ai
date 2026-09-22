from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings isolated from the developer's real environment: no DATABASE_URL/REDIS_URL, so the
    service starts in its degraded-but-up mode (app/runtime.py) rather than picking up whatever a
    shell happens to export.
    """
    return Settings(_env_file=None)  # type: ignore[arg-type]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
