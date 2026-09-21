from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.contracts import IntegratedTravelContext

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def snapshot_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "usgs_route_context.json").read_text(encoding="utf-8"))


@pytest.fixture
def snapshot(snapshot_payload: dict[str, Any]) -> IntegratedTravelContext:
    return IntegratedTravelContext.model_validate(snapshot_payload)
