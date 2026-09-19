# Provider registry — module 04

Phase 0 deliverable 1. Machine-readable twin: [`../config/providers.yaml`](../config/providers.yaml).

`status` is the only field the runtime reads. **Only `ACTIVE` providers may be
called.** Everything else must surface as an explicit unavailable/degraded state —
never as sample or fabricated data.

| status | meaning | runtime behaviour |
| --- | --- | --- |
| `ACTIVE` | approved, reachable, no credential blocker | adapter runs |
| `PENDING_CREDENTIAL` | code may exist, key missing | capability returns `UNSUPPORTED_COVERAGE` + `PROVIDER_AUTH` reason |
| `PENDING_LEAD_APPROVAL` | provider/feed not yet chosen or approved | capability unavailable |
| `UNAVAILABLE` | deliberately off | capability unavailable |

## Matrix

| Provider | Kind | Status | Credential (env) | Owner | Quota (documented, unverified) | Attribution required |
| --- | --- | --- | --- | --- | --- | --- |
| Open-Meteo Geocoding | `GEOCODING` | `ACTIVE` | none | — | free non-commercial tier | yes |
| Open-Meteo Forecast | `WEATHER` | `ACTIVE` | none | — | free non-commercial tier | yes |
| openrouteservice Directions | `ROUTE` | `PENDING_CREDENTIAL` | `ORS_API_KEY` | **TBD — Lead** | daily + per-minute ceiling on free plan | yes |
| openrouteservice POIs | `EMERGENCY_DIRECTORY` | `PENDING_CREDENTIAL` | `ORS_API_KEY` | **TBD — Lead** | shares the routing account quota | yes |
| Amadeus Self-Service | `FLIGHT` | `UNAVAILABLE` | `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` | **TBD — Lead** | test ≠ production tier | yes |
| Agency GTFS / GTFS-RT | `TRANSIT` | `PENDING_LEAD_APPROVAL` | per feed | **TBD — Lead** | per feed, often a minimum poll interval | yes, per feed |
| USGS Earthquake | `DISASTER` | `ACTIVE` | none | — | no published hard quota; feed regenerates ~1/min | yes |
| GDACS | `DISASTER` | `ACTIVE` | none | — | no published hard quota | yes |
| NASA EONET v3 | `DISASTER` | `ACTIVE` | none | — | no published hard quota | yes |

Five of nine entries are `ACTIVE` today. Every quota figure above is transcribed
from public documentation and carries `verification_required: true` in
`providers.yaml` — none has been confirmed against a real account.

## Coverage and licence detail

| Provider | Coverage | Licence | Commercial use |
| --- | --- | --- | --- |
| Open-Meteo Geocoding | global place-name index (GeoNames/OSM derived); thin for informal settlements and recent renames | CC-BY-4.0, upstream ODbL | **no** (free tier is non-commercial) |
| Open-Meteo Forecast | global model output — *not* station observation | CC-BY-4.0 | **no** (free tier is non-commercial) |
| openrouteservice | global OSM road graph; quality follows OSM density; documented caps on `avoid_areas` and alternatives | ORS terms, upstream ODbL | conditional |
| Amadeus | partial global | Amadeus Self-Service terms | conditional |
| GTFS / GTFS-RT | strictly per agency | per feed | per feed |
| USGS | global, authoritative for earthquakes; feeds have **no bbox parameter** | US Gov public domain | yes |
| GDACS | global multi-hazard (EQ, TC, FL, VO, WF, DR) | GDACS terms | conditional |
| NASA EONET | global curated near-real-time; slower than USGS/GDACS | NASA open data | yes |

The Open-Meteo non-commercial restriction is a real constraint on this project's
future, not a footnote — see [`lead-approval-checklist.md`](lead-approval-checklist.md).

## Retention

Default from `00_API_AND_DATA_CONTRACTS.md` § 8: **raw provider bodies are not
persisted.** `defaults.retention` in `providers.yaml` sets
`store_raw_body: false` and `fetch_log_days: 30`. `provider.fetch_log` keeps only
the query hash, HTTP status, timestamps, content hash and quality JSON — enough to
audit a decision without re-storing licensed content.

## Official documentation

| Provider | Docs |
| --- | --- |
| Open-Meteo Forecast | <https://open-meteo.com/en/docs> |
| Open-Meteo Geocoding | <https://open-meteo.com/en/docs/geocoding-api> |
| openrouteservice | <https://openrouteservice.org/dev/> · limits <https://openrouteservice.org/restrictions/> |
| Amadeus Self-Service | <https://developers.amadeus.com/self-service> |
| GTFS-Realtime | <https://gtfs.org/documentation/realtime/reference/> |
| USGS GeoJSON | <https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php> |
| GDACS API | <https://www.gdacs.org/gdacsapi/swagger/index.html> |
| NASA EONET v3 | <https://eonet.gsfc.nasa.gov/docs/v3> |

## Health probes

Each `ACTIVE` provider has a cheap deterministic probe recorded under `health.url`
in `providers.yaml`, feeding `GET /internal/v1/providers/health`. That endpoint
returns status, latency and quota only — **never** a credential, and never the
provider's raw body.

The ORS probe (`/v2/health`) is keyless, so a green probe there does **not** prove
the routing credential works. Phase 4 must add an authenticated canary before
flipping ORS to `ACTIVE`.
