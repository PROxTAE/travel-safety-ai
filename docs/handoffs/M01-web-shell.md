# [M01] Phase 0–1 web shell completion report

This report covers only Phase 0 (contract and visual inventory) and Phase 1
(scaffold and design system) from
`IMPLEMENTATION_PLANS/01_WEB_APP_IMPLEMENTATION.md`. Phase 2 and later work is
explicitly excluded.

## 1. Metadata

| Field                                          | Value                                                                                                                                               |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Module/owner                                   | 01 — Web application                                                                                                                                |
| Issue/PR                                       | Not yet opened; proposed title: `[M01] Add responsive web shell and Phase 1 foundation`                                                             |
| Branch                                         | `feat/01-web-shell`                                                                                                                                 |
| Base/final commit SHA                          | Rebased onto `origin/main` `3353f158787f2d7df6b997ab8ff0aa209615e01c`; pre-revalidation branch head `80d7dafa61e99c4d2ce3a22377ff017a3107c952`      |
| Date/time/timezone                             | 2026-09-21, Asia/Bangkok (UTC+07:00)                                                                                                                |
| Reviewers                                      | Team Lead; M02 public API owner for the Phase 0 contract inventory                                                                                  |
| Contract version                               | Public API v1 as present at `3353f15`; shared source/generated artifacts unchanged by this branch                                                   |
| Docker image digest/tag                        | `smart-travel-web:phase1-contract-rebase`; local digest `sha256:031821102a7013ea054c2a0b4adc22100d9c1b92ee64733426f94bab0815649b`; 91,716,820 bytes |
| Related model/policy/prompt/collection version | N/A — no model, prompt, policy, or collection is used in Phases 0–1                                                                                 |

## 2. Executive summary

Phase 0 records the supplied screens, visible interactions, public API fields,
asset constraints, and later-phase ownership in a screen/contract inventory.
Phase 1 supplies a strict TypeScript Next.js 16 application, responsive desktop
and mobile shell, visual tokens, empty route boundaries, explicit unavailable
states, environment parsing, unit/E2E configuration, and a standalone non-root
Docker runtime. The browser does not call an API, provider, or mock service in
this slice. After rebasing onto the updated shared contract, the official
OpenAPI/schema/example checks, generated TypeScript parity check, M01 consumer
typecheck, lint, format, web typecheck, unit/component, production-build,
Compose, health, and shell E2E checks all passed inside Docker. This slice is
ready to merge, but the web application is not ready to release until Phase 2
and later slices add real authentication, API/SSE integration, live data, and
feature flows.

## 3. Original responsibility and acceptance criteria

### Phase 0 — contract and visual inventory

- [x] Reviewed shared context, public OpenAPI, and all seven supplied screen PNGs — `apps/web/docs/screen-inventory.md`.
- [x] Recorded visible elements, interactions, states, route ownership, and delivery phases — route inventory in the same document.
- [x] Recorded generated-client/auth/SSE decisions — generated contract is available; Auth.js callback and browser SSE authentication are explicitly deferred to Phase 2.
- [x] Checked `RecommendationResponse` fields — action, risk, routes, sources, freshness, limitations, and degraded services are present; no Phase 1 contract change was needed.
- [x] Rechecked the updated route/place contract — an unevaluated route has `exposure: null` and cannot be presented as open, while an emergency POI may have `name: null` and must remain renderable by type/distance. The M01 TypeScript consumer assertions compile without a web change.
- [x] Checked asset dimensions/alpha/font/licensing posture — source screen dimensions and RGBA assets recorded; no bundled font or explicit asset licence was found. Next Image negotiates AVIF/WebP while the supplied PNGs remain preserved.

### Phase 1 — scaffold and design system

- [x] Next.js App Router, React 19, strict TypeScript, and pnpm scaffold.
- [x] Tailwind CSS loads before HeroUI styles.
- [x] CSS tokens cover the supplied colour, spacing, radius, shadow, and type language.
- [x] `AppShell`, desktop sidebar, responsive mobile navigation, global loading, and global error boundary.
- [x] ESLint, Prettier, TypeScript, Vitest, Playwright, and bundle-analyzer configuration.
- [x] Public environment schema rejects missing/invalid API and map URLs; map configuration remains optional until its feature phase.
- [x] Standalone production Docker image, non-root runtime user, liveness endpoint, and Docker healthcheck.

