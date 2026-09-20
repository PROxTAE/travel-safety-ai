# [M04] External Data Services — Completion Report (Phase 0–7)

> All eight phases of
> `IMPLEMENTATION_PLANS/04_EXTERNAL_DATA_SERVICES_IMPLEMENTATION.md` are done.
> Six of seven capabilities answer with real provider data. The seventh,
> flight, is permanently unavailable rather than unfinished: § 5 of the shared
> context forbids serving Amadeus *test* data as a real result, and the project
> has no production credential. The module reports it as unavailable, which is
> what the plan asks for when a capability cannot be served honestly.
>
> The acceptance checklist is walked item by item in § 16 with the evidence for
> each. Two items are partial and say so.

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 04 — external-data · คน 4 |
| Branch | `feat/04-route-adapter` |
| Base commit | `b633480` (`origin/main`) |
| Merged so far | `29a1798` (Phase 0–2, PR #7) · `b633480` (Phase 3, PR #8–#11) |
| Contract version | `1.0.0` |
| Docker image | `smart-travel-external-data:latest` · 320 MB |
| Date | 2026-09-20 |
| Scope delivered | Phase 0–7, all |
| Endpoints | 8 · geocode, weather, disasters, routes, places, transport, context, provider health |
| Providers | 9 registered · 7 callable · 1 permanently unavailable · 1 pending |
| Tests | 531 unit + contract, 28 live canaries |

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

### Phase 3 — disaster sources

USGS, GDACS and NASA EONET adapters, `POST /internal/v1/disasters/query`, a
cross-source duplicate grouper and a periodic provider health probe. The three
sources fan out in parallel and are complementary, not interchangeable: the same
earthquake appears in more than one, and the grouper annotates duplicates
without ever removing one.

Eleven provider traps are absorbed and each has a test: epoch-millisecond
timestamps, a three-ordinate Point that hides a depth, feeds with no bbox or
time parameter, PAGER alert vs magnitude, naive UTC timestamps, string
`"false"` booleans, empty event names, a Green/Orange/Red scale that is not
`Severity`, geometry that is a storm track rather than a point, `closed: null`
meaning "still running", and per-category magnitude units.

### Phase 4 — routing and the emergency directory

openrouteservice Directions v2 and POIs, `POST /internal/v1/routes/query` and
`POST /internal/v1/places/nearby`, activated on 2026-09-20 once a real key
existed and both endpoints answered for real.

Four things worth knowing:

- **Two provider limits were measured, not recalled.** ORS refuses
  `alternative_routes` alongside via points, and caps `target_count` at 3. Both
  rejections are stored as fixtures, and both are checked client-side so a
  caller gets a coverage answer instead of a provider 400.
- **A 404 from this provider is often not an outage.** Error 2010 means the
  coordinate is off the road network. Treating it as a failure would mislead the
  caller and, after a few such requests, open the circuit breaker against a
  healthy provider.
- **The POI category ids were read from the provider's own list endpoint.** The
  first attempt used a plausible-looking group id and a "nearest hospital"
  search returned a pub 250 m away. There is now a canary that would catch it.
- **Quota is per endpoint, and now verified.** Measured from the provider's own
  `X-Ratelimit-*` headers: 200 directions calls a day, 50 POI calls a day.
  Sharing one account does not mean sharing one budget — treating them as one
  pool would let route lookups quietly exhaust the emergency directory.

### Phase 5 — transit realtime

GTFS and GTFS-Realtime for one registered agency, `POST /internal/v1/transport/query`.

The plan requires at least one real GTFS-RT region to work for the demo.
Bangkok cannot be it: the city publishes a static GTFS snapshot and no live
feed, which was checked before an alternative was chosen rather than assumed.
The registered region is the New York City subway, whose schedule and realtime
feeds need no credential — which also fits a project running entirely on free
tiers.

Four provider behaviours absorbed, all established by calling the real feeds:

- **The realtime `trip_id` is not the schedule `trip_id`.** Schedule writes
  `BSP26GEN-A055-Sunday-00_051550_A..N54R`; realtime writes `051550_A..N54R`.
  Joining with `==` matches **zero of sixty-seven** live trips — and nothing
  errors, because an unmatched trip is a valid record with no schedule
  attached. A broken join returns sixty-six healthy-looking records that all
  say `UNKNOWN`, and the endpoint returns 200.
- **Even joined correctly, only about a third of live trips have a published
  counterpart.** That is normal. The rest report `UNKNOWN` with a null delay
  rather than a comforting `ON_TIME`.
- **The provider's `delay` field is usually zero even when a train is late.**
  It reports absolute times instead, so delay is computed against the schedule.
- **Schedule clock times are local to the agency.** Reading them as UTC made
  every New York train 250 minutes late — a four-hour offset plus a real
  ten-minute delay, and a plausible enough number to ship.

### Phase 6 — combined context

`POST /internal/v1/context/query` fans out to every capability under one
deadline with bounded concurrency. A capability that overruns is cancelled and
reported; everything that finished still returns. Five capabilities answered in
5.6 s against a slowest-source time of 5.5 s.

Every capability appears in `capabilities[]` with what happened to it, including
the ones that did not run. An absent key is indistinguishable from "nothing to
report", and for hazards those are opposite answers.

### Phase 7 — final verification

Four things that did not exist before:

- **A contract-drift test.** `tests/contract/test_canonical_contract.py` runs
  real captured responses through the real adapters and validates the output
  against `packages/contracts`. It exists because the schema and this producer
  drifted apart twice and both times nobody found out until someone validated
  by hand.
- **A resilience suite.** 429, timeout, malformed payload, stale data, and one
  capability failing while others answer — nineteen cases, each asking what a
  caller receives rather than whether an exception was raised.
- **A secrets and PII audit.** Source, logs, fixtures and responses, checked
  separately because each fails differently and none of them raises.
- **CI.** This module had no workflow at all. `external-data.yml` runs lint,
  types, the suite, the three checks above, a licence/attribution check, a
  non-root image check, and a grep that fails the build if this module ever
  starts deciding `risk_level` or `severity`.

## 4. Capability status

| Capability | Endpoint | Status |
| --- | --- | --- |
| Geocoding | `POST /internal/v1/geocode/search` | ✅ live |
| Weather | `POST /internal/v1/weather/query` | ✅ live |
| Provider health | `GET /internal/v1/providers/health` | ✅ live |
| Disaster events | `POST /internal/v1/disasters/query` | ✅ live (USGS + GDACS + EONET) |
| Road route | `POST /internal/v1/routes/query` | ✅ live |
| Emergency POI | `POST /internal/v1/places/nearby` | ✅ live |
| Transit realtime | `POST /internal/v1/transport/query` | ✅ live (one registered region) |
| Combined context | `POST /internal/v1/context/query` | ✅ live (fans out to all five) |
| Flight | — | ⛔ **permanently unavailable.** § 5 forbids serving Amadeus test data as a real result and there is no production credential. Not a gap waiting to be filled — the honest end state the plan allows. |

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

### 9.4 `RouteCandidate.exposure` cannot be filled by its producer

Contract § 3.8 marks `exposure` required and PR #15 freezes it as
`required: ["score", "closed"]`, both non-nullable. Module 04 is the producer
(§ 5.2, `/internal/v1/routes/query` → "raw-canonical `RouteCandidate[]`") and it
cannot supply either value: exposure needs the route intersected with hazards
and weather, which is module 05/06 work.

Emitting `score: 0, closed: false` would be the most dangerous thing this module
could do. A route across a closed bridge would arrive at module 07 asserting, in
the contract's own vocabulary, that nothing is wrong — and § 2 is explicit that
official closures must never be weakened.

So module 04 emits `exposure: null`, `risk_level: UNKNOWN`, and flags every
route `INCOMPLETE`. **Decision needed:** either make `exposure` nullable in the
frozen schema, or split a raw producer shape from the evaluated one. Raised on
PR #15.

### 9.5 Disaster freshness measured the wrong thing — fixed in PR #19

Kept here rather than deleted: it is the clearest example so far of a defect
that every test agreed with.

All three disaster adapters computed `age_seconds` from when the *event*
happened rather than from how old our copy of the feed is. With the ten-minute
budget shared context § 10 gives disaster events, that marked every event older
than ten minutes `STALE`. A live query on 2026-09-20 returned 268 events, **268
of them STALE and none FRESH**, including all 32 quakes of magnitude 5.0 and
above.

Two things were wrong at once. A field carrying the same value on every record
tells a consumer nothing, and a consumer filtering `status != STALE` — which is
what § 10 tells them to do — received nothing at all.

The § 10 budget is a refresh policy: it says "fetch again" when exceeded, which
is only coherent about a stale read. Re-fetching cannot make an old earthquake
younger.

USGS already published what was needed and the adapter was ignoring it:
`metadata.generated` is the moment the provider built the feed. GDACS and EONET
publish no feed generation time at all, so they now report the age of the read
and say plainly that the provider's own publication lag is not visible to us —
rather than implying it is zero, or substituting the event's age for it. For
GDACS, a record the provider has not revised in over a day while still marking
the event current gets its own `STALE` flag: that is a different question from
the freshness of the read and is reported as a different thing.

Event age was never lost — `effective_at` carries it, and the freshness note
now points there.

**Verified after the fix:** 273 events, all FRESH, `freshness_seconds` 34
against a feed generated 34 seconds earlier.

The part worth remembering: the whole suite passed while this was broken.
Nothing asserted what the field *meant*, only that it was populated. The ten
regression tests in `tests/unit/test_disaster_freshness.py` assert the meaning,
and nine of them fail against the previous code — checked by stashing the fix
and re-running, not assumed.

## 10. Verification evidence

Re-run on 2026-09-20 on `feat/04-route-adapter`:

```text
command: uv run ruff check .
result:  All checks passed!

command: uv run mypy app
result:  Success: no issues found in 45 source files

command: uv run ruff format --check .
result:  81 files already formatted

command: uv run pytest -m "not canary"
result:  624 passed, 28 deselected, 0 failed  [10m53s]

command: uv run pytest -m canary
result:  28 passed against the live providers  [36s]

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

Phase 4, live from the running container — a real road route and a real
emergency-directory lookup:

```text
POST /internal/v1/routes/query  {"waypoints": [[100.5383,13.7649],[100.5878,14.3532]],
                                 "mode": "CAR", "alternatives": 2}
 -> 200
    ORIGINAL      73.7 km  53.1 min   risk_level=UNKNOWN  exposure=None  quality=FRESH [INCOMPLETE]
    ALTERNATIVE   78.7 km  60.8 min   risk_level=UNKNOWN  exposure=None
    attribution: ['Directions courtesy of openrouteservice.org | OpenStreetMap contributors']
    quality note: "freshness is the age of the road graph (built 2026-09-12),
                   not the age of this request"

POST /internal/v1/places/nearby {"longitude":100.5383,"latitude":13.7649,
                                 "radius_m":2000,"place_types":["HOSPITAL","POLICE"]}
 -> 200  19 places
    HOSPITAL  โรงพยาบาลราชวิถี          247.4 m   PARTIAL
    HOSPITAL  โรงพยาบาลพญาไท 2          631.3 m   PARTIAL
    POLICE    สถานีตำรวจนครบาลพญาไท    1060.9 m   PARTIAL
    directory_caveat: "community-maintained OpenStreetMap data; not an official
                       emergency directory ..."
```

Failure paths, same container, none of which is a 500:

```text
waypoints mid-ocean [[0,0],[0.1,0.1]]   -> 422 UNSUPPORTED_COVERAGE  (provider error 2010)
alternatives: 9                          -> 422 VALIDATION_ERROR  body.alternatives LESS_THAN_EQUAL
mode: TRAIN                              -> 422 UNSUPPORTED_COVERAGE
no Authorization header                  -> 401
unknown body field                       -> 422 VALIDATION_ERROR  EXTRA_FORBIDDEN
```

Measured quota, from the provider's own headers rather than a pricing page:

```text
/v2/directions/*   X-Ratelimit-Limit=200  Remaining=192  Reset in 85,785s (~23.8h)
/pois              X-Ratelimit-Limit=50   Remaining=44   Reset in 85,819s (~23.8h)
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

1. **Flight is permanently unavailable**, not unfinished. See § 4.
2. **The Phase 2 code has not been reviewed** — PR #6 was merged with zero reviews.
3. **Circuit breaker, concurrency limiter and quota tracker are in-process.** Each replica has its own view.
4. **Only the two openrouteservice quotas are verified** (200/day directions, 50/day POIs, measured from the provider's rate-limit headers). The other seven still carry `verification_required: true` and, by the registry test, no number at all.
5. **A weather request is capped at 10 sample points.** Chunking across requests belongs with the Phase 6 fan-out.
6. **The Amadeus mapping is still documentation-derived** and marked NOT VERIFIED; it has never been called. openrouteservice is no longer in that state — both its endpoints are exercised by live canaries.
7. **`Retry-After` HTTP-date form is not parsed**, only delta-seconds.
8. **`quality.status` is computed at normalization, not on cache read.** Safe only because the 15-minute forecast TTL sits inside the 60-minute freshness window — revisit if either number changes.
9. **`exposure` and `risk_level` are null/UNKNOWN on every route** — by design, and now by contract too. Module 02 accepted the argument in issue #26 and PR #29 makes `exposure` nullable with an invariant that a route without one must also carry `risk_level: UNKNOWN`, so "not yet assessed" cannot be misread as "low risk".
10. ~~**A disaster record's `quality.status` is `STALE` on effectively every event.**~~ Fixed in PR #19; see § 9.5 for what it was and how it was found. Two related limits remain: the 600-second budget is still hard-coded in the adapters although § 10 requires it to be configurable, and GDACS/EONET publish no feed generation time so their provider-side lag stays unmeasurable.
11. **`/places/nearby` searches a circle around one point.** A route corridor needs many such calls; batching belongs with the Phase 6 fan-out.
12. **Emergency POI data is community-maintained OpenStreetMap.** Not an official directory. Records carry the flags and the response carries an explicit caveat string, but a UI that renders only the pins will still mislead.
13. **Transit covers one agency.** The registered region is the New York City subway, because Bangkok publishes no live GTFS-Realtime at all — only a stale static snapshot. `feeds[]` takes a second agency without code changes.
14. **About two thirds of live transit trips report `UNKNOWN`.** They are running trips with no counterpart in the published timetable, so no delay can be measured. The response states the matched and unmatched counts so a consumer can tell this from a broken feed.
15. **GTFS service-day selection is approximate.** `_pick_scheduled` takes the first candidate whose route matches; if one trip suffix existed under several service ids (Weekday/Sunday) it could pick the wrong day. Not observed in the real feed, not guaranteed.
16. **The parsed GTFS schedule lives in memory**, so each replica holds its own copy. Re-parsing per request would cost more than the realtime call it supports.
17. **Two contract mismatches remain open on `main`** — `route_id` typed as `Uuid`, and `name` non-nullable on `EmergencyPOI`. Both are fixed in module 02's PR #29; `tests/contract/test_canonical_contract.py` waives exactly those two and fails when the waiver stops being needed.

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

## 16. Acceptance checklist, item by item

The checklist at the end of the module plan, each with what was actually run.
Two items are partial and say why.

### ✅ enabled providers call real endpoints, credentials server-side

Seven callable providers, all exercised by live canaries: `pytest -m canary` →
**28 passed**. Nothing is served from a fixture at runtime; the only stored
payloads are under `tests/`.

The one credential this module uses travels in an `Authorization` header built
from `SecretStr` at call time. It is never in a cache key, a fixture, a log or
a response — each checked by its own test in
`tests/contract/test_no_secrets_escape.py`.

### ✅ no mock or sample payload on a runtime path

`grep` for mock switches runs in CI and in a test. No `USE_MOCK`, no
`MOCK_MODE`, no sample data behind a flag. A capability that cannot answer
returns `UNSUPPORTED_COVERAGE`, never invented data.

### ✅ canonical units, timestamps and coordinates are correct

Every coordinate is GeoJSON `[longitude, latitude]` and validated on
construction — `GeoLineString` checks every position, because unlike a single
point a swapped route is invisible until someone opens a map.

Units are stated rather than assumed: metres and seconds on routes, and
`magnitude_unit` alongside `magnitude` because 12,000 acres and 6.5 Mw are not
comparable numbers.

Three timezone and epoch traps are covered by tests: USGS epoch **milliseconds**,
GDACS timestamps with no offset read as UTC, and GTFS clock times local to the
agency with hours past 23 for a trip running after midnight.

### ✅ every record carries provenance, freshness and quality

No record type can be constructed without `quality` and `source`.
`SourceProvenance` refuses to accept `fetched_at` as `observed_at`, because
passing off a fetch time as an observation makes a computed value look like a
measurement.

Freshness measures the age of the data, not the age of the event — this was
wrong for every disaster record until PR #19 (see § 9.5), and the ten
regression tests for it fail against the previous code.

### ✅ provider-specific schema does not leak to consumers

Provider models are internal; only canonical records cross the boundary.
`tests/contract/test_canonical_contract.py` validates real adapter output
against `packages/contracts` on every CI run.

### ✅ unavailable coverage is shown honestly, never invented

The invariant this module is built around. Tested in both directions for every
capability: an empty list means nothing was reported, and "we could not find
out" is an error with a code.

- All hazard sources timing out → error, not `events: []`
- No routing credential → `UNSUPPORTED_COVERAGE` naming what is missing
- A bbox outside every registered transit feed → `UNSUPPORTED_COVERAGE` naming
  the feeds that exist
- No POI tagged nearby → `[]` **and** a caveat string in the payload

### ✅ retry, cache, circuit and quota policies have tests

Retry with `Retry-After`, exponential backoff with jitter, circuit breaker,
per-provider concurrency limiter, cache stampede lock, negative caching, and a
quota tracker reading the provider's own headers. Nineteen resilience cases in
`tests/contract/test_resilience.py` on top of the unit tests.

### ⚠️ official-source priority metadata is correct but one question is open

`authority` is carried per provider and official sources are never weakened.
What is still unsettled is `official` on `DisasterEvent`: it currently means
"the issuing body is a government authority", so a magnitude 0.4 earthquake
nobody needs to act on is `official: true`. Whether it should instead mean "a
warning has been issued" is open item H, raised with the Lead and unanswered.

Nothing downstream is blocked — the field is present and consistent — but a
consumer reading it as "this matters" would be misled.

### ✅ live canaries pass and licence/attribution are documented

`pytest -m canary` → 28 passed. Every ACTIVE provider carries a licence and an
attribution string, checked in CI, and the attribution is returned in the
response body rather than only recorded in config.

### ✅ Docker: non-root, healthy, observable

`uid=10001(app)`, healthcheck green, `/health/live`, `/health/ready` and
`/metrics` all served. CI fails the build if the image runs as root or ships
`.env`, `tests/` or `.git`.

### ⚠️ unit, timezone and coordinate review with module 05 has not happened

The plan asks for this to be checked *with* the data-integration owner. Module
05 has not started, so there is nobody to check it with.

What exists instead: the fixtures, the canonical records and issue #20
describing every endpoint and shape. The three trap categories most likely to
bite that review — epoch units, naive timestamps, and coordinate order — each
have tests and live canaries already.

---

## 17. What the next person should know

**Start here:** `GET /internal/v1/providers/health` tells you what actually
works in your environment rather than what the code can do. It changes with the
credentials on the machine.

**The one rule this module keeps:** it never decides anything. `severity`,
`risk_level` and `exposure` stay UNKNOWN or null even when the underlying
numbers look obvious, because turning a magnitude into a danger level is module
06/07's judgement to make and this module would be guessing. CI greps for it.

**Read the quality flags.** `PARTIAL` with `INCOMPLETE` is not a lesser version
of `FRESH`; it means a specific field is missing and the record says which.

**If a provider changes shape**, the canaries fail before the fixtures do — that
is the whole reason they hit the network. The fixtures cannot detect drift; they
only pin what was true when captured.

**Two contract mismatches are open on `main`** and waived in
`tests/contract/test_canonical_contract.py`. Module 02's PR #29 fixes both, and
the waiver list fails when it stops being needed, so it cannot outlive them.
