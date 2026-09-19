# [M02] Public contract v1 and API service scaffold — completion report

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 02 — API and backend |
| Issue/PR | (to be filled when the PRs are opened) |
| Branch | `contract/02-public-travel-schema` (phase 0), `feat/02-api-scaffold` (phase 1, branched from it) |
| Base/final commit SHA | base `a814558`, final `d5c2d37` |
| Date/time/timezone | 2026-09-19, Asia/Bangkok |
| Reviewers | Lead + owners of modules 01, 03, 08 for the contract; lead for the shared surfaces |
| Contract version | `1.0.0` |
| Docker image digest/tag | `sta-api@sha256:576fcfbe003e0ae65fd383ddce8f23b58901b4af288e1d8290a01067a46e1cdd` (local build, 355 MB) |
| Related model/policy/prompt/collection version | N/A — none of those exist yet |

## 2. Executive summary

Phases 0 and 1 of the module 02 plan are complete and verified.

Phase 0 freezes the shared contract: 31 canonical entities as JSON Schema, a public OpenAPI 3.1
document covering all 23 operations from §4 of the contract document, generated TypeScript and
Python clients, and a CI gate that regenerates and fails if the committed output drifts from its
source. The other seven modules can now generate clients and write consumer tests against one
definition instead of seven near-copies.

Phase 1 builds the service scaffold: app factory, validated settings, the middleware chain,
liveness/readiness/metrics, the error envelope, the database engine and Alembic migrations for the
`identity` and `travel` schemas, and a non-root multi-stage image wired into compose. A fresh
database migrates to head, the container reports healthy, and the logs carry no token, query string
or coordinate.

Two things are deliberately absent. There is **no authentication** — that is phase 2, and a stub
that returned a user would be indistinguishable from working auth until someone deployed it. And
there are **no `/api/v1/**` endpoints** — those are phases 3 to 6.

The consequence to know about: **readiness is red on a fresh stack**, because it requires the OIDC
discovery document and the Keycloak realm does not exist until phase 2. That is the check working,
not failing. Liveness is green and the container is healthy.

Ready to merge as two PRs in sequence. Not ready to release: the service has no user-facing
capability yet.

## 3. Original responsibility and acceptance criteria

From `02_API_BACKEND_IMPLEMENTATION.md`. Only phases 0 and 1 were in scope for this pass.

### Phase 0 — Freeze public contract

- [x] Read the eight modules' inputs/outputs and produce a field ownership matrix — `docs/api/field-ownership-matrix.md`
- [x] Public OpenAPI v1 and common JSON Schema built from the contract document — `packages/contracts/openapi/`, `packages/contracts/jsonschema/common/`
- [x] Sanitized success/error/SSE examples — inline in the OpenAPI plus `packages/contracts/examples/`
- [x] Lint, breaking-change posture and generators wired — redocly + ajv + openapi-typescript + datamodel-code-generator, gated by `.github/workflows/contracts.yml`
- [ ] Review from owners 1, 3 and 8 before merge — **pending**, this is a review step, not a code step

**Exit criterion — "TypeScript and Python generate successfully and consumer contract tests can
start":** met. Both generate; 59 contract tests run against the generated output; a TypeScript
consumer file compiles against the generated types.

### Phase 1 — Service scaffold

- [x] FastAPI app factory, settings validation, lifespan
- [x] Middleware order: request size and trusted proxy → request id and trace → auth context → rate limit → logging and error mapping
  — with two caveats, both deliberate: the **auth context** slot is left open for phase 2, and **rate limiting** is phase 7. Redis is already required and probed so that phase 7 is a drop-in.
- [x] `/health/live`, `/health/ready`, `/metrics`, with readiness bounded per check and overall
- [x] SQLAlchemy session and unit of work, Alembic per schema
- [x] Docker non-root multi-stage, compose health
- [x] Error handler mapping every exception onto the stable envelope

**Exit criterion — "fresh DB migrates, container healthy, logs contain no body or token":** met.
Evidence in §10.