Phase 1 exit evidence: every empty route compiled, the shell interaction suite
passed at mobile and desktop breakpoints, keyboard activation passed, the
container ran as uid 100 `app`, and Docker reported `healthy`.

Scope did not expand beyond Phases 0–1. No Phase 2 authentication, generated API
client, query cache, SSE client, or shared live-data component was added.

## 4. What was implemented

### Features

| Feature                   | Behavior now                                                                                      | Entry point                          | Status                              |
| ------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------ | ----------------------------------- |
| Screen/contract inventory | Maps supplied screens to routes, interactions, contract fields, and delivery phases               | `apps/web/docs/screen-inventory.md`  | Complete                            |
| Responsive app shell      | Desktop sidebar/header and mobile disclosure navigation with active-route state                   | `AppShell`                           | Complete for Phase 1                |
| Route boundaries          | Dashboard, trip, compare, safety map, assistant, and emergency render honest empty states         | `apps/web/app/(app)/**`              | Complete for Phase 1                |
| Login boundary            | Visual login shell clearly reports sign-in unavailable and leaves planning/emergency links usable | `apps/web/app/(auth)/login/page.tsx` | Complete for Phase 1; auth deferred |
| Environment schema        | Validates public API URL and optional public map settings                                         | `getPublicEnvironment`               | Complete for Phase 1                |
| Web liveness              | Returns a no-store process-liveness response without masking API readiness                        | `GET /api/health`                    | Complete                            |
| Docker runtime            | Multi-stage standalone image with non-root `app` user and healthcheck                             | `apps/web/Dockerfile`                | Complete                            |

### Important flows

```text
Browser route -> App Router layout -> responsive AppShell -> route placeholder
              -> explicit "No live data available" state -> optional Emergency link

GET /api/health -> Next route handler -> no-store JSON liveness response

Docker build -> frozen pnpm install -> next build -> standalone output
             -> runtime image owned by app -> node server.js -> healthcheck
```

The browser shell is the only client component because it uses `usePathname` for
active navigation. Root/layout pages, route pages, placeholders, and the health
handler remain server components or server route handlers.

### What is explicitly not implemented

- Phase 2 Auth.js/OIDC, protected-route middleware, generated API client, TanStack Query configuration, SSE, and shared freshness/risk/degraded components.
- Live trip, recommendation, map, assistant, emergency-directory, contact, weather, transport, or safety data.
- Forms, mutations, consent flows, geolocation, SOS state machine, or route application.
- Runtime mock mode, sample payload route, hard-coded current conditions, and client-side safety decisions.

## 5. Actual architecture and code design

### Folder/file map

| Path                                           | Purpose                                                                    | Important owner/consumer     |
| ---------------------------------------------- | -------------------------------------------------------------------------- | ---------------------------- |
| `apps/web/app/`                                | App Router layouts, pages, error/loading boundaries, health route          | M01                          |
| `apps/web/components/shell/`                   | Responsive navigation shell and route metadata                             | M01; all later feature pages |
| `apps/web/components/ui/route-placeholder.tsx` | Honest empty state shared by Phase 1 routes                                | M01                          |
| `apps/web/lib/env.ts`                          | Zod schema for browser-safe public configuration                           | M01; Phase 2 API/map clients |
| `apps/web/public/assets/`                      | Web copies of project-supplied branding, icons, mascots, and illustrations | M01 UI                       |
| `apps/web/tests/`                              | Environment, shell component, and navigation E2E tests                     | M01/reviewers                |
| `apps/web/docs/screen-inventory.md`            | Phase 0 screen/contract/state inventory                                    | M01, M02, later web slices   |
| `compose.yaml`, `compose.dev.yaml`             | Runtime and local-development web service wiring                           | Team Lead + M01              |

### Main components/classes/functions

