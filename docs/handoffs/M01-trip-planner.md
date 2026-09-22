# [M01] Trip Planner Vertical Slice Completion Report

## 1. Metadata

| Field                                          | Value                                                                                                          |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Module/owner                                   | M01 / web app                                                                                                  |
| Issue/PR                                       | PR not opened; local draft prepared                                                                            |
| Branch                                         | `feat/01-trip-planner`                                                                                         |
| Base/final commit SHA                          | Rebased base `3ffa77c`; implementation head `39c7d00` (this report is a follow-up documentation commit)        |
| Date/time/timezone                             | 2026-09-22 / Asia/Bangkok                                                                                      |
| Reviewers                                      | Required: `@lead`; requested: M02 API and M03 Agent owners                                                     |
| Contract version                               | Public API OpenAPI `1.0.0`                                                                                     |
| Docker image digest/tag                        | `smart-travel-web:m01-trip-planner`; `sha256:3699829bdc2566bcd481910d34c1931e5f3bf2320343a3cdb3519575ebb7101c` |
| Related model/policy/prompt/collection version | N/A; the browser does not own a decision model or policy                                                       |

## 2. Executive summary

This branch implements the Phase 3 Trip Planner vertical slice on top of the
merged Phase 2 authentication and API foundation. An authenticated traveller can
search real Open-Meteo geocoding results, choose and confirm origin/destination
pins, validate timezone-aware dates and preferences, create or revise a persisted
trip, start an assessment, and observe its authenticated SSE progress. Map/list
presentation renders only server-owned route data and has explicit loading,
empty, degraded, and error states. The real isolated Docker stack and six browser
tests pass after rebasing on `origin/main`. The repository still has no runnable
M03 Agent HTTP service, so the real API terminates the assessment with an honest
dependency error and cannot supply route options. The PR is suitable as a draft
for review, but Phase 3's final exit criterion and release readiness remain
blocked on M03.

## 3. Original responsibility and acceptance criteria

- [x] Location search and confirmation map — real geocoding, keyboard selection,
      explicit confirmation, component tests, and browser E2E.
- [x] Zod/RHF trip form and timezone validation — `lib/trips/form.ts` and 10-file
      Vitest suite.
- [x] Create/update trip, assessment, and progress SSE — real M02 API requests,
      persisted trip revision, assessment `202`, and authenticated event stream.
- [x] Route options map/list and error/degraded states — server response mapper,
      no fabricated route, responsive map/list controls.
- [x] Playwright flow creates a trip with a real integration environment — real
      Keycloak, API, PostgreSQL, Redis, external-data, and Open-Meteo.
- [ ] Exit: login to route options without a runtime fixture — blocked because
      M03 currently contains settings/state/event scaffolding but no runnable Agent
      service, HTTP entry point, Dockerfile, or Compose service.

Scope was not expanded into Phase 4. The branch also aligns the Trip Planner and
login action widths with the supplied UI reference. No API contract, shared
Compose, root `.env.example`, database schema, or migration is changed here.

## 4. What was implemented

### Features

| Feature               | Behavior now                                                           | Entry point         | Status                    |
| --------------------- | ---------------------------------------------------------------------- | ------------------- | ------------------------- |
| Location search       | Debounced, abortable public API search with keyboard listbox           | `/trips/new`        | Complete                  |
| Location confirmation | Interactive MapLibre markers require explicit user confirmation        | Trip form map       | Complete                  |
| Trip form             | IANA-timezone date validation and travel preferences                   | `TripPlanner`       | Complete                  |
| Persistence           | Creates a trip or updates it with revision/ETag semantics              | Public API proxy    | Complete                  |
| Assessment progress   | Idempotent assessment submission and authenticated SSE observation     | `useRunEvents`      | Complete                  |
| Route presentation    | Map/list, metrics, risk, provenance, freshness, and unavailable states | `RouteOptions`      | Complete when data exists |
| Live recommendation   | Agent-produced route options from the real stack                       | Assessment pipeline | Blocked by M03 runtime    |

### Important flows

```text
Keycloak login -> protected /trips/new -> debounced location searches
-> traveller selects and confirms both pins -> timezone-aware validation
-> POST /trips (or PATCH /trips/{id}) -> POST /trips/{id}/assessments
-> authenticated SSE /runs/{request_id}/events -> recommendation fetch or honest terminal error
-> server route options rendered, or unavailable/error state without invented data
```

The verified degraded path persists the trip and run, receives the M03
dependency failure over the real API flow, and leaves route options unavailable.

