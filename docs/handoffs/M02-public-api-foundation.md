# [M02] Public API foundation — completion report

Covers phases 0 to 3 of `IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`: the frozen
contract, the service scaffold, OIDC authentication, and identity with consent, encrypted emergency
profiles and the privacy machinery.

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 02 — API and backend |
| Issue/PR | not yet opened; two PRs planned, see §17 |
| Branch | `contract/02-public-travel-schema` (phase 0) and `feat/02-api-scaffold` (phases 1–3, stacked on it) |
| Base/final commit SHA | rebased onto `origin/main` `29a1798`; final `c781226` |
| Date/time/timezone | 2026-09-20, Asia/Bangkok |
| Reviewers | Lead; owners 01, 03, 08 for the contract; lead for the shared surfaces |
| Contract version | `1.0.0` |
| Docker image digest/tag | `sha256:b47f9548de09b5fee3cf83921ed7a99b9ac17c652f3d3ed513e6a83f40d82acf` (local build, 379 MB, runs as `app`) |
| Related model/policy/prompt/collection version | N/A — none exist yet |

## 2. Executive summary

Four phases are complete and verified inside Docker against a real PostgreSQL and a real Keycloak.

**Phase 0** freezes the shared contract: 31 canonical entities as JSON Schema, a public OpenAPI 3.1
document covering all 23 operations from §4 of the contract document, and generated TypeScript and
Python clients produced from that one source. CI regenerates and fails if the committed output
drifts. The other seven modules can now build against one definition instead of seven near-copies.

**Phase 1** is the service scaffold: app factory, validated settings, the middleware chain,
liveness/readiness/metrics, one error envelope for every failure, the database engine with Alembic
per schema, and a non-root multi-stage image wired into compose.

**Phase 2** is authentication: OIDC token verification with a rotation-aware JWKS cache, a Keycloak
realm imported from a committed file that contains no credential, the OIDC subject mapped onto an
internal user, scope and role dependencies, and ownership enforced at the repository query.

**Phase 3** is identity and privacy: `PATCH /me`, versioned consent with server-capped expiry,
an emergency profile sealed with envelope encryption, an audit trail that records actions but never
their content, and an export/deletion worker that reports honestly what it could not reach.

Three endpoints of the 23 are implemented. That is the point of the phasing: the ones that exist are
the ones that prove the whole chain works, and phases 4 to 7 add the rest on top of the same
authentication, ownership and error handling.

Ready to merge as two PRs in sequence. Not ready to release: there is no trip, no assessment and no
rate limiting yet.

## 3. Original responsibility and acceptance criteria

### Phase 0 — Freeze public contract

- [x] Field ownership matrix — `docs/api/field-ownership-matrix.md`
- [x] Public OpenAPI v1 and common JSON Schema from the contract document
- [x] Sanitized success/error/SSE examples — inline plus `packages/contracts/examples/`
- [x] Lint, breaking-change posture and generators wired — gated by `.github/workflows/contracts.yml`
- [ ] Review from owners 1, 3 and 8 — **pending**; a review step, not a code step

**Exit — "TypeScript and Python generate and consumer contract tests can start":** met. 59 contract
tests run against the generated output, plus a TypeScript consumer file that must keep compiling.

### Phase 1 — Service scaffold

- [x] App factory, settings validation, lifespan
- [x] Middleware order: size/proxy → request id/trace → auth context → rate limit → logging/errors
      — with two documented departures: auth is a **dependency**, not a middleware layer (see §5),
      and rate limiting is phase 7. Redis is already required and probed so phase 7 drops in.
- [x] `/health/live`, `/health/ready`, `/metrics`, bounded per check and overall
- [x] SQLAlchemy session and unit of work, Alembic per schema
- [x] Docker non-root multi-stage, compose health
- [x] Error handler mapping every exception onto the stable envelope

**Exit — "fresh DB migrates, container healthy, logs contain no body or token":** met. §10.

### Phase 2 — OIDC and authorization

- [x] Keycloak realm/client/roles as an import file with no real secret — `infra/keycloak/`
- [x] Verify JWT/JWKS and map `sub` to a user profile
- [x] Role/scope dependencies and object ownership
- [x] Auth tests: expired, wrong issuer/audience, unknown kid with refresh, missing scope,
      another user's resource — plus `alg: none` and the HMAC substitution
- [x] CORS allowlist of exact origins; credentials over approved local origins only

**Exit — "protected endpoints pass with a real Keycloak token and negative tests":** met. Seven
tests run against the imported realm, including a real token without the `travel` scope getting 403
and a valid token from the `master` realm getting 401.

### Phase 3 — User, consent and emergency profile

- [x] Migrations, tables, indexes — revision `0003`
- [x] `/me` and consent grant/revoke with policy version
- [x] Emergency profile encrypt/decrypt, and redaction of every field from logs
- [x] Audit of create/update/delete without recording sensitive content
- [x] Retention/export/delete skeleton jobs and status

