"""Producer-side check: every published fixture still matches the schema it claims.

`packages/contracts/scripts/validate-examples.mjs` does the same job with ajv. Doing it again with
the Python validator is deliberate: the services validate with Python, the web app with
JavaScript, and a schema that only one of the two accepts is a contract that will fail in
production on whichever side was not tested.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from conftest import COMMON_SCHEMAS


def _registry(schemas: dict[str, Any]) -> Registry:
    """Register each schema under its bare file name, which is how the $refs address it."""
    resources = [
        (name, Resource.from_contents(schema, default_specification=DRAFT202012))
        for name, schema in schemas.items()
    ]
    return Registry().with_resources(resources)


def _target_schema(target: str) -> dict[str, Any]:
    """A one-line schema that defers to the registry.

    Extracting the sub-object by hand would re-root its internal `#/$defs/...` refs at the
    sub-object, where they do not exist. Referring to it instead keeps the file as the base URI.
    """
    file_part, _, pointer = target.partition("#")
    ref = Path(file_part).name + (f"#{pointer}" if pointer else "")
    return {"$ref": ref}


def test_every_schema_is_a_valid_draft_2020_12_schema(schemas: dict[str, Any]) -> None:
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        assert schema.get("title"), f"{name} has no title; generators use it as the type name."
        assert schema.get("description"), f"{name} has no description explaining what it guarantees."


def test_examples_validate_against_their_target(
    examples: list[tuple[Path, dict[str, Any]]], schemas: dict[str, Any]
) -> None:
    registry = _registry(schemas)
    failures: list[str] = []

    for path, fixture in examples:
        target = fixture["target"]
        validator = Draft202012Validator(_target_schema(target), registry=registry)
        for error in validator.iter_errors(fixture["value"]):
            location = "/".join(str(part) for part in error.absolute_path) or "<root>"
            failures.append(f"{path.name} -> {target}: {location}: {error.message}")

    assert not failures, "Fixtures no longer match their schemas:\n" + "\n".join(failures)


@pytest.mark.parametrize("required", ["target", "kind", "summary", "value", "provenance"])
def test_every_fixture_declares_its_wrapper_fields(
    examples: list[tuple[Path, dict[str, Any]]], required: str
) -> None:
    missing = [path.name for path, fixture in examples if required not in fixture]
    assert not missing, f"Fixtures missing '{required}': {missing}"


def test_real_sanitized_fixtures_record_where_they_came_from(
    examples: list[tuple[Path, dict[str, Any]]],
) -> None:
    """A captured fixture without provenance is indistinguishable from an invented one."""
    required = {
        "provider",
        "source_url",
        "captured_at",
        "license",
        "attribution",
        "upstream_content_hash",
        "redaction",
    }
    failures: list[str] = []

    for path, fixture in examples:
        if fixture.get("kind") != "real-sanitized":
            continue
        assert "real-sanitized" in path.parts, f"{path.name} is real-sanitized but filed elsewhere."
        missing = required - set(fixture.get("provenance", {}))
        if missing:
            failures.append(f"{path.name}: missing provenance {sorted(missing)}")

    assert not failures, "\n".join(failures)


def test_no_fixture_is_referenced_from_runtime_code() -> None:
    """Fixtures are for tests. One reaching a user is a fabricated safety answer.

    Scoped to `app/` directories and to references to *this* folder. Earlier versions matched the
    phrase "real-sanitized" anywhere under services/, which flagged module 04 for having its own
    fixture directory of that name and for a docstring saying where its fixtures came from — both
    of which are exactly what a service should do.
    """
    repo_root = COMMON_SCHEMAS.parents[3]
    runtime_dirs = [
        path
        for parent in ("services", "apps")
        for path in (repo_root / parent).glob("*/app")
        if path.is_dir()
    ]

    offenders: list[str] = []
    for directory in runtime_dirs:
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".js", ".mjs"}:
                continue
            if "node_modules" in path.parts or ".venv" in path.parts:
                continue
            if "contracts/examples" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(repo_root)))

    assert not offenders, f"Runtime code must not read contract fixtures: {offenders}"
