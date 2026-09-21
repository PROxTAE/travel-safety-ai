# [M01] Auth and API Foundation Completion Report

## 1. Metadata

| Field                                          | Value                                                                                                 |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Module/owner                                   | M01 Web application                                                                                   |
| Issue/PR                                       | Phase 2 — Auth and API foundation; PR not yet opened                                                  |
| Branch                                         | `feat/01-auth-api-client`                                                                             |
| Base/final commit SHA                          | `fe703f24777fd9c76cec30bb0dfe463ffec189dc` / `HEAD`                                                   |
| Date/time/timezone                             | 2026-09-22 02:35 +07 (Asia/Bangkok)                                                                   |
| Reviewers                                      | Web owner, M02 API owner, shared-infrastructure reviewer                                              |
| Contract version                               | Public API `1.0.0`, generated after rebase on `fe703f2`                                               |
| Docker image digest/tag                        | `smart-travel-web:phase2` / `sha256:be43d0237c47ddc58934fd70c1d31b665c531fda71f723ccaf2f1e822d1987f5` |
| Related model/policy/prompt/collection version | N/A — no model, policy, prompt, or collection change                                                  |

## 2. Executive summary

Phase 2 adds real Auth.js OIDC authorization-code + PKCE login through Keycloak, protected routes, encrypted HttpOnly sessions, token refresh, logout, and a same-origin BFF boundary. It adds a generated OpenAPI client with correlation IDs, timeouts, cancellation, stable error mapping, retry/freshness defaults, and duplicate-submit protection. The SSE transport supports parsing, replay, reconnect, heartbeat timeouts, terminal events, explicit cancellation, and unmount cleanup. Shared freshness, source, degraded, risk/action, loading, empty, error, connection-state UI is available for later slices. Real Keycloak and M02 `/api/v1/me` were exercised in Docker; browser tokens are not stored in localStorage or returned by the public session endpoint. The shared development override was completed so the same OIDC/API flow works at `http://localhost:3000`. The slice is ready for review and merge, but not for product release because later web phases remain out of scope.

## 3. Original responsibility and acceptance criteria

- [x] Auth.js OIDC to Keycloak, protected-route middleware, and sign-out — unit and real-browser auth tests.
- [x] Generated OpenAPI client with correlation header, timeout, `AbortSignal`, and stable errors — `tests/api-client.test.ts`.
- [x] Query defaults retry only safe/transient failures, use freshness-derived stale time, and do not retry 4xx — `tests/api-client.test.ts`.
- [x] `useRunEvents` supports reconnect, `Last-Event-ID`, heartbeat, explicit cancel, and unmount — `tests/run-events.test.ts` and `tests/use-run-events.test.tsx`.
- [x] Shared sourced-data and loading/empty/error UI states — `components/ui/data-states.tsx` and component tests.
- [x] Redirect, 401 refresh/logout, duplicate submit, and aborted request coverage — 34 Docker unit tests plus real browser logout.
- [x] Exit: real login and real profile — isolated Keycloak/API Playwright test passed.
- [x] Exit: no localStorage token — browser assertion passed; public session is token-free.
- [x] Exit: SSE tests pass — parser/replay/reconnect/heartbeat/cancel tests passed.

Scope extension approved during verification: `.env.example` and `compose.dev.yaml` were updated because the normal shared development stack could not execute the real Phase 2 flow. No Phase 3 feature was started.

## 4. What was implemented

### Features