**Exit — "real persistence, data survives a restart, unauthorized cannot read":** met. A second
application instance reads back what the first wrote; deletion removes what this service owns and
the account stops working immediately; cross-user reads return 404 and 403 as appropriate.

### Deferred, with reason

| Item | Phase | Why not now |
| --- | --- | --- |
| Trips, assessments, SSE, recommendations | 4–6 | Depend on the agent and on modules 04–08 |
| Rate limiting, circuit breaking | 7 | Depend on endpoints existing |
| `DELETE /api/v1/me` as a public endpoint | — | Implied by §4 of the contract document but absent from the frozen OpenAPI; needs a contract change with consumer review, so the worker is CLI-driven for now |
| Internal service OpenAPI documents | modules 03–08 | Not ours to write |

## 4. What was implemented

### Features

| Feature | Behaviour now | Entry point | Status |
| --- | --- | --- | --- |
| Public contract v1 | 31 entities, 23 operations, generated TS + Python clients | `packages/contracts/openapi/public-api.yaml` | Complete |
| App factory, settings, lifespan | Validated at startup; misconfiguration stops the process | `app/main.py`, `app/settings.py` | Complete |
| Middleware chain | Security headers, size limit, correlation, CORS, access log | `app/middleware/` | Complete |
| Error envelope | Every failure becomes the contract error shape | `app/errors/handlers.py` | Complete |
| Health and metrics | Liveness, bounded readiness, Prometheus | `GET /health/*`, `GET /metrics` | Complete |
| Structured logging | JSON with redaction in the pipeline | `app/observability/logging.py` | Complete |
| Persistence | Async engine, session scope, migrations `0001`–`0003` | `app/db/`, `migrations/` | Complete |
| Container | Multi-stage, non-root uid 10001, `dev` stage for the checks | `services/api/Dockerfile` | Complete |
| Keycloak realm | Public PKCE web client, local test client, audience mapper, `travel` scope | `infra/keycloak/smart-travel-realm.json` | Complete |
| Token verification | Algorithm allowlist, signature, iss/aud/exp/nbf, JWKS cache | `app/auth/` | Complete |
| Identity resolution | `sub` → internal UUID, created on first sign-in | `app/repositories/user_profiles.py` | Complete |
| Scope and role guards | 403 for a valid token with the wrong grant | `app/auth/dependencies.py` | Complete |
| `GET`/`PATCH /api/v1/me` | Profile read and update | `app/api/v1/me.py` | Complete |
| `POST /api/v1/consents` | Versioned grant and withdrawal, capped expiry | `app/api/v1/consents.py` | Complete |
| Emergency profile | `GET`/`PUT`/`DELETE`, envelope-encrypted | `app/api/v1/me.py` | Complete |
| Audit trail | Actions, versions and counts; never content | `app/repositories/audit.py` | Complete |
| Export and deletion | Queued, status-tracked, `identity` scope only | `app/cli/retention.py` | **Skeleton** |
| Trips, assessments, SSE | — | — | **Not implemented** |
| Rate limiting | — | — | **Not implemented** |

### Important flows

Request handling:

```text
socket
 -> SecurityHeadersMiddleware   headers on every response, including early rejections
 -> RequestGuardMiddleware      size limit before the body is read; client address resolved once
 -> RequestContextMiddleware    request_id + correlation_id minted, bound to the log context
 -> CORSMiddleware              exact-origin allowlist, identity headers exposed to the browser
 -> AccessLogMiddleware         one line + one metric, route template only
 -> route dependencies          verify token -> resolve user -> check account -> check scope
 -> handler                     owner-scoped repository query
 -> exception handlers          any failure -> stable envelope, detail to the log not the client
```

Emergency profile write:

```text
PUT /api/v1/me/emergency-profile
 -> require the travel scope
 -> require the EMERGENCY_PROFILE consent to be in force
 -> require a configured key, else 503 saying nothing was stored in the clear
 -> seal: random data key -> AES-256-GCM payload -> data key wrapped under the KEK
          owner id bound in as associated data
 -> one row per user, replaced not merged
 -> audit: key version and counts, never the contents
```

### What is explicitly not implemented

- Any `/api/v1/**` route beyond `/me`, `/me/emergency-profile` and `/consents`
- Rate limiting, idempotency storage, SSE
- Export/deletion beyond the `identity` schema
- Bulk key rotation (rotation works per row through the repository)

## 5. Actual architecture and code design

### Folder/file map

