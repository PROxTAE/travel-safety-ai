# [M04] External Data Services — Phase 0–2 Handoff

> **This is not a module completion report.** Phases 0, 1 and 2 of
> `IMPLEMENTATION_PLANS/04_EXTERNAL_DATA_SERVICES_IMPLEMENTATION.md` are done.
> Phases 3–7 are not started, so the module acceptance checklist is **not** met.
> Two of seven user-visible capabilities work; the rest are unavailable and say so.

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 04 — external-data · คน 4 |
| Branch | `contract/04-provider-canonical-schema` |
| Base commit | `a814558` (`origin/main`) |
| Commits on branch | 7, on top of `a814558` |
| Contract version | `1.0.0` |
| Docker image | `smart-travel-external-data:latest` · 320 MB |
| Date | 2026-09-19 |
| Scope delivered | Phase 0 (governance), Phase 1 (foundation), Phase 2 (geocoding + weather) |

## 2. Executive summary

The service runs on port 8002, owns its `provider` schema, and answers two
capabilities with real provider data: place-name lookup and route-aware weather
forecasting. Every record it emits carries provenance, freshness and quality.

Five of nine registered providers are keyless, reachable and `ACTIVE`; two of
those five have adapters. The other four are blocked on a credential or a Lead
decision, and the service reports each as explicitly unavailable rather than
pretending otherwise. Nothing is mocked: the only stored provider payloads are
six real captures used exclusively by tests, and a test asserts no runtime module
can load them.

## 3. What was implemented

### Phase 0 — provider governance

| Plan item | Delivered |
| --- | --- |
| 1. Provider registry matrix | `config/providers.yaml` + `docs/provider-registry.md` |
| 2. Lead approval, official doc links | `docs/lead-approval-checklist.md` — **recorded, not decided** |
| 3. Canonical models with คน 5/6 | `docs/canonical-field-mapping.md`, Q1–Q6 open |
| 4. Real sanitized fixtures | 6 live captures + `MANIFEST.json` + `scripts/capture_fixtures.py` |
| 5. Unsupported coverage / degraded UX | `docs/coverage-and-degraded-ux.md`, U1–U3 open |

### Phase 1 — service foundation

| Plan item | Delivered |
| --- | --- |
| 1. FastAPI / internal auth / health / metrics / settings | `app/main.py`, `app/api/`, `app/settings.py`, `app/observability/` |
| 2. Base adapter, error mapping, shared HTTP transport | `app/adapters/base.py`, `app/domain/errors.py`, `app/transport/http.py` |
| 3. Timeout / retry / circuit / rate / quota / cache | `app/transport/resilience.py`, `app/cache/provider_cache.py` |
| 4. Provider health repository / migrations | `app/repositories/`, `0001_provider_schema` |
| 5. Docker non-root / TLS CA / UTC | `Dockerfile` — uid 10001, `ca-certificates`, `TZ=UTC` |

### Phase 2 — geocoding and weather

| Plan item | Delivered |
| --- | --- |
| 1. Typed provider models with drift capture | `extra="ignore"` plus explicit required-field and shape checks |
| 2. Normalization / units / time / source / quality | `app/adapters/open_meteo_*.py`, `app/domain/records.py` |
| 3. Route point batching and ETA alignment | even downsampling to 10 points; nearest forecast hour per ETA |
| 4. Cache / health / contract tests + real canary | 178 tests + 8 canary tests against the live provider |
| 5. Expose internal endpoints | `POST /internal/v1/geocode/search`, `POST /internal/v1/weather/query` |

**Phase 2 exit criterion met:** Bangkok, Chiang Mai, Tokyo and Reykjavik resolve
for real, with forecast and freshness.

## 4. Capability status