### What is explicitly not implemented

- M03 Agent runtime or recommendation generation.
- Phase 4 dashboard and route-comparison behavior.
- A default third-party tile provider or embedded provider credential.
- Full visual-regression, axe, 200% zoom, and Thai localization matrix; those are
  assigned to Phase 8.

## 5. Actual architecture and code design

### Folder/file map

| Path                                             | Purpose                                                         | Important owner/consumer         |
| ------------------------------------------------ | --------------------------------------------------------------- | -------------------------------- |
| `apps/web/features/trips/trip-planner.tsx`       | Orchestrates form, persistence, assessment, and result states   | M01 UI                           |
| `apps/web/features/trips/location-search.tsx`    | Abortable accessible geocoder combobox                          | Traveller / M02 geocoding facade |
| `apps/web/lib/trips/form.ts`                     | Form schema, defaults, timezone conversion, API payload mapping | Trip form/tests                  |
| `apps/web/components/trip/trip-map.tsx`          | Client-only MapLibre markers and route geometry                 | Location/route UI                |
| `apps/web/components/trip/route-options.tsx`     | Server-derived route cards and unavailable states               | Recommendation consumer          |
| `apps/web/features/assessment/use-run-events.ts` | Reusable SSE lifecycle and terminal-state handling              | Assessment UI                    |
| `apps/web/tests/e2e/trip-planner.spec.ts`        | Real geocode/create/update/assessment and responsive checks     | CI/reviewers                     |
| `apps/web/compose.phase2-test.yaml`              | Isolated real-service integration environment                   | Module verification              |

### Main components/classes/functions

| Symbol                             | Responsibility                                                 | Inputs/outputs                                 | Design notes                                 |
| ---------------------------------- | -------------------------------------------------------------- | ---------------------------------------------- | -------------------------------------------- |
| `TripPlanner`                      | Owns current trip/revision, submission, SSE, and display state | Form intent -> persisted trip/run/result state | Client component at interaction boundary     |
| `LocationSearch`                   | Searches and confirms a provider location                      | Query -> confirmed `LocationRef`               | Cancels superseded requests                  |
| `TripMap`                          | Draws confirmed points and API route geometry                  | Coordinates/GeoJSON -> interactive layer       | Dynamically loaded; fallback art is non-data |
| `RouteOptions`                     | Presents recommendation routes faithfully                      | API recommendation -> cards/layers             | Does not infer final safety action           |
| `tripFormSchema` / `toTripPayload` | Validates and converts wall-clock values                       | RHF values -> API request                      | Uses the selected IANA timezone              |

The page remains a server route boundary while browser-only form and map logic
live in client components. React Query/API policy remains inherited from Phase 2:
safe reads may retry transient failures, mutations do not auto-retry, and data is
stale immediately unless server freshness defines otherwise. Trip mutation
idempotency is per user intent.

### Decisions/trade-offs

- Decision: no unrestricted default tile service. The supplied world-map image
  is a visual fallback while MapLibre coordinates and geometry stay live.
- Alternative: hard-code a public tile URL. Rejected because attribution, quota,
  and production-use terms were not approved.
- Consequence: reviewers can verify interaction without a tile credential, but
  the fallback is not an authoritative basemap.
- Decision: expose the real missing-Agent error instead of adding a runtime mock.
- Consequence: the vertical slice is honest and testable, while the final route
  options exit remains explicitly blocked.
- ADR: none added; behavior follows the implementation plan and existing M01/M02
  contracts.

## 6. API, contract and event changes

| Producer | Method/path/event                          | Request schema                   | Response schema          | Consumer         | Compatibility                         |
| -------- | ------------------------------------------ | -------------------------------- | ------------------------ | ---------------- | ------------------------------------- |
| M02 API  | `GET /api/v1/locations/search`             | Search query                     | Location search envelope | `LocationSearch` | Existing v1                           |
| M02 API  | `POST /api/v1/trips`                       | `TripCreate`                     | Trip envelope            | `TripPlanner`    | Existing v1                           |
| M02 API  | `PATCH /api/v1/trips/{trip_id}`            | `TripUpdate` + revision          | Trip envelope            | `TripPlanner`    | Existing v1                           |
| M02 API  | `POST /api/v1/trips/{trip_id}/assessments` | Assessment request + idempotency | Run reference, `202`     | `TripPlanner`    | Existing v1                           |
| M02 API  | `GET /api/v1/runs/{request_id}/events`     | SSE resume headers               | Shared SSE events        | `useRunEvents`   | Existing v1                           |
| M02 API  | Recommendation endpoint                    | Run/request reference            | Recommendation response  | `RouteOptions`   | Existing v1; success blocked upstream |