| Path | Purpose | Owner/consumer |
| --- | --- | --- |
| `packages/contracts/jsonschema/common/` | 31 canonical entities | 02 maintains; everyone consumes |
| `packages/contracts/openapi/public-api.yaml` | Public API contract | 02; consumed by 01 |
| `packages/contracts/generated/` | TS + Python clients, bundled spec | Generated; never hand-edited |
| `packages/contracts/consumer-checks/` | TypeScript that must keep compiling | 01's early warning |
| `tests/contract/` | 59 producer/consumer tests | Shared |
| `infra/keycloak/` | Local development realm | 02 + lead |
| `services/api/app/auth/` | JWKS cache, verification, principal, dependencies | 02 |
| `services/api/app/security/` | Envelope encryption | 02 |
| `services/api/app/repositories/` | Owner-scoped queries | 02 |
| `services/api/app/cli/` | Retention worker, key generator | 02 |
| `services/api/migrations/` | Alembic for `identity` and `travel` | 02 |
| `docs/api/field-ownership-matrix.md` | Who may write which field | Everyone |

### Decisions and trade-offs

**Entities live in JSON Schema; OpenAPI references them.** The same definitions serve the public
API, six internal APIs and the Python services. Cost: bundling needs a normalisation step.

**The schemas carry no `$id`.** With `$id`, relative `$ref`s re-root at an unfetchable URL and
redocly, ajv, openapi-typescript and datamodel-code-generator all fail to resolve them.

**Authentication is a dependency, not a middleware.** A middleware would run for `/health/*` and
`/metrics` and then need a skip list, which fails open as routes are added. A dependency makes
"unauthenticated" something written down, and the OpenAPI document shows it. *This departs from the
literal middleware order in the plan; the ordering rationale is in `app/main.py`.*

**Alembic's version table lives in a third schema, `api`.** In `public` it would be shared with six
other services, each reading the others' revisions as unknown heads; inside `identity` it would make
that schema undroppable, so revision `0001` could never be downgraded.

**The emergency profile uses envelope encryption rather than field encryption.** Rotation re-wraps
one small data key per row instead of rewriting every medical note, and reading a profile needs the
row *and* the environment. The owner id is bound in as associated data, so a row moved between users
fails to decrypt.

**No searchable copy of the emergency profile.** No `blood_type` column, no `allergies` column. Costs
a query nobody needs; removes a class of accidental disclosure.

**Consent is append-only with a policy version.** The question is not "may we" but "what did this
person agree to, and when". A record without the version of the text shown proves nothing.

**Hand-written response envelope rather than the generated models.** Handlers construct these and a
hand-written model can carry this service's own invariants. Drift risk is paid for by
`tests/test_contract_parity.py`.

### Accepted technical debt

- `app/schemas/envelope.py` duplicates shapes that also exist in the generated models, held in check
  by the parity tests.
- The image is 379 MB; `psycopg[binary]` plus the OpenTelemetry stack accounts for most of it.
- `packages/contracts` uses npm while `apps/web` will use pnpm — two lockfile formats in one repo.

## 6. API, contract and event changes

| Producer | Method/path | Request | Response | Consumer | Compatibility |
| --- | --- | --- | --- | --- | --- |
| 02 | 23 operations under `/api/v1` | see `public-api.yaml` | `{data, meta}` / `{error, meta}` | 01 | New — contract v1.0.0 baseline |
| 02 | `GET /health/live`, `GET /health/ready` | — | health models | orchestrator, runbook | Implemented |
| 02 | `GET /metrics` | — | Prometheus text | Prometheus | Implemented |
| 02 | `GET`/`PATCH /api/v1/me` | `UpdateProfileRequest` | `UserProfile` | 01 | Implemented |
| 02 | `POST /api/v1/consents` | `ConsentRequest` | `ConsentRecord` | 01 | Implemented |
| 02 | `GET`/`PUT`/`DELETE /api/v1/me/emergency-profile` | `EmergencyProfileUpsertRequest` | `EmergencyProfile` | 01 | Implemented (`DELETE` is additive, see below) |

Twenty of the twenty-three operations are contract only. `DELETE /api/v1/me/emergency-profile` is
implemented but **not yet in the OpenAPI document** — an additive change that belongs in a contract
PR alongside the `DELETE /api/v1/me` the contract document's §4 note implies. Flagged in §15.

- **Generated client command:** `cd packages/contracts && npm run generate`
- **Result:** `public-api.bundled.yaml` (4,074 lines), `public-api.d.ts` (2,786), `public_api.py` (1,507)
- **Contract lint:** `Woohoo! Your API description is valid.` with two documented exceptions in
  `.redocly.lint-ignore.yaml` (the health endpoints have no 4xx by design)
- **Breaking change check:** not wired. See §15.
- **Sanitized examples:** `packages/contracts/examples/`

## 7. Database, cache and storage changes

### Migrations

| Revision | Schema/table/index | Upgrade | Downgrade | Data impact |
| --- | --- | --- | --- | --- |
| `0001` | schemas `identity`, `travel` | `CREATE SCHEMA IF NOT EXISTS` + grant | `DROP SCHEMA` **without** CASCADE | None |
| `0002` | `identity.user_profiles` + partial index on `disabled_at` | create | drop | None |
| `0003` | `identity.consents`, `emergency_profiles`, `audit_log`, `data_subject_requests` + 5 indexes | create | drop | None |

