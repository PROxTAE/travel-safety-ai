# [M04] External Data Services — Phase 0–1 Handoff

> **This is not a module completion report.** Phases 0 and 1 of
> `IMPLEMENTATION_PLANS/04_EXTERNAL_DATA_SERVICES_IMPLEMENTATION.md` are done.
> Phases 2–7 — every actual provider adapter — are not started. The acceptance
> checklist for module 04 is therefore **not** met, and this document says so
> rather than implying otherwise.

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 04 — external-data · คน 4 |
| Branch | `contract/04-provider-canonical-schema` |
| Base commit | `a814558` (`origin/main`) |
| Head commit | `9cbcc43` |
| Contract version | `1.0.0` |
| Docker image | `smart-travel-external-data:latest` · `sha256:d3589f32…` · 320 MB |
| Date | 2026-09-19 |
| Scope delivered | Phase 0 (provider governance), Phase 1 (service foundation) |

## 2. Executive summary

The service boots, is healthy in compose, owns its `provider` schema, and can
report on every provider it knows about — but it does not yet call a single one
of them for data. Phase 1 deliberately built the part that every later phase
depends on: the registry gate, the shared transport with its resilience
policies, provenance/quality value objects, and the internal API skeleton.

Five of nine providers are reachable and keyless (Open-Meteo ×2, USGS, GDACS,
EONET) and have real captured fixtures. Four are blocked on a credential or a
Lead decision, and the service reports each one as explicitly unavailable
instead of pretending otherwise.

## 3. What was implemented

### Phase 0 — provider governance

| Plan item | Delivered |
| --- | --- |
| 1. Provider registry matrix | `services/external-data/config/providers.yaml` + `docs/provider-registry.md` |
| 2. Lead approval, official doc links | `docs/lead-approval-checklist.md` — **recorded, not decided** |
| 3. Canonical models with คน 5/6 | `docs/canonical-field-mapping.md` — field-by-field, with Q1–Q6 open |
| 4. Real sanitized fixtures | 5 live captures + `MANIFEST.json` provenance + `scripts/capture_fixtures.py` |
| 5. Unsupported coverage / degraded UX | `docs/coverage-and-degraded-ux.md` — with U1–U3 open for คน 1/2 |

### Phase 1 — service foundation

| Plan item | Delivered |
| --- | --- |
| 1. FastAPI / internal auth / health / metrics / settings | `app/main.py`, `app/api/`, `app/settings.py`, `app/observability/` |
| 2. Base adapter, error mapping, shared HTTP transport | `app/adapters/base.py`, `app/domain/errors.py`, `app/transport/http.py` |
| 3. Timeout / retry / circuit / rate / quota / cache | `app/transport/resilience.py`, `app/cache/provider_cache.py` |
| 4. Provider health repository / migrations | `app/repositories/`, `app/migrations/versions/0001_provider_schema.py` |
| 5. Docker non-root / TLS CA / UTC | `Dockerfile` — uid 10001, `ca-certificates`, `TZ=UTC` |

## 4. Two design decisions worth reviewing

**The registry gate reconciles config against the environment.** A provider
marked `ACTIVE` in `providers.yaml` whose credential is absent resolves to
`PENDING_CREDENTIAL` at startup, and the transport refuses to call it. The
inverse is also true and less obvious: supplying `ORS_API_KEY` does **not**
promote openrouteservice to callable, because the `status` field records a Lead
approval decision, not mere reachability.

**Provider health comes from observation, never from configuration.** An
`ACTIVE` provider with no row in `provider.health` reports `UNKNOWN` with
`last_checked_at: null`, not `UP`, and counts as degraded. Modules 03/05 route
requests on this answer, so "configured" must never be reported as "reachable".
Rows appear once a Phase 2 adapter writes `upsert_health` after a fetch.

**A blank environment variable counts as a missing credential.** `.env.example`
ships `ORS_API_KEY=` with no value, so an unfilled deployment presents an empty
string rather than an unset variable. This was caught against the live container
— the health endpoint was reporting the key as supplied.

## 5. Contract, database and configuration changes

**Database.** New `provider` schema with `providers`, `fetch_log`, `health`,
matching contract § 8. No raw-provider-body column exists: `store_raw_body:
false` is the retention default, so `fetch_log` keeps only a query hash, content
hash, status and timestamps.