| Feature              | Behavior now                                                                             | Entry point                                                      | Status   |
| -------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | -------- |
| OIDC authentication  | Keycloak authorization-code + PKCE; encrypted HttpOnly JWT session                       | `/login`, `/api/auth/*`                                          | Complete |
| Route protection     | Authenticated app routes redirect safely to login; emergency remains public              | `proxy.ts`                                                       | Complete |
| Backend-for-frontend | Server session supplies bearer token; refresh once on expiry/401; clears invalid session | `/api/backend/*`                                                 | Complete |
| API transport        | Generated types, correlation/request IDs, timeout, abort, stable errors, idempotency     | `lib/api/*`                                                      | Complete |
| Query policy         | Bounded transient retry and freshness-driven staleness                                   | `lib/api/query.ts`                                               | Complete |
| Run events           | SSE parse/replay/reconnect/watchdog/cancel lifecycle                                     | `lib/api/run-events.ts`, `features/assessment/use-run-events.ts` | Complete |
| Shared data states   | Freshness, sources, degradation, badges, skeleton/empty/error                            | `components/ui/*`                                                | Complete |
| Docker acceptance    | Isolated real Keycloak/API/web browser suite                                             | `scripts/test-docker.mjs`                                        | Complete |
| Shared dev flow      | Canonical host/container issuer, web server env, API migrate-before-serve                | `compose.dev.yaml`, `.env.example`                               | Complete |

### Important flows

```text
Browser /dashboard -> safe /login redirect -> Keycloak PKCE -> Auth.js callback
-> encrypted HttpOnly session -> same-origin /api/backend/api/v1/me
-> bearer token added server-side -> M02 profile -> rendered profile
```

```text
API 401/expired access token -> server-side refresh token exchange -> one replay
-> updated HttpOnly session; failed refresh/replayed 401 -> clear session -> stable 401
```

```text
SSE run URL -> authenticated BFF stream -> parse contract frames -> remember event ID
-> reconnect with Last-Event-ID after EOF/heartbeat timeout -> stop on terminal event/cancel/unmount
```

### What is explicitly not implemented

- Trip creation, assessment progress UI, route recommendations, comparison, and apply flow (Phase 3+).
- Custom Keycloak theme, user self-registration, or a committed demo user.
- Full visual-regression, axe, 200% zoom, localization, load, image scan, and release checks (later phases/CI).

## 5. Actual architecture and code design

### Folder/file map

| Path                                          | Purpose                                                                 | Important owner/consumer |
| --------------------------------------------- | ----------------------------------------------------------------------- | ------------------------ |
| `apps/web/lib/auth.ts`                        | Auth.js provider/session policy                                         | M01                      |
| `apps/web/lib/auth/*`                         | Safe return URL, session encode/decode/refresh, Keycloak internal fetch | M01/M02                  |
| `apps/web/app/api/backend/[...path]/route.ts` | Same-origin authenticated API/SSE proxy                                 | Browser/M02              |
| `apps/web/lib/api/*`                          | Generated types, API transport, query defaults, SSE                     | M01 Phase 2+ consumers   |
| `apps/web/components/ui/*`                    | Shared data and connectivity states                                     | All later web slices     |
| `apps/web/tests/*`                            | Unit/component/auth/SSE regression coverage                             | M01 reviewers            |
| `apps/web/compose.phase2-test.yaml`           | Isolated real integration environment                                   | M01/CI                   |
| `compose.dev.yaml`                            | Normal host development integration                                     | All local developers     |

### Main components/classes/functions

| Symbol                      | Responsibility                       | Inputs/outputs                                 | Design notes                                   |
| --------------------------- | ------------------------------------ | ---------------------------------------------- | ---------------------------------------------- |
| `auth`, `signIn`, `signOut` | OIDC and encrypted session lifecycle | Keycloak code/tokens -> HttpOnly session       | Public session omits OAuth tokens              |
| backend catch-all handlers  | Authenticate, refresh, proxy, stream | Browser request -> M02 response                | Rejects anonymous/cross-origin mutation        |
| `createApiClient`           | Typed request defaults and errors    | Generated operation + signal -> typed response | No browser bearer token                        |
| `createSubmission`          | Coalesce duplicate mutations         | mutation function -> stable in-flight/result   | Reuses idempotency key after retriable failure |
| `consumeRunEvents`          | SSE lifecycle                        | run ID, signal, callback -> terminal/cancel    | Deduplicates replayed event IDs                |
| `useRunEvents`              | React lifecycle wrapper              | run ID -> connection/events/cancel             | Aborts old run and unmount                     |

### Decisions/trade-offs