Head: `0003`. Verified in-container: `alembic heads` → `0003 (head)`.

- **Empty DB → head:** pass
- **Previous main → head:** `main` carries no module-02 migrations, so identical to empty → head
- **Repeated upgrade:** pass
- **Each revision reverses on its own:** pass — targets named, not counted, because `-1` moves every
  time a revision lands
- **Refuses to drop a schema holding data:** pass
- **Restart persistence:** pass — a second application instance reads back what the first wrote
- **Backup/restore:** not exercised; no production data exists
- **Retention/cleanup:** `app/cli/retention.py`, `identity` scope only
- **Encryption/access control:** emergency profiles are AES-256-GCM envelope-encrypted under a key
  from the environment; the migration grants the migrating role usage on both schemas

### Redis/Qdrant/artifacts

Redis is connected and probed but not yet written to. The namespace is derived as `sta:{env}` so
every service derives it the same way.

## 8. External providers and real data

This module calls no provider. From phase 4 it proxies geocoding through module 04; it never calls a
provider directly and never accepts a provider URL from a request.

- **Runtime/demo contains no mock or hard-coded current data:** [x] — CI greps `services/api/app`
  for mock switches; a contract test asserts no `*/app` code reads the fixture folder
- **Test fixture provenance:** one real-sanitized fixture, captured from Open-Meteo geocoding on
  2026-09-19T08:11:38Z with source URL, licence, attribution, upstream content hash and a redaction
  note. Everything else is labelled structural and synthetic.
- **Unavailable capability behaviour:** readiness names the dependency that is down; the emergency
  profile endpoints answer 503 when no key is configured and say nothing was stored in the clear

## 9. Configuration and Docker

### Environment variables added

| Variable | Required | Secret | Default | If missing |
| --- | --- | --- | --- | --- |
| `OIDC_AUDIENCE` | no | no | `smart-travel-api` | Default used |
| `API_CORS_ALLOWED_ORIGINS` | no | no | `http://localhost:3000` | Default used; `*` rejected at startup |
| `API_TRUSTED_PROXY_HOPS` | no | no | `0` | Forwarding headers ignored |
| `API_MAX_REQUEST_BODY_BYTES` | no | no | `262144` | Default used |
| `API_READINESS_TIMEOUT_SECONDS` | no | no | `3` | Default used |
| `API_DB_*` (5 vars) | no | no | pool 10/5, 5 s connect, 10 s statement | Defaults used |
| `API_REDIS_TIMEOUT_SECONDS` | no | no | `2` | Default used |
| `API_OIDC_TIMEOUT_SECONDS` | no | no | `3` | Default used |
| `API_OIDC_ALLOWED_ALGORITHMS` | no | no | RS/ES family | Symmetric or `none` rejected at startup |
| `API_OIDC_LEEWAY_SECONDS` | no | no | `30` | Default used |
| `API_OIDC_JWKS_TTL_SECONDS` | no | no | `600` | Default used |
| `API_OIDC_JWKS_MIN_REFRESH_SECONDS` | no | no | `30` | Default used |
| `API_DOWNSTREAM_*_TIMEOUT_SECONDS` | no | no | `2` / `10` | Defaults used |
| `API_EMERGENCY_ENCRYPTION_KEYS` | **in production** | **yes** | unset | Emergency profile endpoints answer 503; production refuses to start |
| `API_EMERGENCY_ENCRYPTION_ACTIVE_VERSION` | no | no | last key listed | Default used |
| `API_CONSENT_LOCATION_ONCE_TTL_SECONDS` | no | no | `3600` | Default used |
| `API_CONSENT_LOCATION_LIVE_MAX_TTL_SECONDS` | no | no | `86400` | Default used |
| `API_CONSENT_RETENTION_DAYS` | no | no | `2555` | Default used |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | no | unset | Spans created and dropped |

### Run commands

```bash
cp .env.example .env     # set POSTGRES_PASSWORD, KEYCLOAK_ADMIN_PASSWORD
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api \
  python -m app.cli.generate_key     # paste as API_EMERGENCY_ENCRYPTION_KEYS=v1:<value>

docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app up -d --wait api

curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8000/metrics | head
```

- **Container user:** `app`, uid/gid 10001, verified by running the image
- **Ports:** none in `compose.yaml`; `8000` published by `compose.dev.yaml` only
- **Volumes:** dev only — read-only source mounts plus a writable tool-cache volume
- **Health:** container healthcheck probes `/health/live` alone; readiness probed separately
- **Image:** 379 MB, `sha256:b47f9548de09…`; contains no `.env`, `tests`, `.git` or `uv.lock`

## 10. Tests and verification

Run on 2026-09-20 after rebasing onto `origin/main` `29a1798`. Every API command runs **inside the
container** via `docker compose -p sta-phase1 -f compose.yaml -f compose.dev.yaml --profile core
--profile app run --rm api …`, abbreviated below as `docker compose run --rm api`.