### Deferred, with reason

| Item | Phase | Why not now |
| --- | --- | --- |
| OIDC/JWT verification | 2 | Needs the Keycloak realm; a stub would be worse than nothing |
| `/api/v1/**` endpoints | 3–6 | Depend on auth and ownership |
| Rate limiting, circuit breaking | 7 | Depend on endpoints existing |
| Internal service OpenAPI documents | their owners | `packages/contracts/openapi/` holds the public one; the six internal ones belong to modules 03–08 |

## 4. What was implemented

### Features

| Feature | Behaviour now | Entry point | Status |
| --- | --- | --- | --- |
| Public contract v1 | 31 entities, 23 operations, generated TS + Python clients | `packages/contracts/openapi/public-api.yaml` | Complete |
| Contract CI gate | Lint, schema compile, example validation, regenerate-and-diff, 59 tests | `.github/workflows/contracts.yml` | Complete |
| App factory and settings | Validated at startup; misconfiguration stops the process | `app/main.py:create_app`, `app/settings.py` | Complete |
| Middleware chain | Security headers, size limit, correlation, CORS, access log | `app/middleware/` | Complete |
| Error envelope | Every failure becomes the contract error shape | `app/errors/handlers.py` | Complete |
| Liveness | Touches nothing external | `GET /health/live` | Complete |
| Readiness | PostgreSQL, Redis, OIDC required; agent optional | `GET /health/ready` | Complete |
| Metrics | Route-template labels, dependency gauges | `GET /metrics` | Complete |
| Structured logging | JSON with redaction in the pipeline | `app/observability/logging.py` | Complete |
| Persistence | Async engine, session scope, migrations | `app/db/`, `migrations/` | Complete |
| Container | Multi-stage, non-root uid 10001, healthcheck | `services/api/Dockerfile` | Complete |
| Authentication | — | — | **Not implemented (phase 2)** |

### Important flows

Request handling:

```text
socket
 -> SecurityHeadersMiddleware   headers applied to every response, including early rejections
 -> RequestGuardMiddleware      size limit before the body is read; client address resolved once
 -> RequestContextMiddleware    request_id + correlation_id minted, bound to the log context
 -> CORSMiddleware              exact-origin allowlist, identity headers exposed to the browser
 -> AccessLogMiddleware         one line + one metric observation, route template only
 -> router
 -> exception handlers          any failure -> stable envelope, detail to the log not the client
```

Readiness:

```text
GET /health/ready
 -> run every check concurrently, each with its own timeout
 -> enforce a whole-probe budget; a check that outruns it is reported down, not omitted
 -> ready = every *required* check is up
 -> 200 ready / 503 not_ready, plus dependency_up and readiness_state gauges
```

### What is explicitly not implemented

- Token verification, scopes, ownership checks
- Any `/api/v1/**` route
- Rate limiting, idempotency storage, SSE
- Emergency profile encryption (the schema exists; the envelope encryption is phase 3)

## 5. Actual architecture and code design

### Folder/file map

| Path | Purpose | Owner/consumer |
| --- | --- | --- |
| `packages/contracts/jsonschema/common/` | 31 canonical entities | 02 maintains; everyone consumes |
| `packages/contracts/openapi/public-api.yaml` | Public API contract | 02; consumed by 01 |
| `packages/contracts/generated/` | TS + Python clients, bundled spec | Generated; never edited |
| `packages/contracts/examples/` | Structural and real-sanitized fixtures | Tests only |
| `packages/contracts/consumer-checks/` | TypeScript that must keep compiling | 01's early warning |
| `tests/contract/` | 59 producer/consumer tests | Shared |
| `services/api/app/` | The service | 02 |
| `services/api/migrations/` | Alembic for `identity` and `travel` | 02 |
| `docs/api/field-ownership-matrix.md` | Who may write which field | Everyone |

### Decisions and trade-offs

