"""Shared fixtures for the contract test suite.

These tests read `packages/contracts` only. They never start a service, never touch a database and
never call a provider, so they stay fast enough to run on every commit and deterministic enough to
be a gate rather than a suggestion.
"""

from __future__ import annotations

import functools
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

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


# --- validating a payload against one canonical schema -------------------------------------------
#
# A module-level function rather than a fixture, because the producer tests build a validator inside
# a helper and a fixture cannot be reached from there.


@functools.lru_cache(maxsize=1)
def _common_registry() -> Registry:
    """Every canonical schema, registered under the file name its cross-file `$ref`s use."""
    resources = [
        (path.name, Resource.from_contents(_load_json(path), default_specification=DRAFT202012))
        for path in sorted(COMMON_SCHEMAS.glob("*.schema.json"))
    ]
    return Registry().with_resources(resources)


def validator_for(schema_name: str, pointer: str | None = None) -> Draft202012Validator:
    """A validator for one schema file, or for a `$defs` entry inside it.

    `pointer` is a slash-separated path such as `$defs/WeatherForecastPoint`. Resolving it here
    rather than by `$ref` keeps the error paths rooted at the payload, so a failure names the field
    that is wrong instead of the indirection that found it.
    """
    schema = _load_json(COMMON_SCHEMAS / schema_name)
    if pointer:
        for part in pointer.split("/"):
            schema = schema[part]
        # A fragment lifted out of its file needs the dialect restated, and keeps resolving its own
        # relative `$ref`s against the registry.
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    return Draft202012Validator(schema, registry=_common_registry())
