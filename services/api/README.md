# `services/api/`

**เจ้าของ:** คนที่ 2 · 02-api

The public trust boundary. The browser reaches `web` and this service and nothing else, so every
capability a user has passes through here: authentication, ownership, validation, rate limiting,
idempotency, and the orchestration of an assessment.

Plan: [`IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md)
Contract: [`packages/contracts/openapi/public-api.yaml`](../../packages/contracts/openapi/public-api.yaml)

## What exists today

Phases 1, 2 and 3 of the plan.

| Area | State |
| --- | --- |
| App factory, settings validation, lifespan | Done |
| Middleware chain (security headers, size limit, correlation, CORS, access log) | Done |
| `/health/live`, `/health/ready`, `/metrics` | Done |
| Error handling — every failure becomes the contract envelope | Done |
| SQLAlchemy engine, session scope, Alembic per schema | Done |
| Docker: multi-stage, non-root, healthcheck, compose wiring | Done |
| OIDC token verification, JWKS cache with rotation handling | Done |
| Subject to internal user mapping, owner-scoped repository | Done |
| Scope and role dependencies | Done |
| `GET`/`PATCH /api/v1/me` | Done |
| `POST /api/v1/consents` — versioned grant and withdrawal | Done |
| `GET`/`PUT`/`DELETE /api/v1/me/emergency-profile`, envelope-encrypted | Done |
| Audit trail that records actions but never their content | Done |
| Export and deletion worker with tracked status | Skeleton — `identity` only, see below |
| Trips, assessments, SSE, the rest of `/api/v1/**` | Phases 4–6 — **not implemented** |
| Rate limiting | Phase 7 — **not implemented** |

## Run it

```bash
# from the repository root, with .env filled in (see .env.example)
docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app up -d --wait api

curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8000/metrics | head
```

Locally, without Docker:

```bash
cd services/api
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -m "not integration"   # fast tier: no database, no network
uv run pytest -m integration         # needs Docker; starts a throwaway PostGIS container
```

Or inside the container, against the same platform the service runs on — which is what the
delivery rules ask for and what CI does:

```bash
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api uv run ruff check .
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api uv run mypy app
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api uv run pytest
```

The integration tier finds its database two ways. Inside compose there is no Docker socket, so it
creates a throwaway database on the PostgreSQL next door (`TEST_DATABASE_URL`); on a laptop it
starts a container with Testcontainers. Either way the tests get a database nobody else is using —
sharing one would let a migration test that drops a schema delete another test's tables.

The Keycloak tests skip themselves unless the realm is actually up, and say how to start it.

## Health

Liveness and readiness answer different questions, and conflating them causes outages.

`/health/live` touches nothing external. If it also probed the database, a brief outage would
restart every healthy container and turn a recoverable blip into an outage of its own. The Docker
healthcheck uses this endpoint only.

`/health/ready` probes the dependencies this instance cannot serve without, each bounded
individually and by a budget for the whole probe. 503 takes the instance out of rotation instead of
letting it answer requests it cannot honour.

| Dependency | Required | Why |
| --- | --- | --- |
| `postgres` | yes | System of record. Nothing works without it. |
| `redis` | yes | Rate limiting, idempotency and run status. Without it, duplicate assessments are accepted and one client can exhaust a provider quota for everyone. |
| `oidc` | yes | Without the discovery document no token can be verified, so every authenticated request would fail. |
| `agent` | **no** | Assessments stop; profiles, trips, consent and the emergency screens keep working. Reporting the whole API unready would take down the screens someone might open precisely because something has gone wrong. |

A failing check reports the exception type, never its message: this endpoint is unauthenticated and
a driver's error message contains the connection string.

## Authentication

An OIDC access token from the project's Keycloak realm. Verification lives in `app/auth/` and is
applied as a **dependency**, not as middleware: a middleware would have to run for `/health/*` and
`/metrics` too and then decide to skip them, and that skip list fails open as routes are added.

What is checked, in this order:

1. **Algorithm, from the header, against an allowlist** — before any key is loaded. `alg: none`
   needs no key at all, and `HS256` would be verified using the provider's *public* key as a shared
   secret, which is published in the JWKS. Both are rejected before a lookup happens.
2. **Signature**, against the key named by `kid`.
3. **Issuer, audience, expiry, not-before, issued-at**, with a configurable clock-skew leeway.
4. **The subject resolves to a local user**, created on first sign-in.
5. **The account is neither disabled nor deleted.** A JWT cannot be withdrawn once issued, so
   without this a disabled account keeps working until its token expires.
6. **Scope**, per route. A valid token with the wrong scope is **403, not 401** — 401 tells the
   client to refresh, which returns the same token, and the client loops.

Every rejection returns the same 401 with the same message. The specific reason goes to the log,
where it is useful and not attacker-visible; a caller that could tell "expired" from "wrong
audience" could map the configuration by sending tokens and reading the differences.

### The JWKS cache

Fetching keys per request would put an HTTP call in front of every API call; caching them forever
would break every token the moment the provider rotates. So: served from memory for a TTL,
refetched once when a token names a key id the cache has not seen, and that refetch rate-limited —
`kid` comes from the token, so without a cooldown a stream of tokens carrying random key ids turns
one request into one outbound fetch, with this service as the amplifier.

### Ownership

Enforced at the repository query, not in the handler. `app/repositories/user_profiles.py` has no
method that can return a row without being given an owner, so an ownership check cannot be
forgotten — it can only be deliberately removed. `/api/v1/me` has no id parameter at all: the row
is chosen by the id in the verified principal, never by anything the client sent.

### Logs

The authenticated caller appears as `user_id` plus `subject_digest` — a truncated SHA-256 of the
OIDC subject. Enough to correlate one person's requests during an investigation, without writing an
identity-provider id into log storage.

## Consent

Append-only. Granting and withdrawing go through the same endpoint, because making withdrawal
harder than granting is a dark pattern rather than an oversight to fix later. Every record carries
the version of the text the person was shown — a consent record without that proves nothing, which
is why this is a table and not a column of booleans.

A decision supersedes the previous one for its type rather than overwriting it, so the table can
answer what someone agreed to *and when*.

"In force" means granted, not revoked and not expired — all three. Checking only `granted` would
let a location grant keep working after it lapsed, which is the difference between a one-off share
and tracking. Location grants are capped server-side: `API_CONSENT_LOCATION_ONCE_TTL_SECONDS` and
`API_CONSENT_LOCATION_LIVE_MAX_TTL_SECONDS` are ceilings, and a client may ask for less but never
for more.

## The emergency profile

The most sensitive thing this service holds, so it gets its own treatment.

**Envelope encryption.** Each record has its own data key; the payload is sealed with that, and the
data key is sealed with a key-encryption key from configuration. Two consequences follow, and they
are why it is not just sealed directly: rotating the key means re-wrapping one small data key per
row rather than rewriting every medical note, and reading a profile needs the row *and* the
environment, which live in different places in any real deployment.

AES-256-GCM throughout, and the owner id is bound in as additional authenticated data, so a row
moved to another user's record fails to decrypt instead of handing over someone else's details.

**No plaintext fallback.** With no key configured the endpoints answer 503 and say nothing was
stored in the clear. In production the process refuses to start at all.

**No searchable copy.** The table has no `blood_type` column and no `allergies` column, only
ciphertext and the metadata to open it. A `SELECT *` while debugging shows bytes.

**Consent gates it both ways.** Being signed in is not agreement to store medical data; storing and
reading both need the `EMERGENCY_PROFILE` consent, and withdrawing it takes effect immediately
rather than at the next purge. Deleting works regardless — withdrawing data must never be harder
than providing it.

Rotate a key by appending, never replacing:

```bash
docker compose run --rm api python -m app.cli.generate_key
# API_EMERGENCY_ENCRYPTION_KEYS=v1:<old>,v2:<new>
# API_EMERGENCY_ENCRYPTION_ACTIVE_VERSION=v2
```

Dropping a key while rows still reference it makes them unreadable, and the service says so loudly
rather than reporting the profile as missing.

## The audit trail

`identity.audit_log` records that something happened and never what it said. A profile write is
logged with the key version and the *number* of allergies, never the allergies. `app/repositories/
audit.py` rejects a forbidden key outright rather than relying on everyone remembering, because an
audit log that quotes the data it audits is a second, less guarded copy of it.

Entries carry the request and correlation ids, so one can be matched to the log lines for the same
request. They outlive the account: `user_id` is nulled on deletion, because *that* an account was
deleted is worth keeping and *who* it was is not.

## Export and deletion

```bash
docker compose run --rm api python -m app.cli.retention --once
```

A skeleton, and honest about being one. Deleting everything about a person means reaching the
`agent`, `integration`, `knowledge`, `decision` and `recommendation` schemas through APIs that do
not exist yet, so every completed request records those as `incomplete_scopes`. **COMPLETED here
means "everything this service owns", never "erased everywhere"** — and the person who asked is
exactly the one entitled to know the difference.

Within `identity` it does the real work: deletion hard-deletes the emergency profile, withdraws
every standing consent and soft-deletes the profile; export assembles the profile, the consent
history and the emergency profile, withholding the last if the consent that authorised it has been
withdrawn. An export must not become the way to read data whose consent no longer stands.

Requests are queued through `identity.data_subject_requests` and claimed with
`FOR UPDATE SKIP LOCKED`. There is one worker today; a queue that only works with one breaks the
first time somebody scales it.

## Layout

```text
app/
├─ main.py            app factory and lifespan; middleware order is documented there
├─ settings.py        every environment value, validated at startup
├─ api/               routers: health, and /api/v1/me
├─ auth/              JWKS cache, token verification, principal, dependencies
├─ security/          envelope encryption for the emergency profile
├─ services/          wiring that is neither a route nor a query
├─ cli/               retention worker and key generation
├─ repositories/      owner-scoped queries — the only way to reach a row
├─ db/                declarative base, engine, session scope
├─ errors/            contract error codes, exceptions, handlers
├─ health/            readiness checks and the concrete probes
├─ middleware/        security headers, size limit, correlation, access log
├─ observability/     structured logging with redaction, metrics, tracing
└─ schemas/           the response envelope the handlers build
migrations/           Alembic, scoped to the identity and travel schemas
```

## Database

This service owns two schemas and writes nowhere else. Another service reads its data through the
public API, never through the tables.

| Schema | Holds |
| --- | --- |
| `identity` | `user_profiles`, `consents`, `emergency_profiles`, `audit_log`, `data_subject_requests` |
| `travel` | Trips, assessment requests, idempotency records |
| `api` | This service's Alembic version table only — no user data |

The version table is deliberately in a third schema. In `public` it would be shared with the six
other services on the same instance, and each would read the others' revisions as unknown heads.
Inside `identity` it would make that schema undroppable, so the first migration could never be
downgraded.

```bash
docker compose run --rm api alembic revision --autogenerate -m "add trip revision"
docker compose run --rm api alembic upgrade head
docker compose run --rm api alembic downgrade -1
```

Read every autogenerated migration before committing it: Alembic cannot tell a rename from a
drop-plus-add, and getting that wrong loses data.

## Logging and privacy

Logs are JSON, one line per event, with `request_id`, `correlation_id` and `trace_id` on every line
so one request can be followed across eight services.

Redaction is a processor in the pipeline, not a convention people follow. It removes credentials,
contact details, health data and **exact coordinates** wherever they appear, at any nesting depth. A
latitude in a log file is a person's location history, so it is treated like a medical note.
Country code and timezone survive, because they make a log useful for debugging coverage without
describing where someone was.

Two logs are silenced on purpose: uvicorn's access log, which records the raw path including the
query string, and httpx's request log, which records outbound URLs. This service logs access
itself, after redaction, using the route *template* rather than the resolved path.

## Configuration

Every value is in `app/settings.py` with its reasoning; `.env.example` lists the names. Notes on
the ones that are easy to get wrong:

- `API_CORS_ALLOWED_ORIGINS` — exact origins, comma-separated. A wildcard is rejected at startup:
  this API answers with credentials, and a wildcard would let any site read a signed-in user's trips.
- `API_TRUSTED_PROXY_HOPS` — defaults to `0`, meaning forwarding headers are ignored entirely and
  the socket address is used. Set it to the number of reverse proxies actually in front of the
  service. Trusting the header by default would let any client choose its own rate-limit bucket.
- `OTEL_EXPORTER_OTLP_ENDPOINT` — unset means spans are created and dropped. Traces still appear in
  the logs via `trace_id`, and local development needs no collector.

In production, plain-HTTP CORS origins and a plain-HTTP OIDC issuer are rejected at startup.

## Known limitations

- Export and deletion cover `identity` only. Every completed request names the five schemas it could
  not reach, and the public `DELETE /api/v1/me` endpoint the contract document implies is not in the
  frozen OpenAPI yet — it needs a contract change, so the worker is driven by CLI for now.
- Key rotation re-wraps one row at a time through the repository; there is no bulk rotation command.
- Trips, assessments and the rest of `/api/v1/**` do not exist. Phases 4–6.
- No rate limiting yet, although Redis is already required and probed. Phase 7.
- A token stays valid until it expires. Disabling an account takes effect immediately because the
  local row is checked on every request, but there is no token introspection or revocation list.
- The realm at `infra/keycloak/` is for local development and enables a direct-grant test client.
  See that folder's README before using it anywhere else.
- `infra/postgres/init/00-schemas.sql` creates `api` but not `identity` or `travel`. The migration
  creates them itself, so a fresh or existing database both work; the init script is a shared
  surface and reconciling it is an infra PR.