**Configuration.** One new shared variable, `INTERNAL_SERVICE_TOKEN`.

**No API or JSON Schema change.** `packages/contracts/` is untouched. The
canonical record schemas land with their adapters in Phase 2+.

## 6. Open conflicts and proposals — need a decision

### 6.1 Schema name conflict (blocking nothing today, will bite later)

`infra/postgres/init/00-schemas.sql` creates a schema named **`external_data`**
and labels it "module 04". Both `00_API_AND_DATA_CONTRACTS.md` § 8 and the module
plan's ownership list say the schema is **`provider`**.

Two authoritative documents outvote one infra file, so the migration creates and
uses `provider`, and creates it itself rather than depending on the init script.
That keeps this service correct on a fresh database either way — but it leaves an
unused empty `external_data` schema behind.

**Proposed fix (needs Lead + infra review):** drop `external_data` from
`00-schemas.sql`, or repoint it to `provider`. Not done here because `infra/` is
shared surface and the init script only runs on a fresh volume, so changing it
has no effect on existing developer machines.

### 6.2 Internal auth scheme is a proposal, not a settled contract

Contract § 5 requires internal endpoints to use service authentication and
reject browser tokens, but names no mechanism. Phase 1 implements a shared
bearer secret compared in constant time, rejecting any request carrying a
`Cookie` header. **Modules 03 and 05 are the callers and must agree** before this
is treated as settled.

The service fails closed when the token is unset: an unset secret is a
misconfiguration, not a development convenience.

### 6.3 Cross-module questions still open

`docs/canonical-field-mapping.md` § 7 carries Q1–Q6 for คน 5/6 — chiefly who
derives `severity` and what the `DataQuality.score` formula is.
`docs/coverage-and-degraded-ux.md` carries U1–U3 for คน 1/2. Until Q2/Q3/Q5 are
answered, adapters will emit `severity` and `score` as `null` with a quality
flag rather than guessing.

## 7. Verification evidence

```text
command: uv run ruff check .
result:  All checks passed!

command: uv run mypy app
result:  Success: no issues found in 29 source files

command: uv run pytest
result:  111 passed, 0 failed, 0 skipped

command: docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app config
result:  valid

command: docker compose ... --profile core --profile app up -d --wait external-data
result:  smart-travel-external-data-1  Up (healthy)

command: docker compose ... run --rm external-data alembic upgrade head
result:  Running upgrade -> 0001_provider_schema

command: docker compose ... run --rm external-data alembic downgrade -1
result:  Running downgrade 0001_provider_schema -> (base); only alembic_version left

command: docker compose ... run --rm external-data alembic upgrade head
result:  4 tables in schema provider

command: docker compose ... exec external-data id
result:  uid=10001(app) gid=10001(app)

command: docker compose ... exec external-data date -u '+%Z'
result:  UTC
```

Live endpoint checks against the running container:

```text
GET /health/live                        200  {"status":"UP"}
GET /health/ready                       200  redis UP, postgres UP,
                                             internal_auth UP, provider_registry UP
GET /internal/v1/providers/health       401  AUTHENTICATION_REQUIRED (no token)
GET /internal/v1/providers/health       200  9 providers, all 9 degraded
                                             (none observed yet -> UNKNOWN)
GET /metrics                            200  Prometheus text
```

Provider health as reported by the running service:

```text
open_meteo_geocoding   ACTIVE                 UP               missing=[]
open_meteo_forecast    ACTIVE                 UP               missing=[]
openrouteservice       PENDING_CREDENTIAL     NOT_CONFIGURED   missing=['ORS_API_KEY']
amadeus                UNAVAILABLE            NOT_CONFIGURED   missing=['AMADEUS_CLIENT_ID','AMADEUS_CLIENT_SECRET']
gtfs_registry          PENDING_LEAD_APPROVAL  UNKNOWN          missing=[]
usgs_earthquake        ACTIVE                 UP               missing=[]
gdacs                  ACTIVE                 UP               missing=[]
nasa_eonet             ACTIVE                 UP               missing=[]
ors_pois               PENDING_CREDENTIAL     NOT_CONFIGURED   missing=['ORS_API_KEY']
```

### Two defects the tests caught