- Decision: credentials are entered only on Keycloak, not collected by the web application. Alternative password/direct-grant flow was rejected because it expands credential exposure and weakens OIDC/MFA/SSO behavior.
- Decision: OAuth tokens remain server-side in an encrypted HttpOnly session. Consequence: browser API traffic uses the same-origin BFF.
- Decision: `keycloak.localhost` is the development canonical issuer. It resolves to host loopback for the browser and is a Docker network alias for containers, keeping token issuer validation identical in Auth.js and M02.
- Decision: checked-in generated TypeScript is drift-checked. The post-rebase contract changed earthquake depth documentation; types were regenerated before verification.
- Technical debt: login still exposes an old “Continue to trip planning” CTA that points at a protected route and therefore returns unauthenticated users to login. Replace it with a sign-in action carrying `/trips/new` as callback in a follow-up UX slice.

## 6. API, contract and event changes

| Producer | Method/path/event              | Request schema              | Response schema                | Consumer          | Compatibility                         |
| -------- | ------------------------------ | --------------------------- | ------------------------------ | ----------------- | ------------------------------------- |
| M02 API  | `GET /api/v1/me`               | Bearer token                | `ApiResponse_UserProfile_`     | Web profile       | Existing contract; no producer change |
| M02 API  | `/api/v1/runs/{id}/events` SSE | `Last-Event-ID`             | run progress/terminal events   | Web SSE transport | Existing contract                     |
| Web BFF  | `/api/backend/{path}`          | Same-origin browser request | M02 response/stable auth error | Browser           | New internal web boundary             |

- Generated client command/result: `node apps/web/scripts/generate-api.mjs --check` — passed in Docker after regeneration on `origin/main@fe703f2`.
- Contract lint/breaking check result: consumer drift check passed; this PR does not modify source OpenAPI/JSON Schema.
- Deprecation/migration plan: N/A — no public contract change.
- Sanitized request/response example location: real profile behavior asserted in `apps/web/tests/e2e/auth.spec.ts`.

## 7. Database, cache and storage changes

### Migrations

| Revision | Schema/table/index  | Upgrade                                          | Downgrade/forward fix | Data impact     |
| -------- | ------------------- | ------------------------------------------------ | --------------------- | --------------- |
| N/A      | No M01-owned schema | Existing M02 migrations run before API dev serve | Follow M02 runbook    | No new M01 data |

- Empty DB -> head result: passed in isolated stack before real profile E2E.
- Previous main -> head result: normal preserved development database upgraded using existing M02 migrations; no reset.
- Restart persistence result: normal stack healthy with original PostgreSQL volume retained.
- Backup/restore result: N/A for this web slice; owned by M02/shared infrastructure.
- Retention/cleanup behavior: temporary E2E Keycloak users are deleted in fixture cleanup.
- Encryption/access control: Auth.js session encrypted and HttpOnly; no OAuth token in localStorage/public session.

### Redis/Qdrant/artifact changes

- N/A — no key, collection, model artifact, or retention change.

## 8. External providers and real data

| Provider/source | Endpoint/capability              | Coverage                                   | Credential ref                | Freshness/TTL                               | License/attribution        | Last canary |
| --------------- | -------------------------------- | ------------------------------------------ | ----------------------------- | ------------------------------------------- | -------------------------- | ----------- |
| Keycloak 26     | OIDC discovery/auth/token/logout | Real isolated + localhost development flow | Local `.env`; never committed | Session max 10h; token expiry from provider | Self-hosted infrastructure | 2026-09-22  |
| M02 API         | Real `/api/v1/me`                | Real Docker E2E                            | OIDC access token server-side | Server response contract                    | Internal service           | 2026-09-22  |

- Runtime/demo has no mock or hard-coded current data: [x]
- Test fixture source/captured_at/redaction/license: temporary synthetic identity created in isolated Keycloak and deleted; no captured provider fixture.
- Unsupported/unavailable behavior: stable auth/API error state; emergency route remains public.
- Schema drift/quota/failover: generated-client drift fails the Docker check; Keycloak/API readiness gates block E2E startup.

## 9. Configuration and Docker

### Environment variables added/changed

