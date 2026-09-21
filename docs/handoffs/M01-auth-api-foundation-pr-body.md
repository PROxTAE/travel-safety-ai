# [M01] Add Phase 2 auth and API foundation

## Summary

Adds the Phase 2 web authentication and API foundation: real Auth.js/Keycloak PKCE login, protected routes, encrypted HttpOnly sessions, refresh/logout behavior, a same-origin authenticated API/SSE boundary, generated API types, bounded query/transport policies, SSE lifecycle support, and shared data states. It also makes the normal development Compose stack capable of exercising the same real OIDC/M02 profile flow as the isolated acceptance stack.

## Scope

In scope:

- Auth.js Keycloak OIDC login, callback, protected routes, safe return URLs, session refresh, and logout.
- Server-only OAuth token storage and same-origin authenticated API/SSE proxy.
- Generated public API types and drift check.
- Correlation/request IDs, timeout, cancellation, stable errors, idempotent duplicate-submit handling, and Query defaults.
- SSE parsing, replay, reconnect, heartbeat watchdog, terminal handling, cancellation, and unmount cleanup.
- Shared freshness/source/degraded/risk/action/loading/empty/error/connectivity components.
- Unit/component/auth/SSE tests and real Docker Keycloak/API Playwright tests.
- Shared development-stack OIDC/API configuration in `compose.dev.yaml` and `AUTH_SECRET` documentation in `.env.example`.

Out of scope:

- Phase 3 trip planner/assessment/recommendation UI.
- Keycloak custom theme, registration, or committed demo credentials.
- Full visual, axe, localization, load, vulnerability, and release verification.

## Ownership and dependencies

- Module/owner: M01 Web application.
- Depends on PR/contract: M02 public API 1.0.0 and existing Keycloak realm/client; rebased onto `origin/main@fe703f2`.
- Downstream consumers: later M01 slices use `lib/api`, `useRunEvents`, and shared data-state components.
- Issue/ADR: Phase 2 of `IMPLEMENTATION_PLANS/01_WEB_APP_IMPLEMENTATION.md`; no new ADR.

## Contract, database and configuration changes

- API/OpenAPI/JSON Schema: no producer contract change. Checked-in TypeScript was regenerated after rebase and `check:api` passes against the current bundled public OpenAPI.
- Migration/table/index: no M01 migration. Development API now runs existing M02 `alembic upgrade head` before Uvicorn so a healthy process cannot serve without required profile tables.
- Environment variables: documents `AUTH_SECRET`; dev web receives `AUTH_URL`, `AUTH_TRUST_HOST`, `AUTH_KEYCLOAK_ID`, `AUTH_KEYCLOAK_ISSUER`, `AUTH_KEYCLOAK_INTERNAL_ORIGIN`, and `API_BASE_URL`.
- Backward compatibility/rollout: existing public/emergency routes remain available; missing auth config fails closed with sign-in unavailable.

Shared development-stack rationale:

- The previous web container received only `NEXT_PUBLIC_API_BASE_URL`, so Auth.js could not start a real login.
- Browser `localhost` and Docker `keycloak` produced different OIDC issuers. `keycloak.localhost` is now the canonical dev issuer and a Docker network alias, so Keycloak, Auth.js, and M02 validate the same `iss` value.
- The API health endpoint could pass before M02 tables existed. Dev startup now applies the existing migrations first.
- The fixes preserve named volumes and persistent data; no `down -v`, database reset, or volume recreation is required.

## Real data and provenance

- Provider/source: self-hosted Keycloak 26 and M02 API.
- Endpoint/coverage: real OIDC discovery/auth/token/callback/logout and real `GET /api/v1/me`.
- License/attribution: N/A — internal/self-hosted services.
- Freshness/TTL: provider token expiry; Auth.js encrypted session max age 10 hours.
- Failure/degraded behavior: stable 401/session clearing, bounded retry, sign-in unavailable UI, public emergency route.
- Runtime/demo has no mock or hard-coded current data: [x]

