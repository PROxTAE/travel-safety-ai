# [M01] Implement the Real Trip Planner Vertical Slice

## Summary

Implements Phase 3 of the M01 web plan: real geocoding and pin confirmation,
timezone-aware trip validation, persisted create/update operations, assessment
submission and SSE progress, plus server-owned route map/list states. It also
aligns the Trip Planner with the supplied screen reference, polishes the hero and
responsive sign-out action, supports provider-required map attribution, and
preserves an honest unavailable state while the M03 Agent runtime is absent.

Open this PR as **Draft**: all available post-rebase checks pass, but Phase 3's
login-to-route-options exit cannot pass until M03 is runnable.

## Scope

In scope:

- `apps/web/**` Trip Planner UI, form, geocoder, MapLibre, route presentation,
  tests, isolated integration environment, local assets, and README.
- Completion report and this PR draft under `docs/handoffs/**`.
- Real Keycloak/API/PostgreSQL/Redis/external-data/Open-Meteo browser verification.

Out of scope:

- Phase 4 dashboard/comparison work.
- M03 Agent service implementation.
- Shared Compose or `.env.example` changes.
- API contract/schema and database migration changes.
- Phase 8 full visual, accessibility, localization, and performance matrix.

## Ownership and dependencies

- Module/owner: M01 / web app.
- Depends on: public API OpenAPI `1.0.0`, merged M01 Phase 2, M02 public API and
  M04 external-data/geocoding.
- Downstream consumers: Phase 4 dashboard/comparison and later M01 screens.
- Blocking dependency: M03 Agent runtime for successful recommendation/route
  options.
- Issue/ADR: `IMPLEMENTATION_PLANS/01_WEB_APP_IMPLEMENTATION.md`, Phase 3; no new
  ADR.

## Contract, database and configuration changes

- API/OpenAPI/JSON Schema: no shared contract change; generated consumer drift
  check passes.
- Migration/table/index: none.
- Environment variables: adds browser-visible
  `NEXT_PUBLIC_MAP_TILE_ATTRIBUTION` so deployments can show the selected tile
  provider's required attribution. Existing optional `NEXT_PUBLIC_MAP_TILE_URL`
  / `NEXT_PUBLIC_MAP_TILE_TOKEN` behavior remains documented. No value or secret
  is committed.
- Shared development-stack changes from Phase 2 are already on main and are not
  part of this branch.
- Backward compatibility/rollout: additive web route behavior; rollback is a web
  image/code rollback with no data cleanup.

## Real data and provenance

- Provider/source: Open-Meteo geocoding through M04 external-data and M02 API.
- Endpoint/coverage: authenticated location search for public Bangkok and Chiang
  Mai city locations; persisted trip/assessment through the real API.
- License/attribution: provider-owned; map tile operators must configure their
  own approved URL/attribution.
- Freshness/TTL: provider/backend controlled and rendered from server metadata
  when available.
- Failure/degraded behavior: abort superseded search, show empty/provider errors,
  and show the real M03 dependency failure without sample route options.
- [x] Runtime/demo has no mock or hard-coded current travel data.

## How to run

```bash
git fetch origin
git rebase origin/main
node apps/web/scripts/test-docker.mjs
docker build --target runtime -t smart-travel-web:m01-trip-planner apps/web
```

The test script uses an isolated Compose project with no published host ports and
a tmpfs database. It removes only its own containers with ordinary `down`; it does
not run `down -v` or touch the normal development stack.

## Verification evidence

Commands and post-rebase results:

```text
command: git rebase origin/main
result: Successfully rebased and updated refs/heads/feat/01-trip-planner.
base: 3ffa77c2e4b8ea82b604c635c48f75ca324a3593

command: node apps/web/scripts/test-docker.mjs
result: contract drift check passed
result: lint passed (exit 0)
result: typecheck passed (exit 0)
result: Test Files 10 passed (10); Tests 42 passed (42); latest Duration 21.99s
result: PostgreSQL, Redis, Keycloak, external-data, API, and web healthy
result: Playwright 6 passed (4.4m), 0 failed, 0 skipped

command: docker build --target runtime -t smart-travel-web:m01-trip-planner apps/web
result: compiled successfully; TypeScript finished; static pages 5/5 generated
result: image sha256:3699829bdc2566bcd481910d34c1931e5f3bf2320343a3cdb3519575ebb7101c
result: image size 94,784,007 bytes; runtime user app
```

- E2E covers real OIDC profile/logout, mobile shell, keyboard activation,
  desktop navigation, responsive Trip Planner map/list, real geocode, trip create
  `201`, update `200`, assessment `202`, SSE, and the current real M03 dependency
  error.
- UI reference: `assets/ui-screens/02-trip-planner.png`; manual 1672x941 and
  390x844 screenshots were inspected locally and were not committed.
- Login actions measured equal width: 469 px desktop and 312 px mobile.
- No trace/request payload containing temporary credentials is retained.
- Migration up/down: N/A; this branch has no migration.

## Safety, security and privacy

- [x] Input is validated at the form/API boundary.
- [x] Abort, bounded retries, SSE reconnect, and mutation idempotency are handled.
- [x] No secret, token, personal PII, or personal exact location is leaked to
      code/logs/fixtures; public test city locations are not personal data.
- [x] Provenance, timestamps, quality, and version are retained when returned.
- [x] The browser does not weaken or derive an official/final safety action.
- [x] Provider/API text is treated as untrusted display data.
- [x] Auth and ownership remain enforced by Keycloak and the API.
- [x] Errors expose a bounded public message rather than an internal stack/secret.
- [ ] Dependency/image vulnerability scans are not claimed; staged/full diff
      secret audit and production image build pass.

## Test coverage

- [x] Available success path: auth, real geocode, persist, revise, and submit.
- [x] Invalid/unauthorized path through form and Phase 2 auth regressions.
- [x] Dependency failure and shared transient API behavior.
- [x] Empty/degraded/unavailable route states and freshness/source rendering.
- [x] Timezone boundaries, keyboard/mobile regression, and duplicate intent.
- [x] Generated public API consumer contract check.
- [x] Real-service E2E.
- [ ] Final successful recommendation/route options — blocked by M03 runtime.

## Risks and limitations

- M03 currently has settings/state/event scaffolding but no runnable HTTP service,
  Dockerfile, or Compose service. The API therefore records the run then emits a
  terminal dependency error. Do not describe Phase 3 as release-complete.
- Without an approved tile provider, the map uses the supplied illustrated world
  map as a decorative fallback; coordinates and route geometry remain live layers.
- Automated axe, pixel diff, Thai/long text/200% zoom, and load/Core Web Vitals
  remain Phase 8 work.

## Rollback

- Code rollback: revert this branch's commit range or deploy the previous approved
  web image.
- Database/schema rollback or forward-fix: N/A; no migration.
- Feature flag/provider disable: remove optional map tile configuration to use the
  documented decorative fallback; no database/volume deletion is needed.

## Handoff

- Completion report: `docs/handoffs/M01-trip-planner.md`.
- Next owner: M03 must expose the runnable assessment/recommendation dependency;
  then M02/M01 should replace the unavailable assertion with a real route-options
  assertion and rerun the same Docker suite.
- Reviewer focus: timezone conversion, location confirmation, revision/ETag and
  idempotency behavior, cancellation/SSE lifecycle, no invented route data,
  responsive map/list controls, and the explicit M03 blocker.
