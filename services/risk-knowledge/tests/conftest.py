from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts import IntegratedTravelContext  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def snapshot_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "usgs_route_context.json").read_text(encoding="utf-8"))


@pytest.fixture
def snapshot(snapshot_payload: dict[str, Any]) -> IntegratedTravelContext:
    return IntegratedTravelContext.model_validate(snapshot_payload)