| Test type | Command | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Compose validate | `docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app config` | 1 | 0 | 0 | `compose config OK` |
| API lint | `docker compose run --rm api uv run ruff check .` | — | 0 | 0 | `All checks passed!` |
| API format | `docker compose run --rm api uv run ruff format --check .` | 77 files | 0 | 0 | `77 files already formatted` |
| API types | `docker compose run --rm api uv run mypy app` | 53 files | 0 | 0 | `Success: no issues found in 53 source files` |
| API unit | `docker compose run --rm api uv run pytest -m "not integration"` | 156 | 0 | 99 deselected | |
| API integration | `docker compose run --rm api uv run pytest -m integration` | 99 | 0 | 156 deselected | Real PostGIS + real Keycloak |
| Contract lint/schemas/examples | `cd packages/contracts && npm run check` | 31 schemas, 6 examples | 0 | 2 lint exceptions | Documented in `.redocly.lint-ignore.yaml` |
| Generated output current | `cd packages/contracts && ./scripts/check-generated-clean.sh` | 1 | 0 | 0 | `Generated contract output matches the source.` |
| Contract tests | `uv run --project tests/contract pytest tests/contract` | 59 | 0 | 0 | |
| E2E | — | — | — | — | N/A — no web app and no assessment flow yet |

The deselected counts are the two halves of the same suite, split by the `integration` marker so the
fast tier stays fast. Nothing is skipped for an unexplained reason.

```text
$ docker compose run --rm api uv run ruff check .
All checks passed!

$ docker compose run --rm api uv run ruff format --check .
77 files already formatted

$ docker compose run --rm api uv run mypy app
Success: no issues found in 53 source files

$ docker compose run --rm api uv run pytest -m "not integration"
156 passed, 99 deselected in 3.27s

$ docker compose run --rm api uv run pytest -m integration
99 passed, 156 deselected, 15 warnings in 12.36s

$ cd packages/contracts && npm run check
Woohoo! Your API description is valid.
31 schemas compiled.
6 examples validated.

$ cd packages/contracts && ./scripts/check-generated-clean.sh
Generated contract output matches the source.

$ uv run --project tests/contract pytest tests/contract
59 passed in 1.69s
```

### Scenarios verified

- **Success:** health, metrics, profile read/update, consent grant/withdraw, emergency profile
  round trip with a real Keycloak token
- **Invalid input:** missing field, wrong type, unknown field, unknown route, wrong method,
  non-existent timezone, expiry in the past, oversized body
- **Unauthorized:** no token, wrong scheme, expired, wrong issuer, wrong audience, unknown kid,
  `alg: none`, HMAC substitution, token from the `master` realm, missing scope, disabled account,
  soft-deleted account
- **Ownership:** one user cannot see another's profile, consents or emergency profile
- **Timeout/partial:** hung dependency, over-budget readiness probe, optional dependency down
- **Leak checks:** a `RuntimeError` carrying a DSN and password produces a 500 with none of it in
  the body; readiness reports only the exception type; no profile field reaches stdout or stderr;
  no audit entry anywhere contains profile content; the database holds no readable copy
- **Restart/persistence:** a second application instance reads back what the first wrote
- **Deletion:** removes what this service owns, revokes consents, and the account stops working
  immediately

### Live evidence

```text
$ curl -sS http://localhost:8000/health/ready          # HTTP 200
ready
  postgres  up   (3.67 ms)
  redis     up   (1.56 ms)
  oidc      up   (5.93 ms)
  agent     down (2001.05 ms)  did not answer within 2s   [optional]

$ docker compose run --rm api alembic heads
0003 (head)
```

Against the running container with a token issued by the real realm:

```text
1. PATCH /me                       -> 200
2. PUT emergency (no consent)      -> 403
3. POST /consents                  -> 201
4. PUT emergency                   -> 200
5. GET emergency                   -> 200 | notes: "Carries an auto-injector." | key: v1
6. LOCATION_ONCE expiry capped to  -> 2026-09-19T14:54:12Z   (client asked for 2030)
7. GET /me consents  -> [('EMERGENCY_PROFILE', True), ('LOCATION_ONCE', True)] | has_emergency_profile: True
8. revoke consent                  -> 201
9. GET emergency after revoke      -> 403
10. DELETE emergency               -> 204   (works without consent)
```

What the database holds:

```text
SELECT count(*) FILTER (WHERE ciphertext LIKE '%penicillin%'), count(*) FROM identity.emergency_profiles;
 0 | 0

          action           |                          details
---------------------------+-----------------------------------------------------------
 CONSENT_RECORDED          | {"granted": true, "consent_type": "LOCATION_ONCE", "expiry_capped": true, ...}
 EMERGENCY_PROFILE_READ    | {"key_version": "v1"}
 EMERGENCY_PROFILE_WRITTEN | {"key_version": "v1", "allergy_count": 1, "has_medical_notes": true, ...}
```