| Symbol                 | Responsibility                                    | Inputs/outputs                                       | Design notes                                              |
| ---------------------- | ------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------- |
| `AppShell`             | Desktop/mobile shell and active navigation        | React children -> shell UI                           | Client component only because active state reads pathname |
| `navigationItems`      | One route/label/icon source for both nav variants | Static tuple -> links                                | No current-data values                                    |
| `RoutePlaceholder`     | Shared honest unavailable state                   | Title/description/icon/mascot -> accessible section  | Does not synthesize current safety information            |
| `getPublicEnvironment` | Parse browser-safe configuration                  | environment-like object -> typed values or Zod error | No secret variable is accepted                            |
| `GET` health handler   | Web-process liveness                              | No input -> JSON                                     | Does not call the public API                              |

### Decisions/trade-offs

- Decision: later-feature routes exist now as explicit empty states. Alternative: omit routes until each feature lands. Reason: validates routing/layout/responsiveness without inventing data. Consequence: the slice is navigable but intentionally not a usable travel product. ADR: N/A; documented in the screen inventory and README.
- Decision: only `AppShell` is client-rendered. Alternative: make all route pages clients. Reason: minimize client JavaScript and leave data boundaries ready for server rendering. Consequence: interactive feature islands must opt in during later phases.
- Decision: preserve supplied PNGs and use Next Image format negotiation. Alternative: commit duplicate generated WebP/AVIF files. Reason: preserve source fidelity and avoid asset duplication. Consequence: image optimization happens at serving time.
- Decision: `/api/health` is liveness only. Alternative: proxy API readiness. Reason: orchestration must distinguish web-process health from downstream readiness. Consequence: full-stack readiness needs a separate acceptance probe.

Accepted debt: several large supplied PNGs remain in `public`; bundle/runtime
performance and full visual/accessibility baselines are Phase 8 work.

## 6. API, contract and event changes

| Producer | Method/path/event | Request schema | Response schema                  | Consumer            | Compatibility                |
| -------- | ----------------- | -------------- | -------------------------------- | ------------------- | ---------------------------- |
| Web      | `GET /api/health` | None           | `{status: "ok", service: "web"}` | Docker/orchestrator | New web-local liveness route |

- Generated client command/result: Dockerized `npm run bundle` plus `npm run generate:ts` produced a 2,829-line TypeScript declaration and matched the committed bundled OpenAPI and TypeScript outputs byte-for-byte (`generated-contract-artifacts-clean`). Phase 2 will integrate the client at runtime.
- Contract lint/consumer result: `npm run check` passed in Docker — OpenAPI valid with 2 intentional ignores, 31 schemas compiled, 6 examples validated, and the M01 consumer TypeScript check compiled with no errors.
- Compatibility finding: the current shell does not consume contract payloads at runtime, and its Phase 0 assumptions remain valid. Later UI work must preserve `RouteCandidate.exposure: null` as unevaluated/unknown and render `EmergencyPoi.name: null` without dropping the place.
- Deprecation/migration plan: N/A.
- Sanitized request/response example: the health response is shown in §10; it contains no user/provider data.

## 7. Database, cache and storage changes

No database, cache, Qdrant collection, browser persistence, migration, retention,
backup, or encryption change exists in this slice. All migration and persistence
checks are N/A.

## 8. External providers and real data

No external provider or real-data endpoint is called in Phases 0–1.

- Runtime/demo has no mock or hard-coded current data: [x] — source search found no runtime mock switch, fixture import, sample payload route, provider call, or hard-coded current condition.
- Test fixtures: only structural environment strings and mocked `usePathname`; no current provider payload.
- Unsupported/unavailable behavior: pages say `No live data available`; login says `Sign-in unavailable`.
- Schema drift/quota/failover: N/A until provider/API integration.

## 9. Configuration and Docker

### Environment variables added/changed