**Entities live in JSON Schema; the OpenAPI document references them.**
*Alternative:* define everything inline in OpenAPI. *Reason:* the same entities serve the public
API, six internal APIs and the Python services. *Consequence:* bundling needs a normalisation step
(below). *ADR:* not raised; this follows §9 of the contract document.

**The schemas carry no `$id`.**
*Alternative:* canonical `$id` URIs. *Reason:* with `$id`, relative `$ref`s re-root at an
unfetchable URL and redocly, ajv, openapi-typescript and datamodel-code-generator all fail to
resolve them. *Consequence:* refs resolve by file name, so files cannot be moved without updating
their referrers.

**`scripts/bundle.mjs` normalises redocly's output.**
Bundling JSON Schema files pulls `$schema` and `$defs` into `components.schemas` and registers a
duplicate component named after the source file (`consent-record.schema` beside `ConsentRecord`).
The dot makes datamodel-code-generator read the name as a module path and refuse to emit a single
file, and it leaves consumers with two names for one type. The script folds each body onto the
canonical name and **exits non-zero** if one cannot be resolved, rather than dropping it.

**`Uuid` is `format: uuid` with no pattern beside it.**
Pydantic cannot apply a string pattern to a UUID-typed field and raises at import. The format alone
gives a real UUID type whose canonical serialisation is already lowercase.

**Alembic's version table lives in a third schema, `api`.**
*Alternative:* `public`, or inside `identity`. *Reason:* `public` is shared with six other services,
which would each read the others' revisions as unknown heads; inside `identity` it would make that
schema undroppable, so revision 0001 could never be downgraded. *Consequence:* the bootstrap
script's `api` schema and the contract document's `identity`/`travel` are reconciled rather than
duplicated.

**uvicorn starts through `--factory`.**
A module-level `app = create_app()` validates the environment on any import of `app.main`, turning
a configuration mistake into an import-time stack trace and breaking any test that wanted only the
factory.

**Hand-written response envelope rather than the generated models.**
*Reason:* handlers construct these, and a hand-written model can carry this service's own
invariants. *Consequence:* drift risk, paid for by `tests/test_contract_parity.py`, which fails in
this service if the contract moves.

### Accepted technical debt

- `app/schemas/envelope.py` duplicates shapes that also exist in the generated models. Held in check
  by the parity tests.
- The image is 355 MB. Acceptable for now; `psycopg[binary]` plus the OpenTelemetry stack accounts
  for most of it, and trimming it is not worth a PR before the endpoints exist.

## 6. API, contract and event changes

| Producer | Method/path | Request schema | Response schema | Consumer | Compatibility |
| --- | --- | --- | --- | --- | --- |
| 02 | 23 operations under `/api/v1` | see `public-api.yaml` | `{data, meta}` / `{error, meta}` | 01 | New — contract v1.0.0 baseline |
| 02 | `GET /health/live` | — | `HealthLiveResponse` | orchestrator | Implemented |
| 02 | `GET /health/ready` | — | `HealthReadyResponse` | orchestrator, runbook | Implemented |
| 02 | `GET /metrics` | — | Prometheus text | Prometheus | Implemented |

Only the three health/metrics endpoints are implemented so far. The other 23 are contract only.

- **Generated client command:** `cd packages/contracts && npm run generate`
- **Generated client result:** `public-api.bundled.yaml` (4.1k lines), `public-api.d.ts` (2,786 lines), `public_api.py` (1,507 lines)
- **Contract lint result:** `Woohoo! Your API description is valid.` with 2 documented exceptions in `.redocly.lint-ignore.yaml` (the health endpoints have no 4xx, by design)
- **Breaking change check:** not wired yet. See §15.
- **Sanitized examples:** `packages/contracts/examples/`

### Conventions consumers must know

| Rule | Why |
| --- | --- |
| Responses are open, request bodies are closed (`additionalProperties: false`) | An added optional field stays backward compatible; an unrecognised field on input is a client bug or an attack |
| A value the provider did not supply is `null` and the field is still **required** | Zero rain and unknown rain are different facts |
| Coordinates are `[longitude, latitude]`, bounded per element | A swapped pair fails validation instead of relocating a trip |
| A resource owned by someone else returns 404, not 403 | 403 would confirm the id exists |