| Variable                        | Required             | Secret | Default/example                                          | Used by      | Failure if missing                                      |
| ------------------------------- | -------------------- | ------ | -------------------------------------------------------- | ------------ | ------------------------------------------------------- |
| `AUTH_SECRET`                   | Yes for auth         | Yes    | empty in examples                                        | Auth.js/BFF  | Sign-in unavailable / Compose rejects normal dev config |
| `AUTH_URL`                      | Yes in deployment    | No     | `http://localhost:3000` dev                              | Auth.js      | Incorrect callbacks/host validation                     |
| `AUTH_TRUST_HOST`               | Dev/proxy dependent  | No     | `true` dev                                               | Auth.js      | Host may be rejected                                    |
| `AUTH_KEYCLOAK_ID`              | Yes                  | No     | `web`                                                    | Auth.js      | Wrong OIDC client                                       |
| `AUTH_KEYCLOAK_SECRET`          | No for public PKCE   | Yes    | empty                                                    | Auth.js      | N/A for public client                                   |
| `AUTH_KEYCLOAK_ISSUER`          | Yes                  | No     | `http://keycloak.localhost:8080/realms/smart-travel` dev | Auth.js      | Discovery/login unavailable                             |
| `AUTH_KEYCLOAK_INTERNAL_ORIGIN` | Container deployment | No     | `http://keycloak:8080`                                   | Server fetch | Container cannot reach host-facing issuer directly      |
| `API_BASE_URL`                  | Yes                  | No     | `http://api:8000`                                        | BFF          | Backend calls fail closed                               |

Shared development-stack changes:

- `compose.dev.yaml` supplies all server-only web auth/API variables; previously the web container only received the public API URL and could not enable sign-in.
- Keycloak receives canonical hostname `keycloak.localhost` and the Docker network alias; M02 and Auth.js use the same issuer, avoiding host `localhost` versus container `keycloak` issuer rejection.
- The dev API runs `alembic upgrade head` before Uvicorn; previously health could pass while profile tables were absent, causing real `/me` requests to return 500.
- `.env.example` documents required local `AUTH_SECRET`; the actual generated secret remains only in ignored `.env`.
- The existing PostgreSQL and web dependency volumes were repaired in place. No volume was deleted or recreated.

### Run commands

```bash
docker compose -f compose.yaml -f compose.dev.yaml --profile app up -d --wait --wait-timeout 300
node apps/web/scripts/test-docker.mjs
```

- Container user: web production image uses non-root `app`; development image uses `node`.
- Ports/networks/volumes: normal dev publishes 3000/8000/8080 and uses persistent named volumes; isolated tests publish no ports and use an isolated project.
- Health/readiness behavior: Compose waits for Postgres, Redis, Keycloak, API, and web health before Playwright.
- CPU/RAM/disk measured: not measured in Phase 2.
- Image size/digest: digest recorded above; size not measured.

## 10. Tests and verification

| Test type            | Command                                                                 |                                           Passed | Failed | Skipped | Evidence                                                  |
| -------------------- | ----------------------------------------------------------------------- | -----------------------------------------------: | -----: | ------: | --------------------------------------------------------- |
| Lint/type            | `node apps/web/scripts/test-docker.mjs` (`pnpm lint && pnpm typecheck`) |                                       2 commands |      0 |       0 | Final post-rebase Docker run                              |
| Unit/component       | same (`pnpm test`)                                                      |                               34 tests / 7 files |      0 |       0 | Vitest duration 12.35s                                    |
| Contract             | same (`pnpm check:api`)                                                 |                                    1 drift check |      0 |       0 | Generated types match rebased bundled OpenAPI             |
| Integration          | same (isolated health-gated Compose stack)                              |                      5 required services healthy |      0 |       0 | Postgres/Redis/Keycloak/API/web                           |
| E2E                  | same (Playwright Chromium)                                              |                                                4 |      0 |       0 | 1.7m; real profile/session/logout + responsive navigation |
| Security/privacy     | unit + E2E assertions                                                   | token/cookie/localStorage/auth boundaries passed |      0 |       0 | HttpOnly cookie and no public/browser token               |
| Accessibility/visual | keyboard navigation tests                                               |                          2 interaction scenarios |      0 |       0 | Full axe/visual deferred to Phase 8                       |
| Load/performance     | N/A                                                                     |                                                0 |      0 |       0 | Not required for Phase 2                                  |