| Variable                     | Required                    | Secret                                 | Default/example         | Used by                                | Failure if missing                   |
| ---------------------------- | --------------------------- | -------------------------------------- | ----------------------- | -------------------------------------- | ------------------------------------ |
| `NEXT_PUBLIC_API_BASE_URL`   | Yes for API-enabled runtime | No                                     | `http://localhost:8000` | `getPublicEnvironment`; Phase 2 client | Zod parse error when parsed          |
| `NEXT_PUBLIC_MAP_TILE_URL`   | No until map phase          | No; public URL only                    | Empty                   | Environment schema                     | Empty accepted; invalid URL rejected |
| `NEXT_PUBLIC_MAP_TILE_TOKEN` | No until map phase          | No provider secret may use this prefix | Empty                   | Environment schema                     | Empty accepted                       |
| `PLAYWRIGHT_BASE_URL`        | Test only                   | No                                     | `http://127.0.0.1:3000` | Playwright                             | Default used                         |

### Exact run and verification commands

```bash
docker run --rm -v "$PWD/packages/contracts:/src:ro" -w /work \
  node:22.23.2-alpine3.24 sh -lc \
  'cp /src/package.json /src/package-lock.json /src/redocly.yaml \
   /src/.redocly.lint-ignore.yaml /src/tsconfig.json /work/ && \
   cp -a /src/openapi /src/jsonschema /src/examples /src/generated \
   /src/consumer-checks /src/scripts /work/ && npm ci && npm run check'

docker run --rm -v "$PWD/packages/contracts:/src:ro" -w /work \
  node:22.23.2-alpine3.24 sh -lc \
  'cp /src/package.json /src/package-lock.json /src/redocly.yaml \
   /src/tsconfig.json /work/ && cp -a /src/openapi /src/jsonschema \
   /src/generated /src/scripts /work/ && \
   cp /work/generated/openapi/public-api.bundled.yaml /tmp/bundled.yaml && \
   cp /work/generated/typescript/public-api.d.ts /tmp/public-api.d.ts && \
   npm ci >/dev/null && npm run bundle && npm run generate:ts && \
   cmp /tmp/bundled.yaml /work/generated/openapi/public-api.bundled.yaml && \
   cmp /tmp/public-api.d.ts /work/generated/typescript/public-api.d.ts'

docker build --target development \
  --tag smart-travel-web:pr-check-contract-rebase apps/web
docker run --rm smart-travel-web:pr-check-contract-rebase pnpm lint
docker run --rm smart-travel-web:pr-check-contract-rebase pnpm format
docker run --rm smart-travel-web:pr-check-contract-rebase pnpm typecheck
docker run --rm smart-travel-web:pr-check-contract-rebase pnpm test
docker compose -f compose.yaml -f compose.dev.yaml config --quiet

docker build --target runtime \
  --tag smart-travel-web:phase1-contract-rebase apps/web
docker run --rm -d --name smart-travel-web-contract-rebase-check \
  -p 127.0.0.1:33000:3000 smart-travel-web:phase1-contract-rebase
docker exec smart-travel-web-contract-rebase-check id
curl --fail --silent --show-error http://127.0.0.1:33000/api/health
docker inspect smart-travel-web-contract-rebase-check \
  --format '{{.State.Status}} health={{.State.Health.Status}}'

docker run --rm --network container:smart-travel-web-contract-rebase-check \
  -v "$PWD/apps/web:/src:ro" -w /work \
  -e CI=1 -e PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 \
  mcr.microsoft.com/playwright:v1.55.0-noble bash -lc \
  'cp /src/playwright.config.ts /work/ && mkdir -p /work/tests && \
   cp -a /src/tests/e2e /work/tests/e2e && npm init -y >/dev/null && \
   npm install --no-save @playwright/test@1.55.0 >/dev/null && \
   npx playwright test --reporter=line'
docker stop smart-travel-web-contract-rebase-check
```

- Container user: `uid=100(app) gid=101(app)`.
- Port: runtime exposes 3000; verification published it only on `127.0.0.1:33000`.
- Network/volumes: no runtime volume; E2E mounts source read-only and copies only test/config files into an ephemeral runner.
- Health/readiness: Docker reported `running health=healthy`; `/api/health` returned HTTP 200. This is liveness, not downstream API readiness.
- CPU/RAM/disk measured: not profiled; local image size is 91,716,820 bytes.
- Runtime image/tag/digest: `smart-travel-web:phase1-contract-rebase`, `sha256:031821102a7013ea054c2a0b4adc22100d9c1b92ee64733426f94bab0815649b`.
- Base image: `node:22.23.2-alpine3.24@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85`.
- Docker client/server: 27.2.0 / 27.2.0.