## 7. Database, cache and storage changes

### Migrations

| Revision | Schema/table/index | Upgrade | Downgrade | Data impact |
| --- | --- | --- | --- | --- |
| `0001` | schemas `identity`, `travel` | `CREATE SCHEMA IF NOT EXISTS` + grant | `DROP SCHEMA IF EXISTS` without CASCADE | None — creates two empty schemas |

- **Empty DB → head:** pass (`tests/test_migrations.py::test_empty_database_reaches_head`, and in-container against the compose stack)
- **Previous main → head:** `main` has no migrations, so this is the same as empty → head
- **Repeated upgrade:** pass — what happens when a container restarts mid-deploy
- **Downgrade → base → head:** pass
- **Refuses to drop a schema holding data:** pass — no CASCADE, so one downgrade too many fails loudly instead of deleting a user's trips
- **Restart persistence:** the schemas survived `docker compose up` cycles against the same volume
- **Backup/restore:** not exercised; no user data exists yet
- **Retention/cleanup:** phase 3
- **Encryption/access control:** the migration grants the migrating role usage on both schemas. Per-service database roles are an infra task.

### Redis/Qdrant/artifacts

Redis is connected and probed but not yet written to. The key prefix is derived as
`sta:{env}` in `Settings.redis_namespace` so every service derives it the same way.

## 8. External providers and real data

No provider is called by this module. The API proxies geocoding through module 04 from phase 4
onward; it never calls a provider directly and never accepts a provider URL from a request.

- **Runtime/demo contains no mock or hard-coded current data:** [x] — CI greps `services/api/app` for
  mock switches, and a contract test asserts no runtime code reads the fixture folder
- **Test fixture provenance:** one real-sanitized fixture, captured from Open-Meteo geocoding on
  2026-09-19T08:11:38Z, with source URL, licence, attribution, upstream content hash and a redaction
  note. Everything else is labelled structural and synthetic.
- **Unavailable capability behaviour:** readiness reports the dependency as down and names it; it is
  never treated as healthy by omission.

## 9. Configuration and Docker

### Environment variables added

| Variable | Required | Secret | Default | Used by | If missing |
| --- | --- | --- | --- | --- | --- |
| `OIDC_AUDIENCE` | no | no | `smart-travel-api` | api | Default used |
| `API_CORS_ALLOWED_ORIGINS` | no | no | `http://localhost:3000` | api | Default used; `*` is rejected at startup |
| `API_TRUSTED_PROXY_HOPS` | no | no | `0` | api | Forwarding headers ignored |
| `API_MAX_REQUEST_BODY_BYTES` | no | no | `262144` | api | Default used |
| `API_READINESS_TIMEOUT_SECONDS` | no | no | `3` | api | Default used |
| `API_DB_POOL_SIZE` / `API_DB_MAX_OVERFLOW` | no | no | `10` / `5` | api | Default used |
| `API_DB_CONNECT_TIMEOUT_SECONDS` | no | no | `5` | api | Default used |
| `API_DB_STATEMENT_TIMEOUT_MS` | no | no | `10000` | api | Default used |
| `API_REDIS_TIMEOUT_SECONDS` | no | no | `2` | api | Default used |
| `API_OIDC_TIMEOUT_SECONDS` | no | no | `3` | api | Default used |
| `API_DOWNSTREAM_*_TIMEOUT_SECONDS` | no | no | `2` / `10` | api | Default used |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | no | unset | all | Spans created and dropped |

`POSTGRES_USER` and `POSTGRES_PASSWORD` were already required by the stack and have no default —
the process refuses to start without them.

### Run commands

```bash
cp .env.example .env            # then set POSTGRES_PASSWORD and KEYCLOAK_ADMIN_PASSWORD

docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app up -d --wait api

curl -fsS http://localhost:8000/health/live
curl -sS  http://localhost:8000/health/ready
curl -fsS http://localhost:8000/metrics | head
```