| Capability | Endpoint | Status |
| --- | --- | --- |
| Geocoding | `POST /internal/v1/geocode/search` | ✅ live |
| Weather | `POST /internal/v1/weather/query` | ✅ live |
| Provider health | `GET /internal/v1/providers/health` | ✅ live |
| Disaster events | — | ⬜ Phase 3 (providers ACTIVE and reachable, no adapter yet) |
| Road route · emergency POI | — | ❌ no `ORS_API_KEY` |
| Flight | — | ❌ no Amadeus production credential |
| Transit realtime | — | ❌ Lead has not chosen a GTFS region |

## 5. Four design decisions worth reviewing

**The registry gate reconciles config against the environment.** A provider
marked `ACTIVE` whose credential is absent resolves to `PENDING_CREDENTIAL` at
startup and the transport refuses to call it. The inverse also holds: supplying
`ORS_API_KEY` does **not** promote a provider the Lead has not approved, because
`status` records an approval decision, not reachability.

**Provider health comes from observation, never configuration.** An `ACTIVE`
provider with no row in `provider.health` reports `UNKNOWN` with
`last_checked_at: null` and counts as degraded. Adapters write a real observation
after every call — `UP` with measured latency on success, and on failure a state
that preserves the distinction that matters: an auth failure is
`NOT_CONFIGURED` (our key is wrong) while a timeout is `DOWN` (the provider is).

**Route sampling downsamples evenly, not by truncation.** A route capped at its
first ten points reports nothing about the half the traveller has not driven yet.
Survivors carry the reduced `quality.coverage` and an `INCOMPLETE` flag.

**`severity` and `quality.score` stay unset.** Q2/Q3/Q5 are unanswered by
modules 05/06. Inventing a threshold would be a silent decision about what counts
as dangerous weather.

## 6. Three provider traps absorbed by the adapters

Each was found against a real response rather than documentation, and each
produces a plausible-looking wrong answer rather than a crash:

1. **`hourly.time` carries no zone suffix** even under `timezone=UTC` — the
   provider returns `"2026-09-19T00:00"` and reports `timezone: "GMT"`. Parsing
   it as naive local time shifts every forecast by the host offset; on this
   team's machines, by seven hours. The adapter asserts
   `utc_offset_seconds == 0` and attaches UTC explicitly.
2. **`hourly` is column-oriented** — parallel arrays, not a list of objects. A
   short column means rows no longer line up, so every later value would be
   attributed to the wrong hour. That is `PROVIDER_SCHEMA_CHANGED`.
3. **A batched request returns a JSON array** while a single coordinate returns
   an object, and the array carries no id — results map back to samples **by
   position only**. Getting this wrong hands Chiang Mai's weather to someone in
   Bangkok.

## 7. Contract, database and configuration changes

- **API/JSON Schema:** none. `packages/contracts/` untouched; canonical record schemas land with their remaining adapters.
- **Migration:** `0001_provider_schema` creates `provider.{providers,fetch_log,health}` per contract § 8. Up/down/up tested. No raw-provider-body column — `store_raw_body: false` is the retention default.
- **Environment:** one new shared variable, `INTERNAL_SERVICE_TOKEN`.
- **Compose:** `external-data` added to the `app` profile; host port 8002 in dev.

## 8. Review history on this branch

| When (UTC) | What |
| --- | --- |
| 08:43 | Lead review → CHANGES_REQUESTED: health reported `UP` without observation; metrics route label unbounded |
| 08:56 | Both fixed with five regression tests (`1eb518e`) |
| 09:07 | Lead re-ran on `1eb518e` → "✅ ผ่าน — merge ได้เลย" |
| 09:34:18 | Lead merged PR #6 (Phase 2) into this branch → head became `11dc0b8` |
| 09:34:20 | The 09:07 approval was dismissed, since it covered `1eb518e` only |

The Phase 2 content merged at 09:34 has therefore **not been reviewed by anyone**
— PR #6 was merged with zero reviews. That is the main thing a reviewer should
look at now.

## 9. Open items — need a decision

### 9.1 Internal auth scheme is a proposal

