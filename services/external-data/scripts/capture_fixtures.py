"""Capture real sanitized provider fixtures (one live call each).

Run from the repo root:

    python services/external-data/scripts/capture_fixtures.py            # all
    python services/external-data/scripts/capture_fixtures.py --only ID  # one

`--only` re-captures a single provider and merges the result into the existing
MANIFEST.json, so fixing one provider's drift does not rewrite every other
fixture's timestamp.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import urllib.request
from datetime import UTC, datetime
from typing import Any

OUT = pathlib.Path("services/external-data/tests/fixtures/real-sanitized")
MANIFEST = OUT / "MANIFEST.json"

# name -> (relative file, url, license, redaction note)
CAPTURES = [
    (
        "open_meteo_geocoding_search_bangkok",
        "open_meteo_geocoding/search_bangkok.json",
        "https://geocoding-api.open-meteo.com/v1/search"
        "?name=Bangkok&count=3&language=en&format=json",
        "CC-BY-4.0 (Open-Meteo), upstream data OpenStreetMap contributors (ODbL)",
        "public place-name records only; no credential in query, no PII in payload",
    ),
    (
        "open_meteo_forecast_bangkok",
        "open_meteo_weather/forecast_bangkok.json",
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=13.7563&longitude=100.5018"
        "&hourly=temperature_2m,apparent_temperature,precipitation,"
        "precipitation_probability,snowfall,wind_speed_10m,wind_gusts_10m,"
        "visibility,weather_code"
        "&forecast_days=2&timezone=UTC&timeformat=iso8601"
        "&wind_speed_unit=kmh&precipitation_unit=mm&temperature_unit=celsius",
        "CC-BY-4.0 (Open-Meteo)",
        "keyless endpoint; coordinates are a public landmark, not a user location",
    ),
    (
        # Batched request. The response is a JSON ARRAY, one entry per requested
        # point, in request order and carrying no id field - the shape the route
        # sampler depends on, and different enough to need its own fixture.
        "open_meteo_forecast_batched",
        "open_meteo_weather/forecast_batched.json",
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=13.7563,18.7883&longitude=100.5018,98.9853"
        "&hourly=temperature_2m,apparent_temperature,precipitation,"
        "precipitation_probability,snowfall,wind_speed_10m,wind_gusts_10m,"
        "visibility,weather_code"
        "&forecast_days=2&timezone=UTC&timeformat=iso8601"
        "&wind_speed_unit=kmh&precipitation_unit=mm&temperature_unit=celsius",
        "CC-BY-4.0 (Open-Meteo)",
        "keyless endpoint; two public landmarks (Bangkok, Chiang Mai), no PII",
    ),
    (
        "usgs_significant_month",
        "usgs/significant_month.json",
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/"
        "significant_month.geojson",
        "US Government public domain (USGS)",
        "public earthquake catalogue; no credential, no PII",
    ),
    (
        "gdacs_eventlist_eq",
        "gdacs/eventlist_eq.json",
        "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=EQ",
        "GDACS terms of use - free reuse with attribution to GDACS/JRC",
        "public multi-hazard event list; no credential, no PII",
    ),
    (
        "eonet_events",
        "eonet/events.json",
        "https://eonet.gsfc.nasa.gov/api/v3/events?limit=5&status=open",
        "NASA open data policy (EONET v3)",
        "public natural-event catalogue; no credential, no PII",
    ),
]

# Anything that looks like a credential must never reach a fixture.
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?token|client[_-]?secret)\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{10,}"),
    re.compile(r"(?i)\bauthorization\b"),
]

UA = "travel-safety-ai/0.0 (module-04 fixture capture; contact: team lead)"


def capture(url: str) -> tuple[bytes, int, str]:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read(), resp.status, resp.headers.get("Content-Type", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="capture a single fixture_id")
    args = parser.parse_args()

    if not OUT.parent.parent.exists():
        print("run me from the repo root", file=sys.stderr)
        return 2

    selected = [c for c in CAPTURES if args.only in (None, c[0])]
    if not selected:
        print(f"unknown fixture id: {args.only}", file=sys.stderr)
        return 2

    existing: dict[str, Any] = {}
    if MANIFEST.exists():
        loaded = json.loads(MANIFEST.read_text(encoding="utf-8"))
        existing = {entry["fixture_id"]: entry for entry in loaded["fixtures"]}

    for name, rel, url, license_, redaction in selected:
        raw, status, ctype = capture(url)
        if status != 200:
            print(f"FAIL {name}: HTTP {status}", file=sys.stderr)
            return 1

        text = raw.decode("utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                print(f"FAIL {name}: possible credential in payload", file=sys.stderr)
                return 1

        payload = json.loads(text)
        pretty = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pretty, encoding="utf-8")

        existing[name] = {
            "fixture_id": name,
            "path": rel,
            "source_url": url,
            "http_status": status,
            "content_type": ctype,
            "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "raw_bytes": len(raw),
            "content_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "license": license_,
            "redaction": redaction,
            "capture_method": (
                "single live GET, stored pretty-printed (UTF-8, 2-space indent)"
            ),
        }
        print(f"ok   {name:38s} {len(raw):>7d}B -> {rel}")

    ordered = [existing[name] for name, *_ in CAPTURES if name in existing]
    MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "module": "04-external-data",
                "note": (
                    "Real provider responses captured once for deterministic tests. "
                    "Never served on a runtime path."
                ),
                "fixtures": ordered,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nMANIFEST.json now lists {len(ordered)} fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