### Scenarios verified

- Success: protected redirect, real PKCE login, real profile, logout, public emergency route.
- Invalid/unauthorized: anonymous BFF 401, unsafe return URL, cross-origin mutation, failed refresh, replayed 401.
- Timeout/429/5xx: stable mapper, request timeout/cancel, no 4xx retry, bounded transient retry.
- Stale/partial/conflicting: freshness and degraded/source components; no invented observed time.
- Cancellation/idempotency/concurrency: `AbortSignal`, duplicate-submit coalescing/key reuse, SSE cancellation/unmount/replay dedupe.
- Restart/rollback: isolated stack rebuilt from empty storage; normal stack preserved existing volumes.

Sanitized integration evidence: M02 `/api/v1/me` returned 200 during Playwright; no user credential, token, or raw subject is retained in this report.

## 11. UI evidence (if applicable)

| Screen/state/viewport                       | Reference           | Result screenshot                                       | Visual gap                   |
| ------------------------------------------- | ------------------- | ------------------------------------------------------- | ---------------------------- |
| Login/authenticated shell, Chromium desktop | Existing Phase 1 UI | Automated browser assertions; no new artifact committed | Keycloak uses standard theme |
| Mobile 390x844 interactions                 | Responsive shell    | Automated tap/keyboard assertions                       | Full visual diff deferred    |

- Keyboard/axe results: keyboard activation passed; axe not run in Phase 2.
- Thai/English/long text/200% zoom: not run; Phase 8.
- Loading/empty/error/degraded/offline: shared components unit-tested; full route matrix deferred.

## 12. Safety, security and privacy review

- [x] N/A — no official-warning priority logic changed.
- [x] N/A — no LLM/provider/RAG text introduced.
- [x] No secret, PII, exact location, or OAuth token committed/logged in fixtures.
- [x] Auth and session ownership enforced at protected routes and BFF.
- [x] Timeout/retry/cancel/idempotency bounded.
- [x] Source/freshness/quality fields preserved by shared UI.
- [x] Error/degraded behavior does not invent data.
- [ ] Formal dependency/image/secret scans not run locally; required CI checks remain reviewer evidence.

Finding resolved: browser-safe UUID generation now uses `crypto.getRandomValues` when `crypto.randomUUID` is unavailable on an insecure local HTTP origin.

## 13. Problems encountered and resolutions

| Problem                                              | Root cause                                      | Evidence                                                          | Resolution/workaround                                            | Remaining risk                                                        |
| ---------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------- |
| Profile never requested on Docker HTTP origin        | `crypto.randomUUID` unavailable                 | Browser diagnostics; no BFF request                               | Secure UUIDv4 fallback using `getRandomValues`                   | Unit regression included                                              |
| Local Keycloak/data-integration rejected DB password | Persistent role predated current `.env`         | PostgreSQL 28P01; matching config fingerprints                    | Rotated role credential in place; preserved volume               | Developers changing init-only credentials must rotate persisted roles |
| Local web restart loop                               | Named dependency volume lacked executable links | `sh: next: not found`                                             | Locked pnpm install repaired volume in place                     | Re-run locked install after dependency changes                        |
| Local OIDC issuer mismatch                           | Host and Docker used different issuer names     | Auth.js discovery issuer error                                    | Canonical `keycloak.localhost` + Docker alias                    | Assumes standard `.localhost` resolution                              |
| Local real profile returned 500                      | API dev command did not apply migrations        | Missing `identity.user_profiles`                                  | Migrate before dev serve                                         | Existing M02 migrations remain authoritative                          |
| First post-rebase E2E run: 3/4                       | URL-only logout assertion raced cold navigation | Browser reached login transiently; session boundary later cleared | Poll BFF for 401, then assert protected redirect; full rerun 4/4 | None observed                                                         |

## 14. Performance and operational behavior