A request with a bearer token and coordinates in the query string logged:

```json
{"event_type": "http_request", "http_method": "GET", "route": "<unmatched>", "status": 404,
 "duration_ms": 0.68, "client": "172.18.0.7", "request_id": "ed18a174-…",
 "correlation_id": "ed18a174-…", "trace_id": "8f8a821e…", "service": "api"}
```

No token, no query string, no coordinates. Across all API logs: 0 JWT-shaped strings, 0 occurrences
of the test user's e-mail or display name.

## 11. UI evidence

N/A — this module has no UI.

## 12. Safety, security and privacy review

- [x] Official warning/closure priority preserved — N/A at this layer; encoded in the contract
- [x] LLM/provider/RAG data treated as untrusted — marked as such in every schema carrying it
- [x] No secret, PII or exact location in code, log, trace or fixture — redaction is a pipeline
      processor; CI greps contract sources for secret-shaped strings and the realm file for
      credentials
- [x] Consent/auth/ownership enforced — ownership at the repository query; consent gates the
      emergency profile both ways
- [x] Timeout/retry/cancel bounded — every dependency check and outbound client has an explicit
      timeout; idempotency is phase 5
- [x] Source/freshness/quality/version retained — required by the contract, asserted by tests
- [x] Fallback/degraded behaviour does not invent data — readiness names what is down; the
      emergency profile refuses rather than storing plaintext
- [ ] Dependency/image/secret scans — **not wired**. See §15.

### Findings during the work

| Finding | Resolution |
| --- | --- |
| The redaction rule for long digit runs mangled correlation ids whose first UUID group is all digits | Allowlist of system-generated identifiers, checked after the deny list. Regression test added. |
| httpx logs every outbound URL at INFO, which will carry user-typed place names once geocoding is proxied | Its logger is set to WARNING |
| `/health/ready` detail could have carried a DSN from a driver exception | Only the exception type is reported; a test asserts a password cannot reach the response |
| The JWKS cooldown blocked the *first* legitimate rotation refresh, which would have locked every user out until the TTL | Cooldown now applies to repeat unknown-kid refreshes only |
| `contacts`, `insurance` and `policy_reference` were missing from the log redaction list | Added |

## 13. Problems encountered and resolutions

| Problem | Root cause | Evidence | Resolution | Remaining risk |
| --- | --- | --- | --- | --- |
| `datamodel-codegen` refused to emit a single file | Redocly's bundle contained components named after their source file; the dot reads as a module path | 19 such components | `scripts/bundle.mjs` folds each onto its canonical name and fails loudly if one cannot be resolved | Low — a new entity without an explicit component entry fails the build |
| Generated Pydantic models raised at import | `Uuid` had both `format: uuid` and a redundant pattern | `Unable to apply constraint 'pattern' … type 'uuid'` | Dropped the pattern | None |
| Redocly could not resolve `$ref`s | `$id` re-rooted relative refs at an unfetchable URL | `can't resolve reference primitives.schema.json…` | Removed `$id` from all 31 schemas | Files cannot move without updating referrers |
| Container would not start | pydantic-settings JSON-decodes complex types from the environment before validators run | `error parsing value for field "cors_allowed_origins"` | Annotated with `NoDecode` | None |
| Alembic downgrade could not drop `identity` | The version table lived inside the schema being dropped | `DependentObjectsStillExist` | Moved bookkeeping to the `api` schema | None |
| Keycloak refused the realm import | Unknown field `_comment`, then an unresolvable composite role | `Unrecognized field "_comment"`; `Unable to find composite realm role: uma_authorization` | Comment moved to the README; built-in roles declared explicitly | None |
| Tokens carried no roles and no profile claims | Declaring `clientScopes` **replaces** Keycloak's built-ins rather than adding to them | `realm_access` absent; `scope` lacked `profile` | The six built-in scopes declared explicitly and assigned as client defaults | None — a real-Keycloak test asserts both |
| Keycloak refused the password grant for test users | Verify-profile counts a user without e-mail/name as "not fully set up" | `invalid_grant: Account is not fully set up` | Fixture creates a complete user with `requiredActions: []` | None |
| Test database URL parsed but failed to authenticate | `str(URL)` masks the password as `***` in SQLAlchemy | `password authentication failed` | `render_as_string(hide_password=False)` | None |
| Every *second* `PUT` to the emergency profile was a 500 | `onupdate=func.now()` expires the attribute; reading it in the handler triggers lazy IO from async code | `MissingGreenlet` | Explicit refresh after the flush | None — the test now asserts the replacing write's status |
| Autogenerate proposed dropping PostGIS's `spatial_ref_sys` | A table reflected from `public` arrives with `schema=None`, which the filter treated as ours | Autogenerate output | Filter excludes anything outside `identity`/`travel` | None |
| Autogenerate kept proposing to remove three column comments | Models used `doc=` (Python-side) where migration `0002` wrote `comment=` (database-side) | Autogenerate output | Models declare comments the way the database stores them | None |
| Settings test passed on the host and failed in the container | It relied on `POSTGRES_PASSWORD` happening to be unset | `DID NOT RAISE` | Environment cleared explicitly | None |
| Contract fixture-leak test failed after module 04 landed | It matched the phrase "real-sanitized" anywhere under `services/` | 5 false positives in module 04 | Scoped to `*/app` and to `contracts/examples` | None |
| `compose.yaml` / `compose.dev.yaml` conflicted on rebase | Module 04 added `external-data` where module 02 adds `api` | Rebase conflict | Both kept; purely additive | None |