## 10. Tests and verification

| Test type             | Command                                        |                                         Passed | Failed | Skipped | Evidence                                                        |
| --------------------- | ---------------------------------------------- | ---------------------------------------------: | -----: | ------: | --------------------------------------------------------------- |
| Contract package      | Dockerized `npm run check`                     | 31 schemas / 6 examples / 1 consumer typecheck |      0 |       0 | OpenAPI valid; M01 TypeScript consumer compiled                 |
| Generated TS parity   | Dockerized bundle/generate/`cmp`               |                                    2 artifacts |      0 |       0 | Bundled OpenAPI and 2,829-line TypeScript output unchanged      |
| Lint                  | `docker run --rm ... pnpm lint`                |                                      1 command |      0 |       0 | Exit 0, no ESLint findings                                      |
| Format                | `docker run --rm ... pnpm format`              |                                      1 command |      0 |       0 | All matched files use Prettier code style                       |
| Type                  | `docker run --rm ... pnpm typecheck`           |                                      1 command |      0 |       0 | Exit 0, no TypeScript findings                                  |
| Unit/component        | `docker run --rm ... pnpm test`                |                              4 tests / 2 files |      0 |       0 | Vitest completed in 53.22 s                                     |
| Compose               | `docker compose ... config --quiet`            |                                        1 check |      0 |       0 | Rebased combined configuration valid                            |
| Production build      | `docker build --target runtime ...`            |                                        1 build |      0 |       0 | Next 16.3.5 compiled, typechecked, and generated 9 static pages |
| E2E                   | Dockerized Playwright command in §9            |                                        3 tests |      0 |       0 | Chromium: 3 passed in 46.0 s                                    |
| Health/runtime user   | `curl`, `docker inspect`, `docker exec ... id` |                                       3 checks |      0 |       0 | HTTP 200, healthy, non-root uid 100                             |
| Security/privacy scan | Not run                                        |                                              0 |      0 |       0 | Required CI scan still pending                                  |
| Axe/visual/load       | Not run                                        |                                              0 |      0 |       0 | Full suites belong to Phase 8; keyboard/tap E2E did run         |

### Scenarios verified

- Success: updated contract consumer compiled; generated TypeScript stayed clean; every route compiled; desktop/mobile navigation reached target routes; liveness returned 200.
- Invalid input: missing API URL and invalid map URL throw schema errors.
- Keyboard/touch: mobile disclosure opens/closes, 44 px navigation target is tappable, Enter activates links.
- Timeout/429/5xx, stale/partial/conflicting data, cancellation/idempotency/concurrency: N/A because Phase 2/API behavior is not implemented.
- Restart/rollback: container start and health verified; restart persistence is N/A because no state is stored.
- Request/correlation IDs: N/A; no public API request was made.

## 11. UI evidence

| Screen/state/viewport             | Reference                                     | Result/evidence                                                                    | Visual gap                                              |
| --------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Login, desktop 1672×941           | `assets/ui-screens/00-login.png`              | Local capture `/private/tmp/web-after-login-final.png`; production build passed    | Auth controls intentionally unavailable until Phase 2   |
| Shell/dashboard, desktop 1672×941 | `assets/ui-screens/01-dashboard-overview.png` | Local capture `/private/tmp/web-after-dashboard-final.png`; desktop E2E passed     | Feature cards/map intentionally replaced by empty state |
| Shell, mobile 390×844             | Phase 1 responsive requirement                | Local capture `/private/tmp/web-after-mobile-final.png`; touch/keyboard E2E passed | Full Phase 8 mobile baseline not established            |

- Keyboard result: mobile and desktop navigation E2E passed; visible focus styling is global.
- Axe, screen-reader, Thai/long text/200% zoom: not run; Phase 8.
- Loading/error/empty: boundaries and explicit empty state exist. Degraded/offline semantics start in Phase 2.
- The three local PNGs must be attached to the PR; they are evidence artifacts, not committed source assets.