- **Container user:** `app`, uid/gid 10001, verified by running the image
- **Ports:** none in `compose.yaml`; `8000` published by `compose.dev.yaml` only
- **Volumes:** dev only, read-only source mounts for reload
- **Health:** container healthcheck probes `/health/live` alone; readiness is probed separately
- **Image:** 355 MB, `sha256:576fcfbe003e…`; contains no `.env`, `tests`, `.git` or `uv.lock`

## 10. Tests and verification

All commands run from the repository root on 2026-09-19.

| Test type | Command | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Compose validate | `docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app config` | 1 | 0 | 0 | `compose OK` |
| Contract lint | `cd packages/contracts && npm run lint` | 1 | 0 | 2 ignored | 2 documented exceptions, health endpoints have no 4xx |
| Schema compile | `npm run validate:schemas` | 31 | 0 | 0 | `31 schemas compiled.` |
| Example validation | `npm run validate:examples` | 6 | 0 | 0 | `6 examples validated.` |
| TS consumer typecheck | `npm run typecheck` | 1 | 0 | 0 | `tsc OK` |
| Generated output up to date | `./scripts/check-generated-clean.sh` | 1 | 0 | 0 | `Generated contract output matches the source.` |
| Contract tests | `uv run --project tests/contract pytest tests/contract` | 59 | 0 | 0 | |
| API lint + format | `cd services/api && uv run ruff check . && uv run ruff format --check .` | — | 0 | 0 | `All checks passed!`, `38 files already formatted` |
| API types | `uv run mypy app` | 27 files | 0 | 0 | `Success: no issues found in 27 source files` |
| API unit | `uv run pytest -m "not integration"` | 99 | 0 | 5 deselected | |
| API migrations | `uv run pytest -m integration` | 5 | 0 | 99 deselected | Real `postgis/postgis:16-3.4` via Testcontainers |
| E2E | — | — | — | — | N/A — no endpoints and no web app yet |

The 5 deselected in the unit run are the migration tests; the 99 deselected in the integration run
are the unit tests. Nothing is skipped for an unexplained reason.

### Scenarios verified

- **Success:** liveness 200, readiness 200 when required checks pass, metrics served
- **Invalid input:** missing field → `REQUIRED`; wrong type → path reported, value not echoed; unknown route and wrong method → same envelope
- **Unauthorized:** 401 carries `WWW-Authenticate: Bearer` (raised directly; real token verification is phase 2)
- **Timeout:** a hung dependency does not hang the probe; an over-budget check is reported down
- **Partial:** an optional dependency down does not make the service unready
- **Oversized body:** 413 before the handler runs — asserted by a flag the handler would have set
- **Leak checks:** a `RuntimeError` carrying a DSN and a password produces a 500 with none of it in the body; a readiness failure carrying a DSN reports only the exception type
- **Redaction:** tokens, emails, phone numbers, medical fields and coordinates removed at any depth, including nested inside a trip object; correlation ids survive verbatim

### Live evidence

```text
$ curl -fsS -D- http://localhost:8000/health/live
x-request-id: 6d1c237c-7610-4fe6-bf07-ec20e3c92d5b
x-correlation-id: 6d1c237c-7610-4fe6-bf07-ec20e3c92d5b
x-contract-version: 1.0.0
x-content-type-options: nosniff
x-frame-options: DENY
referrer-policy: no-referrer
permissions-policy: geolocation=(), camera=(), microphone=(), payment=()
cache-control: private, no-store

{"status":"alive","service":"api","version":"0.1.0"}

$ curl -sS http://localhost:8000/health/ready        # 503
postgres up (4.17 ms) | redis up (1.65 ms) | oidc down "unavailable (HTTPStatusError)" | agent down "did not answer within 2s"

$ curl -sS http://localhost:8000/metrics | grep api_dependency_up
api_dependency_up{dependency="postgres",required="true"} 1.0
api_dependency_up{dependency="redis",required="true"} 1.0
api_dependency_up{dependency="oidc",required="true"} 0.0
api_dependency_up{dependency="agent",required="false"} 0.0
api_readiness_state 0.0
```