## 14. Performance and operational behaviour

No load test was run: there is no endpoint worth loading yet. The budgets in §12 of the acceptance
runbook apply from phase 5.

| Metric | Target | Actual | Condition | Pass |
| --- | --- | --- | --- | --- |
| Readiness probe | must answer inside its budget | ~2.0 s, dominated by the absent agent timing out | agent not running | Yes — budget is 3 s |
| `postgres` check | — | 3.67 ms | local compose | — |
| `redis` check | — | 1.56 ms | local compose | — |
| `oidc` check | — | 5.93 ms | local compose | — |

Metrics: `api_http_requests_total`, `api_http_request_duration_seconds`, `api_http_errors_total`,
`api_dependency_check_duration_seconds`, `api_dependency_up`, `api_readiness_state`,
`api_request_body_rejected_total`, `api_auth_failures_total`. Latency buckets have edges at 0.3 s and
0.5 s so the runbook's p95 targets can be measured.

**Incident disable path:** no feature flag, because there is no feature to disable. Rolling back is
an image tag change; the three migrations are additive.

## 15. Known limitations and technical debt

| Limitation | Impact | Workaround | Owner | Priority | Follow-up |
| --- | --- | --- | --- | --- | --- |
| Export and deletion cover `identity` only | A person told "deleted" still has rows in five other schemas | Every completed request names them in `incomplete_scopes` | 02 + owners 03–08 | High | Wire the service APIs as each lands |
| `DELETE /api/v1/me` and `DELETE /me/emergency-profile` are not in the OpenAPI | The web app cannot generate a client for them | The latter works; the former is CLI-driven | 02 | High | Additive contract PR |
| No breaking-change detection on the contract | A breaking change could merge without a version bump | Review plus consumer checks | 02 + lead | High | `oasdiff` against `origin/main` in `contracts.yml` |
| No container vulnerability scan or SBOM | Required by §12 of the delivery rules | — | lead | High | Scanner choice affects every service |
| No rate limiting | One client can exhaust a provider quota for everyone | Redis is already required and probed | 02 | High | Phase 7 |
| A token stays valid until it expires | Disabling takes effect immediately via the local row, but there is no introspection or revocation list | `disabled_at` is checked on every request | 02 | Medium | Revisit if sessions get long |
| Generated Pydantic models do not enforce coordinate ranges | A swapped coordinate would pass model validation | The API validates at the boundary from phase 4; the JSON Schema does enforce it | 02 | Medium | Pinned by a test |
| No bulk key rotation command | Rotating a large table means calling the repository per row | Rotation itself works | 02 | Low | Add when there is data |
| The realm enables a direct-grant test client | A password-grant surface exists in the local realm | Documented; must be deleted in any non-local realm | 02 + lead | Low | Provision staging separately |
| `packages/contracts` uses npm while `apps/web` will use pnpm | Two lockfile formats | — | 01 + 02 | Low | Fold into the workspace when `apps/web` lands |

## 16. Handoff to other members

| Recipient | What is ready | What they must do | Blocking? |
| --- | --- | --- | --- |
| **01 — web** | Generated TypeScript at `packages/contracts/generated/typescript/public-api.d.ts`; `consumer-checks/` shows the import shape. Working OIDC: the `web` client is public + PKCE with redirect `http://localhost:3000/api/auth/callback/*`. `GET`/`PATCH /me`, `POST /consents` and the emergency profile are live. | Import the generated types rather than hand-writing shapes. Request the `travel` scope — without it every `/api/v1` call is 403. Add your origin to `API_CORS_ALLOWED_ORIGINS`. | Contract review is blocking for you |
| **03 — agent** | `TravelRequest`, `RunRef`, `RunState`, the SSE payload schemas and the nine `RunStage` values | Implement `/internal/v1/runs` against `TravelRequest`; report progress with those stages. Progress copy is an **i18n key**, never a translated sentence. Add `openapi/internal-agent.yaml` on your own contract branch. | Yes — phase 5 depends on it |
| **04 — external-data** | Already merged. `LocationRef`, `SourceProvenance` and `DataQuality` are the shapes the API will proxy | Confirm your geocoding output maps onto `LocationRef` as the real-sanitized fixture shows | No |
| **05 — data-integration** | `IntegratedTravelContext`, `DataQuality`, the weather/transport/disaster entities | You own `DataQuality.formula_version`. Snapshots are immutable; a refresh is a new id with `supersedes_snapshot_id` | No |
| **06 — risk-knowledge** | `RiskAssessment`, `RetrievedEvidence`, `RouteCandidate` | `reason_codes` is a closed vocabulary — propose additions on a contract branch. You own `exposure.closed` | No |
| **07 — decision-engine** | `DecisionResult` including `validation.locked_action` | The API rejects a result whose `locked_action` is false rather than displaying it | No |
| **08 — recommendation** | `RecommendationResponse`, `OfficialContact`, `FeedbackEvent`, `AlertSubscription` | **Review these — they are your entities and were drafted here** because the public API cannot be described without them. Build on them rather than forking on your contract branch. | **Review is blocking** |
| **Lead** | Shared surfaces changed: `compose.yaml`, `compose.dev.yaml`, `.env.example`, `Makefile`, `.github/workflows/`, `infra/keycloak/`, `docs/handoffs/README.md` | Review. All additive. The compose conflict with module 04 was resolved by keeping both services. | Yes |