## 12. Safety, security and privacy review

- [x] No runtime safety claim, recommendation, contact, or current condition is invented.
- [x] No secret, token, PII, medical detail, or exact user location is present in code/tests/log evidence.
- [x] Public configuration accepts only browser-safe values; `.env*` is excluded from Docker except `.env.example`.
- [x] Error UI exposes no internal stack or secret.
- [x] Official-warning priority cannot be weakened because no warning processing exists in this slice.
- [ ] Dependency/image/secret scans were not run locally; required CI remains pending.
- [ ] Auth, consent, ownership, timeout, retry, cancellation, idempotency, provenance, and LLM/provider trust controls are N/A until their planned phases and are not claimed complete here.

No safety/security finding remains inside the Phase 0–1 implementation. Release
is blocked by intentionally absent later-phase controls.

## 13. Problems encountered and resolutions

| Problem                                                              | Root cause                                                                                                | Evidence                                                                                         | Resolution/workaround                                                                                                       | Remaining risk                                                     |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Branch was behind main                                               | `origin/main` advanced through shared contract/API work to `b13c1be`, then docs-only records to `3353f15` | Current merge base equals `origin/main`; final delta touched only `docs/handoffs/m04-records/**` | Rebased branch and reran all checks affected by the contract/API changes; the final docs-only delta did not invalidate them | None; verify again immediately before push                         |
| `next-env.d.ts` pointed at dev-only generated types                  | `next dev` rewrites the generated reference                                                               | Pre-commit diff showed `.next/dev/types/routes.d.ts`                                             | Restored stable `.next/types/routes.d.ts` reference                                                                         | Next may rewrite it during local dev; review before future commits |
| First E2E container could not initialize beside a read-only lockfile | pnpm creates a temporary file in its working directory                                                    | `EROFS ... /work/_tmp_*`                                                                         | Copied only test/config files into disposable writable container storage                                                    | None                                                               |
| Two E2E setup retries found no tests                                 | One command forwarded a literal `--`; one copy flattened the `e2e` directory                              | Playwright `No tests found` before any test ran                                                  | Used direct `npx playwright test` and preserved `/work/tests/e2e`                                                           | None; final suite passed 3/3                                       |
| Docker development image export was slow                             | 1.4 GB dependency-heavy check image on the local Docker Desktop storage driver                            | Export 309.4 s, unpack 121.2 s                                                                   | Reused the tagged image for all static/unit checks                                                                          | CI time may benefit from cache/export tuning                       |
| `pnpm format` rejected the generated lockfile                        | Prettier was checking pnpm's canonical lockfile output                                                    | `pnpm-lock.yaml` was the only reported file                                                      | Added the generated lockfile to `.prettierignore`; rerun passed                                                             | None                                                               |

## 14. Performance and operational behavior

| Metric               | Target                         | Actual                              | Test condition                | Pass |
| -------------------- | ------------------------------ | ----------------------------------- | ----------------------------- | ---- |
| Runtime image user   | Non-root                       | uid 100 `app`                       | Local production container    | Yes  |
| Runtime image health | Healthy                        | Docker `healthy`; endpoint HTTP 200 | Local production container    | Yes  |
| Runtime image size   | No Phase 1 budget defined      | 91,716,820 bytes                    | Local arm64/desktop build     | N/A  |
| E2E shell suite      | All committed shell cases pass | 3/3 in 46.0 s                       | Chromium in Playwright Docker | Yes  |

No metrics, dashboards, alerts, circuit breakers, rate limits, provider caches,
or performance budgets are added in this slice. Disable/rollback by deploying the
previous image/commit; there is no state cleanup.

## 15. Known limitations and technical debt

