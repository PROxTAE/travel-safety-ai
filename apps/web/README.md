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
Phase 3 adds the real trip-planner vertical slice described below. See
[`screen-inventory.md`](docs/screen-inventory.md) for the screen, interaction,
and contract inventory.

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
API's `OIDC_ISSUER` consistently. The shared development override supplies these
settings for the normal local stack; other environments must provide equivalents.

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

## Phase 3 trip planner

`/trips/new` searches the authenticated public geocoding endpoint after a 400 ms
debounce, cancels superseded searches, supports keyboard selection, and requires
the traveller to confirm both provider pins on the interactive MapLibre preview.
The RHF form validates wall-clock dates with Zod in the selected IANA timezone;
it never silently interprets trip dates in the browser timezone.

Submitting creates a persisted trip (or PATCHes an existing trip with its
revision ETag), starts an idempotent assessment, follows progress over authenticated
SSE, and fetches the completed recommendation. Route geometry, metrics, risk,
quality, sources, and freshness are rendered only from that server response. A
missing route is shown as unavailable rather than filled with a sample option.

Map tiles are optional configuration because no unrestricted default provider is
assumed. Without `NEXT_PUBLIC_MAP_TILE_URL`, MapLibre remains interactive and
shows confirmed coordinates and server route geometry over the supplied
illustrated world-map fallback with an explicit configuration notice. The
illustration is presentation only and is never used as geographic data. Tile
URLs may contain a `{token}` placeholder resolved from
`NEXT_PUBLIC_MAP_TILE_TOKEN`. Set `NEXT_PUBLIC_MAP_TILE_ATTRIBUTION` to the
visible attribution required by the selected provider. All three settings are
browser-visible and must not contain a server-side secret.

The current repository does not yet contain an M03 Agent runtime service. The
real API therefore persists the trip/run and returns a terminal dependency error
after assessment submission; the final login-to-route-options acceptance path is
blocked until M03 and its downstream recommendation pipeline are runnable.

## Docker module verification

From the repository root:

```bash
node apps/web/scripts/test-docker.mjs
```

The isolated `smart-travel-web-phase2` project runs contract drift, lint,
typecheck, and Vitest in the web image, then browser tests against real Keycloak,
API, PostgreSQL, Redis, and Open-Meteo geocoding through the external-data
service. The Phase 3 browser check confirms real persisted trip/run behavior and
the honest M03 dependency error. It uses random credentials, temporary test
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

`NEXT_PUBLIC_API_BASE_URL` must point to the public API. Map tile configuration
is optional; without it the interactive confirmation/route layers use the
supplied illustrated world-map fallback. Configure the provider's required
visible attribution with `NEXT_PUBLIC_MAP_TILE_ATTRIBUTION`. Do not use
`NEXT_PUBLIC_` for secrets.

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