## 17. Commit and PR inventory

Two PRs, stacked. The second is branched from the first because the service cannot be built without
the contract.

**PR 1 — `contract/02-public-travel-schema` → `main`** (4 commits):

```text
fec3ff7 contract(contracts): add public API v1 and canonical entity schemas
3363f49 build(contracts): add contract lint, validation and client generation
683c01d test(contracts): add contract fixtures and producer/consumer tests
d55ec81 ci(contracts): gate pull requests on the contract pipeline
```

**PR 2 — `feat/02-api-scaffold` → `main`** (18 further commits, `Depends on` PR 1):

```text
a5e3f4c feat(api): add FastAPI scaffold, settings, middleware and error envelope
1a14ef6 feat(api): add liveness, readiness and metrics endpoints
79d7cfb feat(api): add database engine and migrations for identity and travel
a0fa56e build(api): package the service as a non-root image and wire it into compose
e5832b6 ci(api): gate pull requests on lint, types, tests and image checks
a5ffce1 fix(contracts): scope the contract test run to its own directory
c15cbef docs(api): add the M02 completion report for phases 0 and 1
b3d24bb feat(infra): add the Keycloak realm the public API verifies against
ad32053 feat(api): verify OIDC access tokens with a rotation-aware JWKS cache
bd3cc59 feat(api): map the OIDC subject to an internal user with owner-scoped queries
c31e64b feat(api): protect GET /api/v1/me with scope and ownership checks
802be9d build(api): run the module checks inside the container
6fef6ec feat(api): add envelope encryption for the emergency profile
b43440c feat(api): add consent, emergency profile, audit and request tables
0c5e261 feat(api): add profile updates, consent and the emergency profile endpoints
c85db73 feat(api): add the export and deletion worker and a key generator
6ac48b2 docs(api): document consent, encryption and the retention worker
c781226 fix(contracts): scope the fixture-leak check to what it meant
```

- **PR review comments resolved:** none yet — not opened
- **Required checks status:** all green locally; the two new workflows have not run on a remote
- **Rebased on main SHA:** `29a1798`
- **Proposed squash titles:**
  - `[M02] Freeze public API contract v1 and wire client generation`
  - `[M02] Add public API with OIDC, identity, consent and encrypted emergency profile`

## 18. Rollback and recovery

1. **Feature flag / provider disable:** N/A — no feature flag and no provider.
2. **Application rollback:** revert the image tag, or remove `api` from the `app` profile. Nothing
   depends on it yet.
3. **Migration:** `alembic downgrade base` drops the three revisions, and only while the tables are
   empty. Once real accounts exist this becomes a forward-fix — note that dropping `audit_log`
   destroys the record of what was done to accounts, which cannot be reconstructed from anywhere.
4. **Model/policy/prompt/knowledge:** N/A.
5. **Data/cache cleanup:** none needed. **Do not** run `docker compose down -v` — it deletes the
   PostgreSQL and Qdrant volumes.
6. **Encryption keys:** never remove a key version while rows reference it; they become unreadable.
   Rotate by appending and re-wrapping.
7. **Verification after rollback:** `docker compose ps`, then `curl /health/live` and
   `/health/ready`.

## 19. Final declaration

- [x] The work in scope (phases 0–3) is complete, with evidence
- [x] No required work is hidden — phases 4 to 8 are listed as not started, and the skeleton parts
      are labelled as skeletons
- [x] Documentation, env, contracts and migrations updated
- [ ] Downstream owners handed off — written in §16, **not yet communicated**
- [x] Ready to merge, subject to the reviews named in §16
- [ ] Ready to release — no. No trip, no assessment, no rate limiting, and export/deletion reaches
      only one of six schemas.

Prepared by: module 02 (with Claude Opus 5)
Reviewed by: —
Date: 2026-09-20