## How to run

```bash
# Normal development stack
cp .env.example .env
# Fill required secrets, including AUTH_SECRET, POSTGRES_PASSWORD, and Keycloak admin password.
docker compose -f compose.yaml -f compose.dev.yaml --profile app up -d --wait --wait-timeout 300

# Complete isolated Phase 2 verification
node apps/web/scripts/test-docker.mjs
```

## Verification evidence

Commands and results:

```text
command: git fetch origin && git rebase origin/main
result: successfully rebased onto fe703f24777fd9c76cec30bb0dfe463ffec189dc

command: node apps/web/scripts/generate-api.mjs --check
result before regeneration: failed as expected because origin/main changed the public contract
result after regeneration: passed

command: node apps/web/scripts/test-docker.mjs
result:
  check:api: passed
  lint: passed
  typecheck: passed
  Vitest: 7 files passed, 34 tests passed, 0 failed, 0 skipped (12.35s)
  integration readiness: Postgres, Redis, Keycloak, API, web healthy
  Playwright: 4 passed, 0 failed, 0 skipped (1.7m)
```

Final browser output:

```text
✓ real profile, HttpOnly session, and logout (52.9s)
✓ mobile navigation and page actions (21.9s)
✓ mobile keyboard activation (8.5s)
✓ desktop sidebar interaction (10.0s)
4 passed (1.7m)
```

- UI screenshots/video: N/A — no screenshot artifact committed; semantic and responsive browser assertions passed.
- Sanitized curl/trace/request IDs: real `/api/v1/me` returned 200; identifiers intentionally omitted from the PR body.
- Visual diff/accessibility result: keyboard interaction passed; full visual/axe verification is Phase 8.
- Migration up/down result: isolated empty database upgraded to head; no destructive downgrade in this web slice.

## Safety, security and privacy

- [x] Input and return URLs validated at the boundary.
- [x] Timeout/cancellation/retry/idempotency handled.
- [x] No secret, token, PII, or exact location leaked to committed logs/fixtures.
- [x] Provenance/freshness/quality fields retained by shared UI.
- [x] N/A — no official-warning policy changed.
- [x] N/A — no LLM/provider/RAG text introduced.
- [x] Auth/session ownership enforced; public emergency access preserved.
- [x] Stable errors do not expose arbitrary upstream details.

## Test coverage

- [x] Success path.
- [x] Invalid/unauthorized path.
- [x] Dependency timeout/429/5xx mapping and bounded retry.
- [x] Stale/partial data UI states.
- [x] Boundary/regression cases, including insecure-origin secure UUID fallback.
- [x] Contract test with current producer schema through generated-client drift check.
- [x] Real Keycloak/API E2E.

## Risks and limitations

- Users must currently be provisioned in Keycloak; self-registration and a custom theme are not included.
- The login page’s “Continue to trip planning” CTA still targets a protected route and returns unauthenticated users to login. A follow-up should initiate sign-in with `/trips/new` as callback.
- Agent-dependent assessment progress is intentionally not exercised until Phase 3; M02 reports the absent agent as an optional readiness warning.
- Formal dependency, image, and secret scans are expected from CI.

## Rollback

- Code rollback: revert the M01 commit and rebuild the previous web image.
- Database/schema rollback or forward-fix: no M01 schema; do not delete volumes. Follow M02 migration compatibility guidance if API rollback is required.
- Feature flag/provider disable path: remove/omit Auth.js runtime configuration to fail closed with sign-in unavailable while public emergency access remains.

## Handoff

- Completion report: `docs/handoffs/M01-auth-api-foundation.md`.
- What the next owner must do: Phase 3 should consume the typed client, BFF, `useRunEvents`, and shared data-state components; M03 real progress remains the downstream integration dependency.
- Reviewer focus areas: encrypted server-only token lifecycle, one-time refresh/replay behavior, origin/return-URL enforcement, SSE cancellation/replay, and the disclosed shared `compose.dev.yaml` issuer/migration changes.
