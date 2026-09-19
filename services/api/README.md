# `services/api/`

**เจ้าของ:** คนที่ 2 · 02-api

The public trust boundary. The browser reaches `web` and this service and nothing else, so every
capability a user has passes through here: authentication, ownership, validation, rate limiting,
idempotency, and the orchestration of an assessment.

Plan: [`IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md)
Contract: [`packages/contracts/openapi/public-api.yaml`](../../packages/contracts/openapi/public-api.yaml)

## What exists today

Phase 1 of the plan: the scaffold everything else is built on.

| Area | State |
| --- | --- |
| App factory, settings validation, lifespan | Done |
| Middleware chain (security headers, size limit, correlation, CORS, access log) | Done |
| `/health/live`, `/health/ready`, `/metrics` | Done |
| Error handling — every failure becomes the contract envelope | Done |
| SQLAlchemy engine, session scope, Alembic per schema | Done |
| Docker: multi-stage, non-root, healthcheck, compose wiring | Done |
| OIDC token verification | Phase 2 — **not implemented** |
| `/api/v1/**` endpoints | Phases 3–6 — **not implemented** |

There is no authentication yet, and no placeholder pretending to be authentication: a stub that
returns a user is indistinguishable from working auth until someone deploys it. The middleware
chain leaves the slot open and phase 2 fills it.

**Readiness is currently red** on a fresh stack, and correctly so. It requires the OIDC discovery
document, and the `smart-travel` realm does not exist until phase 2 imports it. Liveness is green,
the container is healthy, and everything else works — see *Health* below.

## Run it

```bash
# from the repository root, with .env filled in (see .env.example)
docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app run --rm api alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app up -d --wait api

curl -fsS http://localhost:8000/health/live
curl -sS  http://localhost:8000/health/ready    # 503 until the Keycloak realm exists
curl -fsS http://localhost:8000/metrics | head
```

Locally, without Docker:

```bash
cd services/api
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest                      # integration tests skip themselves without Docker
uv run pytest -m integration       # migrations against a throwaway PostGIS container
```

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

## Layout

```text
app/
├─ main.py            app factory and lifespan; middleware order is documented there
├─ settings.py        every environment value, validated at startup
├─ api/               routers (health today; /api/v1 from phase 3)
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
| `identity` | Profiles, consent records, emergency profiles |
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

- No authentication, so no endpoint is protected yet. Phase 2.
- Readiness is red until the Keycloak realm is imported. Phase 2.
- No rate limiting yet, although Redis is already required and probed. Phase 7.
- `infra/postgres/init/00-schemas.sql` creates `api` but not `identity` or `travel`. The migration
  creates them itself, so a fresh or existing database both work; the init script is a shared
  surface and reconciling it is an infra PR.