- Generated client command/result: `pnpm check:api` passed inside Docker; no
  generated diff.
- Contract lint/breaking check result: the OpenAPI consumer drift check passed;
  this branch changes no shared contract.
- Deprecation/migration plan: N/A.
- Sanitized examples: existing `packages/contracts/examples/**`; browser E2E uses
  public Bangkok and Chiang Mai city locations, not personal travel data.

## 7. Database, cache and storage changes

There are no migrations, table/index changes, cache-key changes, or new browser
storage. The integration environment runs existing API/external-data migrations
against its own tmpfs PostgreSQL database. Empty-DB startup and restart readiness
passed as part of `node apps/web/scripts/test-docker.mjs`; previous-main migration,
backup/restore, and retention changes are N/A. OAuth tokens remain server-side and
are not stored in localStorage.

## 8. External providers and real data

| Provider/source            | Endpoint/capability                                    | Coverage                      | Credential ref                           | Freshness/TTL               | License/attribution                      | Last canary            |
| -------------------------- | ------------------------------------------------------ | ----------------------------- | ---------------------------------------- | --------------------------- | ---------------------------------------- | ---------------------- |
| Open-Meteo                 | Geocoding through M04 external-data and M02 public API | Bangkok and Chiang Mai search | No browser credential                    | Provider/runtime controlled | Provider-owned; surfaced through backend | 2026-09-22 Docker E2E  |
| Optional map-tile operator | MapLibre style/tiles                                   | Configured deployments only   | `NEXT_PUBLIC_MAP_TILE_TOKEN` if required | Operator controlled         | Operator must supply attribution         | Not configured in test |

- [x] Runtime/demo contains no mock or hard-coded current travel data.
- Test inputs are public city names; unit-only protocol frames contain no provider
  facts and are not imported by runtime code.
- Unsupported/unavailable route generation is shown as unavailable with the real
  dependency error; no sample route is substituted.
- Superseded geocoding requests are aborted. Provider error/empty states are
  explicit; quota/failover remains owned by M04.

## 9. Configuration and Docker

### Environment variables added/changed