A request sent with a bearer token and coordinates in the query string
(`GET /api/v1/x?lat=…&lon=…`) produced this log line — no token, no query string, no coordinates:

```json
{"event_type": "http_request", "http_method": "GET", "route": "<unmatched>", "status": 404,
 "duration_ms": 0.68, "client": "172.18.0.1", "request_id": "ed18a174-…",
 "correlation_id": "ed18a174-…", "trace_id": "8f8a821e…", "service": "api"}
```

## 11. UI evidence

N/A — this module has no UI.

## 12. Safety, security and privacy review

- [x] Official warning/closure priority preserved — N/A at this layer; the contract encodes it (`RouteCandidate.exposure.closed`, `DecisionResult.validation.locked_action`)
- [x] LLM/provider/RAG data treated as untrusted — marked as such in every schema that carries provider text
- [x] No secret, PII, or exact location in code, log, trace or fixture — enforced by the redaction processor and asserted by tests; CI greps the contract sources for secret-shaped strings
- [x] Consent/auth/ownership enforced — **not yet**; phases 2 and 3. Nothing is exposed that would need it.
- [x] Timeout/retry/cancel bounded — every dependency check and every outbound client has an explicit timeout; idempotency is phase 5
- [x] Source/freshness/quality/version retained — required by the contract, asserted by tests
- [x] Fallback/degraded behaviour does not invent data — readiness names what is down; nothing substitutes a default
- [ ] Dependency/image/secret scans — **not wired**. See §15.

### Findings during the work

| Finding | Resolution |
| --- | --- |
| The redaction rule for long digit runs was mangling correlation ids whose first UUID group is all digits | Added an allowlist of system-generated identifiers that skip text scrubbing, checked *after* the deny list. Regression test added. |
| httpx logs every outbound URL at INFO, which will contain user-typed place names once geocoding is proxied | Its logger is set to WARNING in `configure_logging` |
| `/health/ready` detail could have carried a DSN from a driver exception | Only the exception type is reported; a test asserts a password cannot reach the response |

## 13. Problems encountered and resolutions

| Problem | Root cause | Evidence | Resolution | Remaining risk |
| --- | --- | --- | --- | --- |
| `datamodel-codegen` refused to emit a single file: `Modular references require an output directory` | Redocly's bundle contained components named after their source file (`trip.schema`); the dot reads as a module path | 19 such components in the bundle | `scripts/bundle.mjs` folds each onto its canonical name and fails loudly if one cannot be resolved | Low — a new entity without an explicit `components.schemas` entry fails the build rather than passing silently |
| Generated Pydantic models raised at import: `Unable to apply constraint 'pattern' ... schema of type 'uuid'` | `Uuid` had both `format: uuid` and a redundant pattern | Traceback from `RecommendationResponse.model_validate` | Dropped the pattern; the UUID type already serialises lowercase canonical | None |
| Redocly could not resolve `$ref`s during example validation | `$id` on each schema re-rooted relative refs at an unfetchable URL | `can't resolve reference primitives.schema.json#/$defs/Uuid from id https://…` | Removed `$id` from all 31 schemas | Files cannot be moved without updating referrers |
| `pydantic-settings` failed to start the container: `error parsing value for field "cors_allowed_origins"` | It JSON-decodes complex types from the environment before any validator runs | Container log from the first compose run | Annotated the field with `NoDecode`; the comma-separated form is parsed by the existing validator | None — a test covers the comma-separated form |
| Alembic downgrade could not drop `identity` | The version table lived inside the schema the migration drops | `DependentObjectsStillExist: cannot drop schema identity` | Moved bookkeeping to the `api` schema | None |
| `uv run --project tests/contract pytest` collected `services/api/tests` from the repository root | pytest resolves `testpaths` against the invocation directory | `ModuleNotFoundError: No module named 'httpx'` during collection | The wrapper passes the path explicitly | None |
| Settings could not be constructed in tests | Field aliases without `populate_by_name` | `Field required [type=missing]` for `POSTGRES_USER` | Enabled `populate_by_name` | None |
| Heredocs through the tooling mangled backslashes in JSON regex patterns | Escape handling in the shell transport | `Invalid \escape` from `json.load` | Schema files written with the file-writing tool rather than heredocs | None |

