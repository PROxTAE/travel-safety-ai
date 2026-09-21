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
    "stored_sha256",
    "stored_bytes",
    "license",
    "redaction",
}

SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|apikey|access[_-]?token|client[_-]?secret|authorization)\b"
)


def _manifest() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))


def test_manifest_lists_every_captured_file() -> None:
    """Every file, not every JSON file.

    This globbed `*.json` until a GTFS schedule (a zip) and a GTFS-Realtime
    message (protobuf) arrived, at which point two unlisted fixtures would have
    sat in the tree with no recorded licence or provenance and nothing would
    have said so.
    """
    on_disk = {
        str(path.relative_to(FIXTURE_ROOT)).replace("\\", "/")
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file() and path.name not in ("MANIFEST.json", "README.md")
    }
    listed = {entry["path"] for entry in _manifest()["fixtures"]}
    assert on_disk == listed


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_entry_has_complete_provenance(entry: dict[str, Any]) -> None:
    assert REQUIRED <= set(entry)
    assert entry["source_url"].startswith("https://")
    assert entry["content_hash"].startswith("sha256:")
    assert entry["captured_at"].endswith("Z")
    assert entry["license"]
    assert entry["redaction"]


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_a_captured_error_says_why_it_was_captured(entry: dict[str, Any]) -> None:
    """Most fixtures are successful responses. A few are deliberately not.

    A provider's refusal is evidence: it is how the openrouteservice limits were
    established, rather than recalled. But an unexplained non-200 sitting in the
    fixture set is indistinguishable from a capture that simply went wrong, so
    one has to say what it is for.
    """
    status = entry["http_status"]
    if status == 200:
        return
    assert 400 <= status < 600, f"{entry['fixture_id']} has an implausible status"
    assert entry.get("note"), f"{entry['fixture_id']} captured HTTP {status} without explaining why"


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_fixture_file_parses_and_is_non_empty(entry: dict[str, Any]) -> None:
    path = FIXTURE_ROOT / entry["path"]
    if path.suffix != ".json":
        # A zip or a protobuf message has its own reader; all that is checked
        # here is that the bytes recorded in the manifest are the bytes on disk.
        assert path.read_bytes()
        return
    assert json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_fixture_carries_no_credential(entry: dict[str, Any]) -> None:
    path = FIXTURE_ROOT / entry["path"]
    text = path.read_text(encoding="utf-8", errors="ignore")
    assert not SECRET_PATTERN.search(text)


@pytest.mark.parametrize("entry", _manifest()["fixtures"], ids=lambda e: e["fixture_id"])
def test_stored_hash_matches_the_bytes_on_disk(entry: dict[str, Any]) -> None:
    """The file must still be the file that was recorded.

    Note which hash this checks. `content_hash` describes the upstream response
    as the provider sent it - compact JSON, or a 5.6 MB archive - while the copy
    in the repository is pretty-printed or trimmed, so the two legitimately
    differ. Asserting the upstream hash against the stored file was the first
    version of this test and it failed on six fixtures that were perfectly fine.
    """
    import hashlib

    raw = (FIXTURE_ROOT / entry["path"]).read_bytes()
    assert entry["stored_sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert entry["stored_bytes"] == len(raw)


def test_capture_urls_are_keyless() -> None:
    for entry in _manifest()["fixtures"]:
        assert not SECRET_PATTERN.search(entry["source_url"])


def test_fixtures_are_not_loadable_from_the_runtime_package() -> None:
    """Guards the rule that fixtures never reach a runtime path.

    Docstrings are allowed to cite the fixture that verified a mapping - that is
    how a reader checks the adapter. What must not exist is executable code that
    names the directory, so only non-docstring string constants are inspected.
    """
    import ast

    app_root = FIXTURE_ROOT.parents[2] / "app"
    offenders: list[str] = []

    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "real-sanitized" in node.value
                and node.value not in docstrings
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == [], f"runtime code references fixtures: {offenders}"
