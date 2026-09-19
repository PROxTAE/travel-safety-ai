"""Every fixture must carry provenance.

Contract acceptance checklist, final item: "real sanitized fixtures ระบุ source
URL, captured_at, license และ redaction note".
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from tests.conftest import FIXTURE_ROOT

REQUIRED = {
    "fixture_id",
    "path",
    "source_url",
    "http_status",
    "captured_at",
    "raw_bytes",
    "content_hash",
    "license",
    "redaction",
}

SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|client[_-]?secret|authorization)\b"
)


def _manifest() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))


def test_manifest_lists_every_captured_file() -> None:
    on_disk = {
        str(path.relative_to(FIXTURE_ROOT)).replace("\\", "/")
        for path in FIXTURE_ROOT.rglob("*.json")
        if path.name != "MANIFEST.json"
    }
    listed = {entry["path"] for entry in _manifest()["fixtures"]}
    assert on_disk == listed


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_entry_has_complete_provenance(entry: dict[str, Any]) -> None:
    assert REQUIRED <= set(entry)
    assert entry["http_status"] == 200
    assert entry["source_url"].startswith("https://")
    assert entry["content_hash"].startswith("sha256:")
    assert entry["captured_at"].endswith("Z")
    assert entry["license"]
    assert entry["redaction"]


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_fixture_file_parses_and_is_non_empty(entry: dict[str, Any]) -> None:
    payload = json.loads((FIXTURE_ROOT / entry["path"]).read_text(encoding="utf-8"))
    assert payload


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_fixture_carries_no_credential(entry: dict[str, Any]) -> None:
    text = (FIXTURE_ROOT / entry["path"]).read_text(encoding="utf-8")
    assert not SECRET_PATTERN.search(text)


def test_capture_urls_are_keyless() -> None:
    for entry in _manifest()["fixtures"]:
        assert not SECRET_PATTERN.search(entry["source_url"])


def test_fixtures_are_not_importable_from_the_runtime_package() -> None:
    """Guards the rule that fixtures never reach a runtime path."""
    from pathlib import Path

    app_root = FIXTURE_ROOT.parents[2] / "app"
    offenders = [
        path.name
        for path in app_root.rglob("*.py")
        if "real-sanitized" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"runtime modules reference fixtures: {offenders}"
    assert Path(app_root).is_dir()