## 14. Performance and operational behaviour

No load test was run: there is no endpoint worth loading yet. The budgets in
`09_INTEGRATION_ACCEPTANCE_RUNBOOK.md` §12 apply from phase 5 onward.

| Metric | Target | Actual | Condition | Pass |
| --- | --- | --- | --- | --- |
| Readiness probe latency | must answer inside its budget | ~2.0 s, dominated by the agent probe timing out at 2 s | agent absent | Yes — the budget is 3 s |
| `postgres` check | — | 4.17 ms | local compose | — |
| `redis` check | — | 1.65 ms | local compose | — |

Metrics added: `api_http_requests_total`, `api_http_request_duration_seconds`,
`api_http_errors_total`, `api_dependency_check_duration_seconds`, `api_dependency_up`,
`api_readiness_state`, `api_request_body_rejected_total`. Latency buckets have edges at 0.3 s and
0.5 s so the runbook's p95 targets can actually be measured.

**Incident disable path:** there is no feature flag yet because there is no feature. Rolling back
is an image tag change; the single migration is additive and safe to leave in place.

## 15. Known limitations and technical debt

| Limitation | Impact | Workaround | Owner | Priority | Follow-up |
| --- | --- | --- | --- | --- | --- |
| No authentication | No endpoint can be protected | None needed — nothing is exposed | 02 | Next | Phase 2 |
| Readiness red until the Keycloak realm exists | The api container never reports ready on a fresh stack | Liveness is green and the container is healthy | 02 | Next | Phase 2 |
| No breaking-change detection on the contract | A breaking change could merge without a version bump | Review, plus the consumer checks | 02 + lead | High | Wire `oasdiff` against `origin/main` in `contracts.yml` |
| No container vulnerability scan or SBOM | Required by the delivery rules §12 | — | lead | High | Add Trivy/Grype to CI |
| Generated Pydantic models do not enforce coordinate ranges | A swapped or out-of-range coordinate would pass model validation | The API validates coordinates at the boundary from phase 4; the JSON Schema does enforce it | 02 | Medium | Pinned by a test that fails if a generator upgrade fixes it |
| `infra/postgres/init/00-schemas.sql` does not create `identity` or `travel` | None in practice — the migration creates them | — | lead | Low | Infra PR |
| Image is 355 MB | Slower pulls | — | 02 | Low | Revisit after the endpoints exist |
| `packages/contracts` uses npm while the web app will use pnpm | Two lockfile formats in one repository | — | 01 + 02 | Low | Fold into the pnpm workspace when `apps/web` lands |

## 16. Handoff to other members