**Log redaction was destroying every timestamp.** The phone-number pattern
matched ISO-8601 dates — `2026-09-19` is ten digits joined by dashes — so every
log line read `"timestamp": "[PHONE]T08:09:49Z"`. Timestamps are now lifted out
before redaction and restored after. Regression tests in
`tests/unit/test_logging_redaction.py`; verified in the real container log.

**A 404 escaped the error envelope.** Starlette raises its own `HTTPException`
for an unmatched route, so registering only the FastAPI handler let unknown
paths return a bare `{"detail": ...}`. Both are registered now.

## 8. Safety, security and privacy

- [x] No credential value in the repository, a log, a trace or a fixture. The health endpoint returns credential *names* only.
- [x] Provider-specific messages never reach a consumer — `PROVIDER_AUTH` surfaces as "not configured in this deployment", never "invalid API key".
- [x] Redaction covers tokens, bearer headers, email, phone and exact coordinates (rounded to ~11 km in logs).
- [x] SSRF: base URLs come from config only, redirects disabled, off-host URLs refused.
- [x] Timeout budget, cancellation propagation, `Retry-After`, backoff+jitter, circuit breaker.
- [x] `SourceProvenance` rejects `observed_at == fetched_at`, so model output cannot pose as a measurement.
- [x] Unhandled errors log the exception *type* only — a message can carry a URL with query parameters.
- [ ] Idempotency keys — N/A for Phase 1 (no mutating endpoint yet).

## 9. Known limitations

1. **No provider is actually called for data.** Phases 2–7 are not started.
2. **Circuit breaker, concurrency limiter and quota tracker are in-process.** With more than one replica each has its own view. A shared breaker needs a Redis design that belongs with the distributed-cache work.
3. **No quota figure has been verified** against a live account. Every entry carries `verification_required: true`, and `/internal/v1/providers/health` reports `quota_verified: false` for all nine.
4. **`DataQuality.score` is always `null`** pending Q5.
5. **openrouteservice and Amadeus mappings are documentation-derived** and marked NOT VERIFIED — no credential means they have never been called.
6. **Retry-After HTTP-date form is not parsed**, only delta-seconds. None of the active providers uses the date form; a wrong parse would be worse than the default backoff.
7. **No canary test job yet** — the `canary` pytest marker is registered but unused until adapters exist.

## 10. Handoff

**Team Lead** — `services/external-data/docs/lead-approval-checklist.md`:
approve providers (A1–A5), assign credential owners (B1–B3), verify quotas
(C1–C4), confirm licence/attribution (D1–D3). Plus the schema-name conflict in
§ 6.1 above. **Phase 4 and 5 cannot start until B1/B2/A5 are resolved.**

**คน 5 (data-integration)** — Q1–Q6 in `docs/canonical-field-mapping.md` § 7,
especially who derives `severity` and the `score` formula.

**คน 6 (risk-knowledge)** — Q2, Q3, Q6: which feature fields the risk model
needs so adapters do not drop them.

**คน 1 / คน 2 (web, public API)** — `docs/coverage-and-degraded-ux.md`: four of
seven user-visible capabilities are unavailable and need an honest disabled
state. U1–U3 are open.

**คน 3 / คน 5 (internal API callers)** — agree the internal auth scheme in § 6.2.

**Next owner of this module** — Phases 2 and 3 are unblocked and can start now:
geocoding, weather and all three disaster sources are keyless, reachable, and
have real fixtures with the parsing traps already documented.

## 11. How to run

```bash
cp .env.example .env
# fill POSTGRES_PASSWORD, KEYCLOAK_ADMIN_PASSWORD, INTERNAL_SERVICE_TOKEN

docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app up -d --wait
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app \
  run --rm external-data alembic upgrade head

curl -s localhost:8002/health/ready
curl -s -H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN" \
  localhost:8002/internal/v1/providers/health
```

Module checks:

```bash
cd services/external-data
uv sync --locked
uv run ruff check .
uv run mypy app
uv run pytest
```

## 12. Rollback

- **Code:** revert `9cbcc43` and `479c28d`. `7c46d7b` is documentation and fixtures only, safe to keep.
- **Compose:** reverting `9cbcc43` removes the service from the `app` profile; the `core` profile is untouched.
- **Database:** `alembic downgrade base` drops all three tables, tested. It leaves the empty `provider` schema and its `alembic_version` table, which is intentional.
- **Provider disable path:** set a provider's `status` to `UNAVAILABLE` in `providers.yaml` and restart. No code change needed.
