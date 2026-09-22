# Smart Travel Assistant web

Traveler-facing Next.js 16 application for Smart Travel Assistant. It uses React
19, HeroUI 3, Tailwind CSS 4, and will communicate only with the public API.

## Phase 1

The responsive application shell, route boundaries, visual tokens, runtime public
environment validation, testing configuration, and a production standalone Docker
image are in place. The visible application routes are deliberately empty states:
they do not contain mock travel conditions, contacts, or recommendations.

Implemented routes:

- `/login`
- `/dashboard`
- `/trips/new`
- `/trips/[tripId]`
- `/trips/[tripId]/compare`
- `/safety-map`
- `/assistant/[conversationId]`
- `/emergency`
- `/api/health`

Phase 2 adds Auth.js Keycloak PKCE login, protected routes, application sign-out,
the real `/me` profile, a typed public API client, SSE and shared data states.
Later phases add live maps and feature vertical slices. See [`screen-inventory.md`](docs/screen-inventory.md) for the
screen, interaction, and contract inventory.

## Phase 2 configuration and boundaries

Copy `.env.example` to `.env.local`, generate `AUTH_SECRET` locally, and configure
`AUTH_URL`, `AUTH_KEYCLOAK_ISSUER`, and server-only `API_BASE_URL`. The existing
`web` Keycloak client is public and uses PKCE; it needs no client secret. Request
scope is `openid profile email travel`. Callback: `/api/auth/callback/keycloak`.
Use HTTPS in production: session cookies are Secure there and always HttpOnly,
SameSite=Lax. Never put OAuth credentials in `NEXT_PUBLIC_` settings.

In Docker, the browser and API must agree on the canonical OIDC issuer. Set
`AUTH_KEYCLOAK_INTERNAL_ORIGIN=http://keycloak:8080` only when Next.js needs a
different transport address; it preserves the public Host/issuer. Configure the
API's `OIDC_ISSUER` consistently. Root Compose files are intentionally unchanged;
pass server settings through your local web environment or an explicit override.

Browser calls go through `/api/backend/api/v1/*`. This route validates the
encrypted session, rejects cross-origin mutations, adds bearer/correlation
headers, propagates cancellation, and refreshes once on expiry/401. OAuth tokens
never appear in the public session endpoint or localStorage. Refresh failure
clears the app cookie. Sign-out ends the application session; the identity
provider's separate SSO session is governed by Keycloak. Refresh coalescing is
process-local: deploy one web replica until a shared token vault/lock is agreed
with the API owner (the realm uses single-use refresh tokens).

`proxy.ts` (Next.js 16's middleware convention) protects dashboard, trip, map,
and assistant routes. API authorization is enforced independently. Emergency
stays reachable when signed out; protected emergency APIs still require login.

`pnpm generate:api` regenerates the checked-in consumer types from the shared
bundled OpenAPI without modifying `packages/contracts`. `pnpm check:api` detects
drift. The typed `api` client accepts AbortSignal; create one `createSubmission`
per user intent and pass its key as `Idempotency-Key` on mutations. Queries use
zero stale time unless a caller derives it from server `expires_at` with
`freshnessStaleTime`. Only network/temporary 5xx reads retry (at most twice);
4xx and mutations do not. Retry-After is respected for retryable responses.

`useRunEvents(requestId)` exposes event/connection/error/cancel. Its fetch stream
resumes with Last-Event-ID, deduplicates replay, checks heartbeat silence, backs
off up to five reconnects, and closes on completion/failure/needs-input, cancel,
run change or unmount. Cancellation stops observation, not the server's run.
`DataFreshness`, `SourceList`, `DegradedBanner`, `RiskBadge`, `ActionBadge`,
`DataSkeleton`, `EmptyState`, and `ErrorState` preserve missing/unknown values;
they never derive a final action from a risk level.

## Docker Phase 2 verification

From the repository root:

```bash
node apps/web/scripts/test-docker.mjs
```

The isolated `smart-travel-web-phase2` project runs lint/typecheck/Vitest in the
web image, then real browser OIDC/profile/logout and navigation tests against
Keycloak, API, PostgreSQL, and Redis. It uses random credentials, temporary test
users and a separate in-memory test database, no host ports and no existing data
volumes. It removes only its own containers on exit. Browser dependency/results
volumes remain reusable. Test traces are disabled to avoid recording credentials.
Unit protocol tests construct synthetic control/error frames; they contain no
provider facts and are never imported by the runtime. No runtime mocks exist.

## Local development

Node.js 22.22+ and pnpm are required.

```bash
cd apps/web
cp .env.example .env
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

`NEXT_PUBLIC_API_BASE_URL` must point to the public API. Map configuration is
optional until the MapLibre feature is implemented. Do not use `NEXT_PUBLIC_` for
secrets.

## Verification

```bash
corepack pnpm lint
corepack pnpm typecheck
corepack pnpm test
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 corepack pnpm build
docker build --tag smart-travel-web:local apps/web
```

The Docker image runs Next standalone output as the non-root `app` user. Its
healthcheck calls `GET /api/health`, which is a web-process liveness endpoint and
does not mask public API readiness.