Contract § 5 requires service authentication on internal endpoints but names no
mechanism. This branch implements a shared bearer secret, compared in constant
time, rejecting any request carrying a `Cookie`. It fails closed when unset.
**Modules 03 and 05 are the callers and must agree.** The Lead has accepted it as
an MVP proposal and is confirming with those owners.

### 9.2 Schema name conflict — Lead is fixing it

`infra/postgres/init/00-schemas.sql` created `external_data` while contract § 8
and the module plan say `provider`. The migration follows the contract and
creates `provider` itself. The Lead has taken the infra fix into PR #5, which is
still open.

### 9.3 Cross-module questions

`docs/canonical-field-mapping.md` § 7 carries Q1–Q6 for คน 5/6 — chiefly who
derives `severity` and what the `DataQuality.score` formula is.
`docs/coverage-and-degraded-ux.md` carries U1–U3 for คน 1/2.

## 10. Verification evidence

```text
command: uv run ruff check .
result:  All checks passed!

command: uv run mypy app
result:  Success: no issues found in 34 source files

command: uv run pytest
result:  178 passed, 8 deselected (canary), 0 failed

command: uv run pytest -m canary
result:  8 passed against the live provider

command: docker compose ... --profile core --profile app up -d --wait external-data
result:  Up (healthy)

command: alembic upgrade head / downgrade -1 / upgrade head
result:  all three succeed; 4 tables in schema provider

command: docker compose ... exec external-data id
result:  uid=10001(app) gid=10001(app)
```

Live from the running container — Bangkok → Chiang Mai with ETAs:

```text
bkk  valid_at=2026-09-19T10:00:00Z  28.8C  feels 34.2C  rain 0.0mm/95%  wind 8.5km/h
cnx  valid_at=2026-09-19T14:00:00Z  24.6C  feels 30.0C  rain 0.6mm/89%  wind 3.3km/h
     severity=UNKNOWN  score=None  coverage=1.0  eta_offset=0s  observed_at=None
attribution: ['Weather data by Open-Meteo.com (CC BY 4.0)']
```

Health moving from assumption to observation:

```text
before any call:  open_meteo_geocoding  UNKNOWN  last_checked_at=None
after one call:   open_meteo_geocoding  UP       814 ms
                  open_meteo_forecast   UP       947 ms
                  usgs / gdacs / eonet  UNKNOWN  (no adapter yet — correct)
```

### Defects found by the tests during development

- **Log redaction destroyed every timestamp.** The phone pattern matched ISO-8601 dates, so every line logged `"timestamp": "[PHONE]T08:09:49Z"`.
- **404s escaped the error envelope.** Starlette raises its own `HTTPException` for unmatched routes.
- **A blank `ORS_API_KEY=` was read as a present credential**, caught against the live container.

Four more came from the PR #7 review, two of them able to hand a caller a
plausible-looking forecast with no error raised:

- **Concurrent weather requests swapped samples.** One adapter instance serves every request, and the query was stashed on `self` across an `await` — a second request arriving mid-flight relabelled the first one's forecast. The query is now passed into `normalize` explicitly, which makes the whole class of bug impossible for future adapters too.
- **A cached forecast ignored the caller's ETA.** The cache key covered coordinates and window, but the cached records had already been narrowed to the first caller's hour and labelled with their sample ids. A second traveller at the same point got the wrong hour under their own name. ETA and sample ids are now part of the key.
- **The registry mirror never recovered from a first boot.** Bringing the container up before `alembic upgrade head` meant the startup sync failed against missing tables and was never retried, so every later health write failed its foreign key while `/health/ready` still answered UP. Readiness now retries the mirror and reports `registry_mirror`; the dev container migrates before serving.
- **Log redaction ate request and correlation ids.** A uuid4 is digits joined by dashes, so the phone pattern mangled roughly one in four — the same trap as the timestamp case, found by measuring 2,000 of them.

