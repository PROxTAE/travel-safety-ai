# Real sanitized provider fixtures

Phase 0 deliverable 4. Each file is a **real response from a real provider**,
captured once, stored verbatim apart from pretty-printing.

`MANIFEST.json` is the machine-readable provenance record — `source_url`,
`captured_at`, `http_status`, `raw_bytes`, `content_hash` (sha256 of the raw
bytes, not of the pretty-printed file), `license` and `redaction` for every
fixture. The capture is reproducible from the URLs it records.

## Rules

- **Test-only.** These files must never be reachable from a runtime code path.
  `00_SHARED_PROJECT_CONTEXT.md` forbids serving sample payloads as real results,
  and `AI_EXECUTION_INSTRUCTIONS.md` permits sanitized fixtures *only* inside
  deterministic automated tests.
- **No credentials.** Every captured URL is keyless. The capture script rejects any
  payload matching `api_key`, `access_token`, `client_secret`, `bearer …` or
  `authorization` before writing a file.
- **No PII.** All five payloads are public catalogue data — place names, model
  weather output, and public hazard events. No user, account or device data.
- **Timestamps inside the payloads age.** That is intended: fixtures pin the
  *schema*, not the conditions. A test asserting "this forecast is fresh" would
  start failing tomorrow and must be written against injected time instead.

## Contents

| Fixture | Provider | Shape worth knowing |
| --- | --- | --- |
| `open_meteo_geocoding/search_bangkok.json` | Open-Meteo Geocoding | `results[]`, lat/lon as separate floats |
| `open_meteo_weather/forecast_bangkok.json` | Open-Meteo Forecast | `hourly` is **column-oriented** parallel arrays; `time` has **no `Z` suffix** |
| `usgs/significant_month.json` | USGS | GeoJSON; `properties.time` is **epoch ms**; geometry Point has **3 ordinates** (lon, lat, depth) |
| `gdacs/eventlist_eq.json` | GDACS | GeoJSON; `fromdate`/`todate` have **no zone suffix**; `alertlevel` is Green/Orange/Red |
| `eonet/events.json` | NASA EONET v3 | `geometry` is a **list** of positions over time; `closed: null` means still open |

Those five "shape worth knowing" notes are the reason the fixtures exist — each is
a real trap that documentation alone does not make obvious, and each is mapped in
[`../../../docs/canonical-field-mapping.md`](../../../docs/canonical-field-mapping.md).

## Not captured

`openrouteservice` and `Amadeus` have no fixture because no credential exists, so
they have never been called. Their mappings are documentation-derived and marked
**NOT VERIFIED** in the mapping document. They must be re-verified against a real
response before Phase 4/5 is accepted.

## Re-capturing

Re-capture when a provider announces a schema change or a canary detects drift.
Replace the file, regenerate `MANIFEST.json`, and treat any diff beyond changed
values as a contract event, not a routine update.
