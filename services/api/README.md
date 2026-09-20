# `services/api/`

**เจ้าของ:** คนที่ 2 · 02-api

The public trust boundary. The browser reaches `web` and this service and nothing else, so every
capability a user has passes through here: authentication, ownership, validation, rate limiting,
idempotency, and the orchestration of an assessment.

Plan: [`IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md)
Contract: [`packages/contracts/openapi/public-api.yaml`](../../packages/contracts/openapi/public-api.yaml)

## What exists today

Phases 1 to 5 of the plan.

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
| `POST`/`GET /api/v1/trips`, `GET`/`PATCH`/`DELETE /api/v1/trips/{id}` | Done |
| Trip revision / ETag / `If-Match` optimistic concurrency | Done |
| Keyset pagination over the trip list | Done |
| Idempotent trip creation (`Idempotency-Key`) | Done |
| `GET /api/v1/locations/search` — proxied to module 04 | Done |
| `POST /api/v1/trips/{id}/assessments` — start a run, idempotent | Done |
| `GET`/`DELETE /api/v1/runs/{id}` — poll and cancel | Done |
| `GET /api/v1/runs/{id}/events` — SSE with `Last-Event-ID` resume | Done |
| Run state machine, refusing backwards and post-terminal moves | Done |
| Recommendation revalidated against the contract before exposure | Done |
| Conversations, recommendations GET, safety map, emergency, feedback | Phase 6 — **not implemented** |
| Rate limiting, circuit breaking | Phase 7 — **not implemented** |

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

## Trips

A trip is a saved journey. Five routes, and three rules that hold across all of them.

**Ownership is a query, not a check.** Every repository function takes the owner resolved from the
token and filters on it; there is no `get(trip_id)` without one. A trip belonging to somebody else
is reported as 404, identically to one that does not exist, so ids cannot be probed by watching the
status change.

**A mutation is guarded by a revision.** `GET` returns `ETag: W/"3"`; `PATCH` requires that value
back in `If-Match`. The comparison happens *inside* the UPDATE statement, not before it:

```sql
UPDATE travel.trips SET revision = revision + 1, ...
 WHERE id = :id AND user_id = :owner AND deleted_at IS NULL AND revision = :expected
```

Two tabs editing the same trip are therefore resolved by PostgreSQL. One gets revision 4, the other
gets 412 and has to reload. A read-then-write implementation passes a sequential test and loses an
edit in production, which is why `tests/test_trip_concurrency.py` runs real concurrent transactions.

Missing `If-Match` is 428, not a silent unconditional write. `If-Match: *` is refused too — it means
"whatever is current", which is exactly the overwrite the header exists to prevent.

**Changing the journey invalidates its assessment.** Moving the origin, destination, departure,
return, time zone or travel modes clears `latest_request_id` and `selected_route_id`. Keeping them
would let the UI go on showing a verdict reached for a different journey, and a stale safety answer
is indistinguishable from a current one. Renaming a trip or changing preferences does not.

### Creating a trip

Both endpoints must be `confirmed_by_user`. The coordinates decide which weather, closures and
alerts get fetched, and geocoding "Springfield" returns a list whose first entry is a guess; a pin
nobody looked at would send every hazard lookup somewhere the traveller never chose.

`Idempotency-Key` makes a retry safe. The same key with the same body returns the original trip; the
same key with a different body is 409 `IDEMPOTENCY_CONFLICT`. Neither the key nor the body is
stored — both are reduced to a SHA-256 digest, because the key is a bearer value and the body holds
the coordinates of somebody's journey. Two concurrent retries race on a unique constraint inside a
savepoint, so the loser rolls back its own trip rather than leaving an orphan.

### Listing

Keyset pagination on `(departure_time, id)`, newest departure first. Not OFFSET: a trip created
while somebody is paging would shift every later page by one and hide a row. The id breaks ties
between two trips leaving at the same moment. Cursors are opaque and must not be constructed by a
client. Soft-deleted trips are excluded unless `status=DELETED` is asked for explicitly.

### Deleting

A soft delete. The response reports `IN_PROGRESS`, never `COMPLETED`: the trip stops being visible
at once, but assessments and recommendations made for it live in other services' schemas and are
removed by the retention worker. Claiming completion before that has happened would be a
reassurance this service cannot honestly give.

## Place search

`GET /api/v1/locations/search` proxies to module 04's `/internal/v1/geocode/search`. This service
never talks to a geocoding provider, holds no provider key, and never takes a URL from a caller —
the base URL is configuration and the path is a constant. Anything else would make the public API,
which sits on the internal network holding a service credential, an SSRF proxy for everything
behind the firewall.

An empty list means the provider matched nothing. A provider that is down is 503, and a slow one is
504. The two are never collapsed: a traveller told "no results for Chiang Mai" concludes something
very different from one told "search is unavailable". Results are returned with
`confirmed_by_user: false` whatever module 04 said — confirmation is a person looking at a map, and
no upstream service may assert it on their behalf.

## Assessments and runs

`POST /api/v1/trips/{trip_id}/assessments` accepts work and returns 202 with a `RunRef`. Nothing has
been assessed when it returns; the client follows the run over SSE or by polling.

### The ordering that stops runs being lost

The request row is **committed before the agent is called**. Not flushed — committed. Every other
order loses runs:

| Order | What it loses |
| --- | --- |
| Call the agent, then write | The run, whenever this process dies between the two |
| Write without committing, then call | The run, to the rollback triggered by the very failure being handled |
| **Commit, then call** | Nothing. The worst case is a run that exists and failed |

So an agent that is down produces a run in `FAILED` with a retryable error code, which the
traveller can see and retry — not a request that vanished with nothing to poll.

### The state machine

`app/domain/run.py` decides which reports from the agent are allowed to change the record.

- `COMPLETED`, `PARTIAL`, `FAILED` and `CANCELLED` are terminal and accept no successor. A late or
  replayed message about a finished run is dropped. A traveller told their assessment failed has
  already acted on that; reviving the run would change the answer under them.
- Nothing returns to `QUEUED`. A started run cannot become unstarted.
- A status outside the contract is refused rather than coerced. `SUCCEEDED` is not silently read as
  `COMPLETED` — that is how a future agent release would start reporting failures as successes.

An unrecognised *stage*, by contrast, is dropped and the run continues: a stage is a display hint,
and losing a hint is a smaller harm than failing a run over a label.

### Idempotency

`Idempotency-Key` uses the same table trips use. The same key with the same body returns the
original run (200, not 202); the same key with a different body is `IDEMPOTENCY_CONFLICT`. This
service's own `request_id` is sent to the agent as *its* idempotency key, so a retry at the HTTP
layer cannot start a second assessment either.

### SSE

`GET /api/v1/runs/{request_id}/events`. Ownership is checked before the stream opens, while a
status code can still say so — once the response has begun, a refusal can only be an event, and a
browser's `EventSource` retries those for ever.

Events live in a Redis **stream**, `sta:{env}:run:{request_id}:events`, not pub/sub. A stream keeps
what it published, so a client that reconnects with `Last-Event-ID` receives what it missed.
Pub/sub delivers only to whoever is connected, which means a dropped connection can lose the
terminal event — the one event that decides what the traveller is told.

The bridge forwards an event only if its name is in the contract and its payload validates against
that name's model, and the models forbid undeclared fields. That is the last place a prompt, a
provider body or a token can be stopped before it reaches a browser. An event that fails is dropped
whole rather than stripped: something nobody expected is something nobody has reasoned about.

Streams are capped per user and have a hard duration; a client that needs longer reconnects and
loses nothing. `X-Accel-Buffering: no` stops nginx turning progress into one long silence.

### Validating the result before exposing it

When the agent reports `COMPLETED`, this service fetches the recommendation from module 08 and
checks it against the contract *before* the run is marked complete. It must parse, carry sources
and freshness, hold known enum values, and name the same run and trip that asked for it. Anything
else and the run becomes `FAILED` with `POLICY_VALIDATION_FAILED`, and the id is never handed out —
an id leading to an object this service could not read is worse than no id, because the traveller
would act on it.

If module 08 is merely *unreachable*, the run stays in flight and the next poll tries again. It is
neither completed on an unverified result nor failed on a result that may be perfectly good.

### Caching

A run's state is one person's journey, so no shared cache may hold it. The poll endpoint sends
`private, max-age=2` with `Vary: Authorization`; cancellation and the SSE stream send `no-store`.
The max-age is small on purpose — the point of polling is freshness, and a proxy holding a run's
state even briefly can show a verdict that has since changed.

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
├─ api/               routers: health, /api/v1/me, /api/v1/trips, /api/v1/locations
├─ auth/              JWKS cache, token verification, principal, dependencies
├─ clients/           calls to internal services; base URLs come from settings, never a request
├─ domain/            trip rules — no FastAPI, no SQLAlchemy, testable on their own
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
| `travel` | `trips`, `idempotency_keys` (assessment requests arrive in phase 5) |
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
- `API_TRIP_SUPPORTED_TRAVEL_MODES` — the modes this deployment has a real data source for. A mode
  outside the list is refused with `UNSUPPORTED_COVERAGE` rather than accepted and then silently not
  assessed. `FLIGHT` is absent by default because the contract's flight provider is Amadeus
  production and the shared context rules its test environment out as acceptance data.
- `INTERNAL_SERVICE_TOKEN` — the shared secret presented to internal services. Blank counts as
  unset, and place search then reports itself unavailable rather than sending an empty bearer token
  and having module 04 look broken.

In production, plain-HTTP CORS origins and a plain-HTTP OIDC issuer are rejected at startup.

## Known limitations

- Export and deletion cover `identity` only. Every completed request names the five schemas it could
  not reach, and the public `DELETE /api/v1/me` endpoint the contract document implies is not in the
  frozen OpenAPI yet — it needs a contract change, so the worker is driven by CLI for now.
- Key rotation re-wraps one row at a time through the repository; there is no bulk rotation command.
- Travel-mode coverage is a flat configured list, not per region. The contract's 422 anticipates
  "no coverage *in that region*", which needs module 04's provider registry. Still outstanding
  after phase 5: the registry is module 04's to expose. Today a mode is supported everywhere or
  nowhere.
- `GET /api/v1/locations/search` needs module 04 running and `INTERNAL_SERVICE_TOKEN` set. Without
  either it returns 503 `DEPENDENCY_UNAVAILABLE` — never an empty result list, because "nothing
  matched" and "search is down" lead a traveller to do different things.
- **Module 03 does not exist yet.** The agent client, the state machine, the SSE bridge and the
  recommendation gate are all implemented and tested, but no agent has ever answered them. Until
  `services/agent` serves `/internal/v1/runs`, every real assessment ends as a `FAILED` run with
  `DEPENDENCY_UNAVAILABLE` — correctly, and visibly, rather than with an invented verdict. The
  same applies to module 08 and the recommendation fetch.
- Nothing publishes `run.progress` yet. This service writes `run.accepted` and the terminal event;
  the stages in between are module 03's to publish to the same Redis stream. A stream with only
  those two events is what a client sees today.
- `POST /internal/v1/runs/{id}/resume` is not called. Resuming a `NEEDS_INPUT` run is phase 6,
  with conversations; the state machine already permits the transition.
- Cancellation is best effort outward. The run is marked `CANCELLED` here whether or not the agent
  can be told, so a cancellation never blocks on an unreachable service — but the agent may keep
  working until it notices.
- The SSE per-user stream cap fails open when Redis is unavailable. A Redis blip must not cost
  every client its progress reporting; the trade is that the cap is not enforced during one.
- `GET /api/v1/recommendations/{id}` does not exist — phase 6. Phase 5 exposes the recommendation's
  *id* once validated, and validates the top level of the object plus its provenance; the nested
  route, alert and contact entities are modelled in phase 6, where they are actually served.
- No rate limiting yet, although Redis is already required and probed. Phase 7.
- A token stays valid until it expires. Disabling an account takes effect immediately because the
  local row is checked on every request, but there is no token introspection or revocation list.
- The realm at `infra/keycloak/` is for local development and enables a direct-grant test client.
  See that folder's README before using it anywhere else.
- `infra/postgres/init/00-schemas.sql` creates `api` but not `identity` or `travel`. The migration
  creates them itself, so a fresh or existing database both work; the init script is a shared
  surface and reconciling it is an infra PR.