| Metric     | Target                            | Actual p50/p95/max | Test condition                 | Pass |
| ---------- | --------------------------------- | ------------------ | ------------------------------ | ---- |
| Unit suite | deterministic                     | 12.35s total       | Docker, 34 tests               | Yes  |
| E2E suite  | complete within configured limits | 1.7m total         | Fresh isolated stack, Chromium | Yes  |

- Metrics/dashboard/alerts added: none.
- Log fields/redaction verified: correlation/request/trace propagation tested; tokens absent from responses.
- Circuit/rate/quota/cache behavior: bounded API/SSE retry; no provider quota introduced.
- Incident disable/rollback steps: remove/revert web auth deployment or return stable auth-unavailable UI; do not delete persistent volumes.

## 15. Known limitations and technical debt

| Limitation/debt                                     | User/safety impact                                        | Workaround                            | Owner       | Priority                | Follow-up issue                                |
| --------------------------------------------------- | --------------------------------------------------------- | ------------------------------------- | ----------- | ----------------------- | ---------------------------------------------- |
| Standard Keycloak login UI and no self-registration | User needs an administrator-created account               | Create user in Keycloak admin locally | M01/infra   | Medium                  | Registration/theme slice                       |
| Trip-planning CTA on login targets protected route  | Unauthenticated user returns to login and may be confused | Use Keycloak sign-in button first     | M01         | Medium                  | Change CTA to login with `/trips/new` callback |
| Agent absent in Phase 2 integration                 | API logs optional readiness warning                       | Phase 2 does not execute assessment   | M03/Phase 3 | Low for this PR         | Phase 3 integration                            |
| Full visual/axe/load/image scans deferred           | Non-functional gaps not fully measured                    | CI/later phases                       | M01/CI      | Required before release | Phase 8/9                                      |

## 16. Handoff to other members

| Recipient/module | What is ready                                          | What they must change/do                                    | Contract/config                     | Blocking?                       |
| ---------------- | ------------------------------------------------------ | ----------------------------------------------------------- | ----------------------------------- | ------------------------------- |
| M01 Phase 3      | Typed API/BFF/SSE/query/shared states                  | Build trip planner and assessment UI using these primitives | `apps/web/lib/api/*`                | No                              |
| M02 API          | Real profile and token validation integration verified | Keep bundled OpenAPI and issuer behavior compatible         | Public API 1.0.0                    | No                              |
| M03 Agent        | SSE consumer transport ready                           | Supply real assessment progress in Phase 3 environment      | Existing run events                 | Blocks Phase 3 E2E, not Phase 2 |
| Shared infra     | Normal dev OIDC/API flow documented                    | Review `compose.dev.yaml` shared-surface changes            | `AUTH_SECRET`, `keycloak.localhost` | Review required                 |

## 17. Commit and PR inventory

```text
HEAD feat(web): add Phase 2 auth and API foundation
```

- PR review comments resolved: N/A — PR not opened.
- Required checks status: local Docker contract/lint/type/unit/integration/E2E passed; CI scans pending.
- Rebased on main SHA: `fe703f24777fd9c76cec30bb0dfe463ffec189dc`.
- Squash title proposed: `[M01] Add Phase 2 auth and API foundation`.

## 18. Rollback and recovery

1. Feature disable: omit Auth.js server configuration to show sign-in unavailable; public emergency remains accessible.
2. Application rollback: revert the M01 commit and rebuild the prior web image.
3. Database rollback: no M01 migration. Do not delete volumes; use the M02 migration/runbook if API rollback requires a forward fix.
4. Model/policy/prompt/knowledge rollback: N/A.
5. Data/cache cleanup: remove only temporary test identities if a run is interrupted; preserve database and named volumes.
6. Verification after rollback: `/api/health`, public routes, previous shell tests, and Compose health.

## 19. Final declaration

- [x] Work in Phase 2 scope is complete according to the evidence.
- [x] No required Phase 2 work is hidden.
- [x] Documentation, env examples, generated contract consumer, and Docker configuration are updated.
- [x] Downstream handoff requirements are stated.
- [x] Ready for review/merge after required approvals and CI.
- [ ] Ready for release — later web phases and final non-functional verification remain.

Prepared by: M01 implementation agent

Reviewer: Pending

Date: 2026-09-22
