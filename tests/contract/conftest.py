"""Shared fixtures for the contract test suite.

These tests read `packages/contracts` only. They never start a service, never touch a database and
never call a provider, so they stay fast enough to run on every commit and deterministic enough to
be a gate rather than a suggestion.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "packages" / "contracts"
COMMON_SCHEMAS = CONTRACTS / "jsonschema" / "common"
EXAMPLES = CONTRACTS / "examples"
GENERATED_PYTHON = CONTRACTS / "generated" / "python"
BUNDLED_OPENAPI = CONTRACTS / "generated" / "openapi" / "public-api.bundled.yaml"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def contracts_root() -> Path:
    return CONTRACTS


@pytest.fixture(scope="session")
def schemas() -> dict[str, Any]:
    """Every canonical schema, keyed by file name — the key its cross-file $refs use."""
    return {path.name: _load_json(path) for path in sorted(COMMON_SCHEMAS.glob("*.schema.json"))}


@pytest.fixture(scope="session")
def examples() -> list[tuple[Path, dict[str, Any]]]:
    """Every fixture wrapper under examples/, as (path, parsed) pairs."""
    found = [(path, _load_json(path)) for path in sorted(EXAMPLES.rglob("*.json"))]
    assert found, "No example fixtures found; the suite would pass vacuously."
    return found


@pytest.fixture(scope="session")
def generated_models() -> Iterator[Any]:
    """The generated Pydantic models, imported the way a service imports them."""
    if not (GENERATED_PYTHON / "smart_travel_contracts" / "public_api.py").exists():
        pytest.fail(
            "Generated Python models are missing. Run:\n"
            "  cd packages/contracts && npm run generate"
        )
    sys.path.insert(0, str(GENERATED_PYTHON))
    try:
        from smart_travel_contracts import public_api

        yield public_api
    finally:
        sys.path.remove(str(GENERATED_PYTHON))