| Recipient | What is ready | What they must do | Contract/config | Blocking? |
| --- | --- | --- | --- | --- |
| **01 — web** | Generated TypeScript types at `packages/contracts/generated/typescript/public-api.d.ts`; `consumer-checks/public-api.consumer.ts` shows the import shape | Import the types instead of hand-writing request/response shapes. Review the contract for anything the six screens need that is missing. | `X-Request-ID`, `X-Correlation-ID`, `X-Contract-Version` are exposed via CORS; add the web origin to `API_CORS_ALLOWED_ORIGINS` | Contract review is blocking for you |
| **03 — agent** | `TravelRequest`, `RunRef`, `RunState`, the SSE payload schemas and the nine `RunStage` values | Implement `/internal/v1/runs` to accept `TravelRequest` and report progress with those stages. Add `openapi/internal-agent.yaml` on your own contract branch. | Progress copy is an i18n **key**, never a translated sentence | Yes — phase 5 depends on it |
| **04 — external-data** | `LocationRef`, `SourceProvenance`, `DataQuality`, and one real-sanitized Open-Meteo fixture showing the mapping | Produce `LocationRef` from the geocoding provider. `provider` is a lowercase key matching `SourceProvenance.provider`. | `observed_at` is `null` when the provider publishes none — never backfilled from `fetched_at` | Yes — phase 4 depends on it |
| **05 — data-integration** | `IntegratedTravelContext`, `DataQuality`, `weather`/`transport`/`disaster` entities | You own `DataQuality.formula_version`. Snapshots are immutable; a refresh is a new id with `supersedes_snapshot_id`. | — | No |
| **06 — risk-knowledge** | `RiskAssessment`, `RetrievedEvidence`, `RouteCandidate` | `reason_codes` is a closed vocabulary — propose additions on a contract branch. You own `exposure.closed`. | — | No |
| **07 — decision-engine** | `DecisionResult` including `validation.locked_action` | The API rejects a result whose `locked_action` is false rather than displaying it | — | No |
| **08 — recommendation** | `RecommendationResponse`, `OfficialContact`, `FeedbackEvent`, `AlertSubscription` | Review `recommendation-response.schema.json` — it is your entity and it was drafted here. Your `contract/08-…` branch should build on it rather than forking it. | The API revalidates your response against the schema before the browser sees it | **Review is blocking** |
| **Lead** | Shared surfaces changed: `compose.yaml`, `compose.dev.yaml`, `.env.example`, `Makefile`, `.github/workflows/` | Review. All changes are additive. | — | Yes |

## 17. Commit and PR inventory

```text
25eda5c contract(contracts): add public API v1 and canonical entity schemas
3256c01 build(contracts): add contract lint, validation and client generation
78c4fc8 test(contracts): add contract fixtures and producer/consumer tests
73d95e8 ci(contracts): gate pull requests on the contract pipeline
44a5ef6 feat(api): add FastAPI scaffold, settings, middleware and error envelope
4b0c1d3 feat(api): add liveness, readiness and metrics endpoints
bb773d4 feat(api): add database engine and migrations for identity and travel
21f79b3 build(api): package the service as a non-root image and wire it into compose
1b077ba ci(api): gate pull requests on lint, types, tests and image checks
d5c2d37 fix(contracts): scope the contract test run to its own directory
```

- **PR review comments resolved:** none yet — not opened
- **Required checks status:** all green locally; the two new workflows have not run on a remote yet
- **Rebased on main SHA:** `a814558` (no divergence)
- **Proposed squash titles:**
  - `[M02] Freeze public API contract v1 and wire client generation` (commits 1–4, 10)
  - `[M02] Add public API service scaffold with health, persistence and Docker` (commits 5–9)

## 18. Rollback and recovery

1. **Feature flag / provider disable:** N/A — no feature and no provider.
2. **Application rollback:** revert the image tag. There is no previous version; removing the `api`
   service from the `app` profile stops it without affecting anything else.
3. **Migration:** `alembic downgrade base` drops both schemas, and only while they are empty. Once
   phase 3 adds tables, this becomes a forward-fix.
4. **Model/policy/prompt/knowledge:** N/A.
5. **Data/cache cleanup:** none needed. **Do not** run `docker compose down -v` — it deletes the
   PostgreSQL and Qdrant volumes.
6. **Verification after rollback:** `docker compose ps`, then `curl /health/live` on the remaining
   services.

## 19. Final declaration

- [x] The work in scope (phases 0 and 1) is complete, with evidence
- [x] No required work is hidden — phases 2 to 8 are listed as not started
- [x] Documentation, env, contracts and migrations updated
- [ ] Downstream owners handed off — written here, **not yet communicated**
- [x] Ready to merge, subject to the reviews named in §16
- [ ] Ready to release — no. The service has no user-facing capability, and authentication does not
      exist yet.

Prepared by: module 02 (with Claude Opus 5)
Reviewed by: —
Date: 2026-09-19