| Limitation/debt                           | User/safety impact                        | Workaround                                                                | Owner        | Priority | Follow-up                    |
| ----------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------- | ------------ | -------- | ---------------------------- |
| No authentication or protected routes     | Shell is not a real signed-in experience  | Login explicitly says unavailable                                         | M01 Phase 2  | High     | `feat/01-auth-api-client`    |
| No API client/SSE/live data               | No trip or safety decision can be made    | Every route shows honest empty state                                      | M01 Phase 2+ | High     | Planned later slices         |
| No full axe/visual matrix                 | Accessibility/pixel gaps may remain       | Keyboard/touch regression tests cover shell basics                        | M01 Phase 8  | Medium   | `test/01-visual-a11y-e2e`    |
| Large source PNGs                         | Slower transfer/storage on first view     | Next Image format negotiation                                             | M01 Phase 8  | Medium   | Performance pass             |
| Asset licence not stated in supplied pack | Redistribution terms are not documented   | Treat as project-supplied; do not publish externally without confirmation | Team Lead    | Medium   | Licence/attribution decision |
| Check image is 1.4 GB                     | Slow local export, not production runtime | Reuse Docker cache; runtime image is 91.7 MB                              | M01/CI       | Low      | CI cache optimization        |

## 16. Handoff to other members

| Recipient/module | What is ready                                               | What they must change/do                                                                                                                         | Contract/config                                             | Blocking?                                             |
| ---------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- | ----------------------------------------------------- |
| M01 Phase 2      | Route/layout boundaries, env schema, test/Docker foundation | Add OIDC, generated client, query/SSE and shared live-data states without runtime mocks; preserve nullable route exposure and POI name semantics | Public API v1 at `3353f15`; three `NEXT_PUBLIC_*` variables | No                                                    |
| M02 public API   | UI-to-contract inventory                                    | Review browser auth/SSE handoff decisions before Phase 2                                                                                         | `apps/web/docs/screen-inventory.md`                         | Review needed for Phase 2                             |
| Team Lead/CI     | Reproducible Docker commands and image                      | Run required dependency/image/secret scans and attach local screenshots                                                                          | Docker 27.2.0 evidence                                      | Blocks merge only if repository requires those checks |

Exact handoff branch: `feat/01-web-shell`; report:
`docs/handoffs/M01-web-shell.md`; PR draft:
`docs/handoffs/M01-web-shell-pr.md`.

## 17. Commit and PR inventory

```text
22370bd docs(web): add screen and contract inventory
e4ba291 chore(web): scaffold Next.js application
6a42736 feat(web): add travel design tokens and assets
4aff7ec feat(web): add responsive application shell
71c8310 style(web): format screen inventory
30eb354 infra(web): add Docker Compose service
cbc80ae feat(web): align phase 1 shell with approved visuals
5418c18 fix(web): restore mobile shell interactions
c884b1c chore(web): refresh phase 1 runtime toolchain
80d7daf docs(web): add phase 1 completion evidence
```

- PR review comments resolved: N/A — PR not opened.
- Required checks status: local requested checks pass; GitHub checks not yet run.
- Rebased on main SHA: `3353f158787f2d7df6b997ab8ff0aa209615e01c`.
- Squash title proposed: `[M01] Add responsive web shell and Phase 1 foundation`.

## 18. Rollback and recovery

1. Feature flag/provider disable: N/A; no provider or feature flag exists.
2. Application rollback: deploy the prior web image/commit; local verification tag is `smart-travel-web:phase1-contract-rebase`.
3. Migration downgrade/forward-fix: N/A; no database change.
4. Model/policy/prompt/knowledge rollback: N/A.
5. Data/cache cleanup: N/A; no persisted or cached user/provider data.
6. After rollback, verify the prior image's `/api/health`, non-root user, and shell route smoke tests.

## 19. Final declaration

- [x] Phase 0–1 scope is complete according to the evidence above.
- [x] No required Phase 0–1 work is hidden.
- [x] Documentation, environment example, Docker files, and tests are updated; contracts/migrations are unchanged by design.
- [x] Downstream handoff paths and Phase 2 boundary are explicit.
- [x] Ready for review/merge after required repository CI and approval.
- [ ] Not ready for product release — Phase 2 and later live/auth/safety flows are intentionally absent.

Prepared by: Codex, with local Docker evidence captured on 2026-09-21 (Asia/Bangkok).
