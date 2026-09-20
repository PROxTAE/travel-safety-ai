"""Capture module 04 canonical context responses for deterministic tests.

Run from any directory: python services/data-integration/scripts/capture_fixtures.py
No fixture is used on a production runtime path.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "golden"
ENDPOINT = "http://localhost:8002/internal/v1/context/query"
CASE_NAMES = (
    "corridor_normal_bkk_chiang_mai",
    "disasters_cross_source_global",
    "dateline_pair_fiji",
    "route_unavailable_no_credential",
)
SENSITIVE_KEYS = {"authorization", "cookie", "set-cookie", "token", "api_key", "access_token"}
RECORD_KEYS = ("weather", "disaster_events", "routes", "places", "transport")


def token_from_environment() -> str | None:
    token = os.environ.get("INTERNAL_SERVICE_TOKEN")
    if token:
        return token
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("INTERNAL_SERVICE_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"\'') or None
    return None


def sanitized(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if key.lower() in SENSITIVE_KEYS else sanitized(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


def cases(now: datetime) -> dict[str, dict[str, object]]:
    eta = (now + timedelta(hours=6)).replace(minute=0, second=0, microsecond=0)
    bangkok_to_chiang_mai = (
        (100.5018, 13.7563), (100.1372, 15.7047),
        (99.4950, 18.2888), (98.9853, 18.7883),
    )
    return {
        CASE_NAMES[0]: {
            "samples": [
                {"longitude": lon, "latitude": lat,
                 "eta": (eta + timedelta(hours=index * 2)).isoformat(),
                 "sample_id": f"corridor-{index}"}
                for index, (lon, lat) in enumerate(bangkok_to_chiang_mai)
            ],
            "bbox": [97.0, 5.0, 106.0, 21.0],
            "include": ["WEATHER", "DISASTER"],
            "deadline_seconds": 60,
        },
        CASE_NAMES[1]: {
            "bbox": [-180.0, -90.0, 180.0, 90.0],
            "include": ["DISASTER"],
            "deadline_seconds": 60,
        },
        CASE_NAMES[2]: {
            "samples": [
                {"longitude": 179.6, "latitude": -16.6,
                 "eta": eta.isoformat(), "sample_id": "fiji-west"},
                {"longitude": -179.8, "latitude": -16.4,
                 "eta": (eta + timedelta(hours=1)).isoformat(),
                 "sample_id": "fiji-east"},
            ],
            "include": ["WEATHER"],
            "deadline_seconds": 60,
        },
        CASE_NAMES[3]: {
            "waypoints": [[100.5383, 13.7649], [100.5878, 14.3532]],
            "mode": "CAR",
            "include": ["ROUTE"],
            "deadline_seconds": 60,
        },
    }


def capture(name: str, body: dict[str, object], token: str) -> dict[str, object]:
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-ID": str(uuid4()),
            "X-Correlation-ID": str(uuid4()),
            "X-Contract-Version": "1",
        },
        method="POST",
    )
    status: int | None = None
    content_type: str | None = None
    error: str | None = None
    raw = b""
    try:
        with urllib.request.urlopen(request, timeout=75) as response:
            status = response.status
            content_type = response.headers.get("Content-Type")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        content_type = exc.headers.get("Content-Type")
        raw = exc.read()
    except urllib.error.URLError as exc:
        error = f"transport_error:{type(exc.reason).__name__}"

    captured_at = datetime.now(UTC).isoformat()
    try:
        payload: object = json.loads(raw) if raw else {"capture_error": error}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"capture_error": "non_json_response", "http_status": status}
    payload = sanitized(payload)
    serialized = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if token.encode("utf-8") in serialized:
        raise RuntimeError(f"credential appeared in response for {name}; fixture withheld")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_bytes(serialized)

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(meta, dict):
        meta = {}
    counts = {
        key: len(data[key]) if isinstance(data.get(key), list) else 0
        for key in RECORD_KEYS
    }
    degraded = meta.get("degraded_services", [])
    if not isinstance(degraded, list):
        degraded = []
    capabilities = data.get("capabilities", [])
    outcomes = {
        item["capability"]: item["outcome"]
        for item in capabilities
        if isinstance(item, dict) and isinstance(item.get("capability"), str)
        and isinstance(item.get("outcome"), str)
    } if isinstance(capabilities, list) else {}
    degraded_mismatch = any(
        outcome in {"UNAVAILABLE", "FAILED", "TIMED_OUT"}
        for outcome in outcomes.values()
    ) and not degraded
    print(f"{name}: HTTP {status if status is not None else 'NO_RESPONSE'} "
          f"counts={json.dumps(counts, sort_keys=True)} degraded={degraded} "
          f"capabilities={json.dumps(outcomes, sort_keys=True)} "
          f"degraded_mismatch={degraded_mismatch}" +
          (f" error={error}" if error else ""), flush=True)
    return {
        "fixture_id": name,
        "path": f"{name}.json",
        "source_endpoint": ENDPOINT,
        "captured_at": captured_at,
        "request_body": body,
        "http_status": status,
        "content_type": content_type,
        "record_counts": counts,
        "degraded_services": degraded,
        "capability_outcomes": outcomes,
        "degraded_mismatch": degraded_mismatch,
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "redaction_note": "Public landmark coordinates only; request auth header excluded; sensitive response keys redacted recursively.",
        "capture_error": error,
    }


def main() -> int:
    token = token_from_environment()
    if not token:
        print("INTERNAL_SERVICE_TOKEN is unavailable; no request sent", file=sys.stderr)
        return 2
    entries = [capture(name, body, token) for name, body in cases(datetime.now(UTC)).items()]
    manifest = {
        "schema_version": "0.1.0",
        "module": "05-data-integration",
        "note": "Real module 04 responses for deterministic tests only. Freeze test clock against each record's fetched_at; do not edit captured values to simulate staleness.",
        "fixtures": entries,
    }
    (OUT / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return 0 if all(item["http_status"] == 200 for item in entries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