## 11. Safety, security and privacy

- [x] No credential value in the repository, a log, a trace or a fixture; health returns credential *names* only
- [x] Provider-specific messages never reach a consumer — `PROVIDER_AUTH` surfaces as "not configured in this deployment"
- [x] Redaction covers tokens, bearer headers, email, phone and exact coordinates (rounded to ~11 km in logs)
- [x] SSRF: base URLs from config only, redirects disabled, off-host URLs refused
- [x] Timeout budget, cancellation, `Retry-After`, backoff+jitter, circuit breaker
- [x] `SourceProvenance` rejects `observed_at == fetched_at`, so model output cannot pose as a measurement
- [x] Unhandled errors log the exception *type* only
- [ ] Idempotency keys — N/A, no mutating endpoint yet

## 12. Known limitations

1. **Phases 3–7 are not started.** Disaster, routing, transit, flight and the combined `/context/query` do not exist.
2. **The Phase 2 code has not been reviewed** — PR #6 was merged with zero reviews.
3. **Circuit breaker, concurrency limiter and quota tracker are in-process.** Each replica has its own view.
4. **No quota figure is verified** against a live account; all nine carry `verification_required: true`.
5. **A weather request is capped at 10 sample points.** Chunking across requests belongs with the Phase 6 fan-out.
6. **openrouteservice and Amadeus mappings are documentation-derived**, marked NOT VERIFIED — no credential means they have never been called.
7. **`Retry-After` HTTP-date form is not parsed**, only delta-seconds.
8. **`quality.status` is computed at normalization, not on cache read.** Safe only because the 15-minute forecast TTL sits inside the 60-minute freshness window — revisit if either number changes.

## 13. Handoff

**Team Lead** — `services/external-data/docs/lead-approval-checklist.md`: approve
providers (A1–A5), assign credential owners (B1–B3), verify quotas (C1–C4),
confirm licence/attribution (D1–D3). **Phases 4 and 5 cannot start until
B1/B2/A5 are resolved.**

**คน 5 (data-integration)** — Q1–Q6 in `docs/canonical-field-mapping.md` § 7.

**คน 6 (risk-knowledge)** — Q2, Q3, Q6: which feature fields the risk model needs.

**คน 1 / คน 2 (web, public API)** — `docs/coverage-and-degraded-ux.md`: four of
seven user-visible capabilities are unavailable and need an honest disabled state.

**คน 3 / คน 5 (internal API callers)** — agree the internal auth scheme (§ 9.1).

**Next work on this module** — Phase 3 is unblocked: USGS, GDACS and EONET are
keyless, reachable, already `ACTIVE` in the registry, and have real fixtures with
the parsing traps documented in the field mapping.

## 14. How to run

```bash
cp .env.example .env
# fill POSTGRES_PASSWORD, KEYCLOAK_ADMIN_PASSWORD, INTERNAL_SERVICE_TOKEN

# The dev override runs `alembic upgrade head` before serving, so a fresh
# clone needs nothing else. Migrating separately after this line was the
# ordering bug found in review: the container came up against missing tables.
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app up -d --wait

curl -s localhost:8002/health/ready
curl -s -X POST localhost:8002/internal/v1/geocode/search \
  -H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"Chiang Mai","count":2}'
```

> After PR #5 lands, the core services lose their profile and
> `--profile core` becomes unnecessary. These commands need updating then.

Module checks:

```bash
cd services/external-data
uv sync --locked
uv run ruff check . && uv run mypy app && uv run pytest
uv run pytest -m canary   # hits real providers
```

## 15. Rollback

- **Code:** the branch is six commits; revert the feature commits and keep `7c46d7b` (docs and fixtures only) if desired.
- **Database:** `alembic downgrade base` drops all three tables, tested. The empty schema and `alembic_version` remain by design.
- **Provider disable path:** set a provider's `status` to `UNAVAILABLE` in `providers.yaml` and restart. No code change.