| Variable                           | Required                                    | Secret              | Default/example        | Used by                                  | Failure if missing                                                                          |
| ---------------------------------- | ------------------------------------------- | ------------------- | ---------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_MAP_TILE_ATTRIBUTION` | Required when a tile provider is configured | No; browser-visible | Empty placeholder only | `TripMap` / MapLibre attribution control | Falls back to generic provider text; deployments must set the provider-required attribution |

The branch continues to consume the existing `NEXT_PUBLIC_MAP_TILE_URL` and
optional `NEXT_PUBLIC_MAP_TILE_TOKEN`, plus the existing Phase 2 Auth/API
settings documented in `apps/web/README.md` and `.env.example`. No secret value
or `.env` file is in the diff. A local ignored `.env.local` may select a tile
provider for development; it is not part of the branch.

### Run commands

```bash
git fetch origin
git rebase origin/main
node apps/web/scripts/test-docker.mjs
docker build --target runtime -t smart-travel-web:m01-trip-planner apps/web
```

- Container user: non-root `app`.
- Integration network/volumes: isolated Compose project, no host ports, tmpfs
  PostgreSQL, reusable browser dependency/results volumes; shared dev volumes are
  not touched.
- Health/readiness: PostgreSQL, Redis, Keycloak, external-data, API, and web must
  be healthy before Playwright runs. Web healthcheck calls `/api/health`.
- CPU/RAM/disk measured: not benchmarked.
- Image size/digest: 94,784,007 bytes (~90.4 MiB),
  `sha256:3699829bdc2566bcd481910d34c1931e5f3bf2320343a3cdb3519575ebb7101c`.

## 10. Tests and verification

| Test type            | Command                                                                       |                   Passed |     Failed |                          Skipped | Evidence                                                |
| -------------------- | ----------------------------------------------------------------------------- | -----------------------: | ---------: | -------------------------------: | ------------------------------------------------------- |
| Contract             | `node apps/web/scripts/test-docker.mjs` (`pnpm check:api`)                    |                1 command |          0 |                                0 | Generated client clean                                  |
| Lint                 | same (`pnpm lint`)                                                            |                1 command |          0 |                                0 | Exit 0                                                  |
| Typecheck            | same (`pnpm typecheck`)                                                       |                1 command |          0 |                                0 | Exit 0                                                  |
| Unit/component       | same (`pnpm test`)                                                            |      42 tests / 10 files |          0 |                                0 | Latest Vitest 21.99 s                                   |
| Integration/E2E      | same (`npx playwright test`)                                                  |                        6 |          0 |                                0 | Latest Playwright 4.4 min                               |
| Production build     | `docker build --target runtime -t smart-travel-web:m01-trip-planner apps/web` |                        1 |          0 |                                0 | Compile/type/static generation passed                   |
| Security/privacy     | Staged/full diff secret audit                                                 |                  1 audit | 0 findings | Image/dependency scanner not run | No `.env`, credential, token, or password value in diff |
| Accessibility/visual | Keyboard/touch/responsive Playwright plus manual 1672x941/390x844 inspection  | 3 relevant browser cases |          0 |      axe and pixel-diff deferred | No overflow/console error observed                      |
| Load/performance     | Not run                                                                       |                        0 |          0 |                                1 | Phase 8 scope                                           |

### Scenarios verified

- Success: real OIDC profile/logout; geocode both endpoints; confirm pins; create
  trip (`201`); update trip (`200`); submit/re-submit assessment (`202`).
- Invalid/unauthorized: Phase 2 auth redirect/session tests and trip-form validation
  remain passing.
- Timeout/429/5xx: shared API retry/error unit coverage remains passing; the E2E
  observes the real unavailable Agent dependency.
- Stale/partial/conflicting data: route options preserve unavailable/freshness/
  source states and never invent data.
- Cancellation/idempotency/concurrency: location AbortSignal, Phase 2 duplicate
  submission coverage, mutation idempotency keys, and SSE deduplication pass.
- Restart/rollback: isolated services started from clean tmpfs and passed health
  gates; rollback is code-only because no data migration exists.
- Request/correlation IDs were not printed or stored by the passing Playwright run.

## 11. UI evidence

| Screen/state/viewport      | Reference                               | Result                                                                          | Visual gap                          |
| -------------------------- | --------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------- |
| Trip Planner / 1672x941    | `assets/ui-screens/02-trip-planner.png` | Manual screenshot inspected; three-column layout and actions present            | Exact automated pixel diff deferred |
| Trip Planner / 390x844     | Responsive requirement                  | Map/List controls visible, no horizontal body overflow                          | Full Phase 8 device matrix deferred |
| Login / desktop and mobile | Existing login reference                | Keycloak and Continue actions have equal widths (469 px desktop, 312 px mobile) | None observed                       |
| M03 unavailable            | Error/degraded design                   | Explicit alert and unavailable route state                                      | Expected dependency limitation      |

- Keyboard: geocoder selection and mobile keyboard activation pass. axe was not
  run and is not claimed.
- Thai/English/long text/200% zoom: not yet verified; Phase 8.
- Loading, empty, error, degraded, and no-route states exist; offline matrix is
  deferred to Phase 8.
- Supplied PNG assets are local presentation assets. The illustrated map is not
  used for coordinates, route calculations, or current conditions.

## 12. Safety, security and privacy review

- [x] Official warning/closure priority is not overridden in the browser.
- [x] Provider/API text and geometry are treated as untrusted display data.
- [x] No secret, token, personal PII, or personal exact location is in code, logs,
      traces, or fixtures; test city centers are public locations.
- [x] Auth and trip ownership are enforced by the real Keycloak/API boundary.
- [x] Abort, bounded retry, SSE reconnect, and mutation idempotency are retained.
- [x] Source/freshness/quality/version fields are preserved when provided.
- [x] Fallback/degraded behavior does not invent route or safety data.
- [ ] Dependency/image vulnerability scanners were not run; secret diff audit and
      production image build passed.

The test script disables traces so temporary credentials are not recorded, uses a
random per-run password, and executes on an isolated network with no published
ports. Cleanup uses ordinary Compose `down`, never `down -v`, and does not touch
the shared development stack.

## 13. Problems encountered and resolutions

| Problem                                                | Root cause                                                 | Evidence                                 | Resolution/workaround                                                                  | Remaining risk                                       |
| ------------------------------------------------------ | ---------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| First browser verification timed out on a mobile route | Cold dev compilation exceeded the former 15 s test timeout | Single pre-rebase Playwright timeout     | Raised only the affected browser test timeout to 60 s; full post-rebase run passed 6/6 | Dev-mode timing may vary on slower hosts             |
| Assessment cannot return route options                 | M03 has scaffolding but no runnable service/Compose entry  | Real API emits terminal dependency error | Show honest error/unavailable state and test it without runtime fixtures               | Phase 3 exit remains blocked                         |
| No approved default tile provider                      | Provider terms/credential were not selected                | No tile URL configured in isolated stack | Interactive MapLibre layers use supplied decorative fallback                           | Geographic context is limited without operator tiles |
| README described a neutral fallback                    | UI was updated to supplied illustrated world map           | Documentation review before PR           | Updated `apps/web/README.md`                                                           | None                                                 |

## 14. Performance and operational behavior

No production performance target or load benchmark was part of Phase 3, so
p50/p95/max and Core Web Vitals are not claimed. Operationally, health gates
prevent browser tests from racing service startup; searches debounce for 400 ms
and abort superseded work; event reconnects are bounded. No new dashboard,
metric, alert, circuit breaker, or quota policy is introduced by this branch.
Rollback is a normal image/code rollback with no storage cleanup.

## 15. Known limitations and technical debt

| Limitation/debt                              | User/safety impact                        | Workaround                                      | Owner          | Priority            | Follow-up                       |
| -------------------------------------------- | ----------------------------------------- | ----------------------------------------------- | -------------- | ------------------- | ------------------------------- |
| No runnable M03 Agent service                | No live route recommendation can complete | Honest dependency alert; persisted trip remains | M03            | Blocker             | M03 runtime/Compose integration |
| Decorative fallback without tiles            | Reduced geographic context                | Configure approved tile URL/token               | M01/operations | Medium              | Phase 8/config review           |
| No automated axe/pixel diff/200%/Thai matrix | Accessibility/visual gaps may remain      | Manual responsive and keyboard checks           | M01            | High before release | `test/01-visual-a11y-e2e`       |
| No load/Core Web Vitals evidence             | Performance regression not quantified     | Production build and responsive smoke only      | M01            | Medium              | Phase 8                         |

## 16. Handoff to other members

| Recipient/module | What is ready                                   | What they must change/do                                                    | Contract/config                         | Blocking?              |
| ---------------- | ----------------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------- | ---------------------- |
| M03 Agent        | Persisted assessment/run and M01 SSE consumer   | Provide runnable service that produces the existing recommendation contract | Public API `1.0.0`; assessment/SSE flow | Yes                    |
| M02 API          | Real create/update/assessment flow exercised    | Wire/verify M03 runtime dependency once available                           | Existing public API paths               | Yes, downstream of M03 |
| `@lead`          | Rebased draft, Docker evidence, report, PR body | Review shared dependency assumptions and known Phase 3 exit gap             | No shared-file change in branch         | Review required        |
| M01 Phase 8      | Responsive UI and test selectors                | Add axe, visual baselines, Thai/zoom/device matrix                          | `test/01-visual-a11y-e2e`               | Before release         |

## 17. Commit and PR inventory

```text
d86fd87 feat(web): implement trip planner vertical slice
70d9a82 test(web): verify real trip planner integration
39c7d00 fix(web): align trip planner with visual reference
```

- PR review comments resolved: N/A; PR not opened.
- Required checks status: local post-rebase contract/lint/type/unit/integration/E2E
  and production build pass; remote CI not run.
- Rebased on main SHA: `3ffa77c2e4b8ea82b604c635c48f75ca324a3593`.
- Squash title proposed: `feat(web): implement real trip planner vertical slice`.

## 18. Rollback and recovery

1. No feature flag was added; disable exposure by rolling back the web image/code.
2. Restore the prior approved web image rather than deleting containers or data.
3. No migration downgrade or forward-fix is required.
4. No model/policy/prompt/knowledge rollback applies.
5. No data/cache cleanup is required; persisted trips use existing schemas.
6. After rollback, verify `/api/health`, login, profile, logout, and the previous
   route boundaries. Never delete the shared PostgreSQL volume for this rollback.

## 19. Final declaration

- [ ] Work in scope is fully complete — implementation items pass, but the Phase
      3 route-options exit is blocked by M03.
- [x] No required work is hidden; the blocker and deferred Phase 8 checks are
      listed above.
- [x] Documentation is updated; no env, contract, or migration change was needed.
- [x] Downstream handoff requirements are documented for M02/M03 and `@lead`.
- [ ] Ready to merge — open as draft until the team accepts the explicit M03
      dependency or the real route-options flow passes.
- [ ] Ready to release — requires M03 and the Phase 8 accessibility/visual matrix.

Prepared by: Codex on behalf of M01
