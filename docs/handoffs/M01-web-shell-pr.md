# [M01] Add responsive web shell and Phase 1 foundation

## Summary

Adds the Phase 0 screen/contract inventory and the Phase 1 Next.js web
foundation: visual tokens, responsive shell, route/error/loading boundaries,
honest unavailable states, public-environment validation, tests, and a
standalone non-root Docker runtime. This creates a verified UI foundation
without inventing live travel data before API integration exists.

## Scope

In scope:

- Phase 0 screen, interaction, state, asset, and public-contract inventory.
- Phase 1 Next.js 16/React 19 strict TypeScript scaffold.
- HeroUI/Tailwind styling, design tokens, desktop/mobile navigation shell.
- Empty route boundaries for login, dashboard, trips, comparison, safety map,
  assistant, and emergency.
- Public environment schema, web liveness endpoint, unit/component/E2E setup.
- Standalone non-root production image and Compose service definitions.

Out of scope:

- Phase 2 Auth.js/OIDC, route protection, generated API client, Query/SSE, and
  live-data shared components.
- All live trip/map/recommendation/assistant/emergency features and providers.
- Runtime mocks, hard-coded current travel data, and browser safety decisions.
- Full Phase 8 axe, visual-baseline, localization, zoom, and performance pass.

## Ownership and dependencies

- Module/owner: M01 web application.
- Depends on PR/contract: public API v1 as present at `3353f15`; the M01 consumer check passes against the updated route/place shapes. This PR does not modify the shared contract.
- Downstream consumers: M01 Phase 2+ feature branches; M02 reviews auth/SSE handoff before Phase 2.
- Issue/ADR: no issue/ADR supplied; Phase 0 decisions are in `apps/web/docs/screen-inventory.md`.

## Contract, database and configuration changes

- API/OpenAPI/JSON Schema: no shared contract change. The rebased v1 contract permits unevaluated routes with `exposure: null` and emergency POIs with `name: null`; the M01 consumer assertions compile and preserve both distinctions. Adds web-local `GET /api/health` returning `{status, service}`.
- Migration/table/index: N/A — no database/storage change.
- Environment variables: `NEXT_PUBLIC_API_BASE_URL`; optional `NEXT_PUBLIC_MAP_TILE_URL` and `NEXT_PUBLIC_MAP_TILE_TOKEN`. None may contain a provider secret.
- Backward compatibility/rollout: additive web application and Compose service; later phases fill the existing route boundaries.

## Real data and provenance

- Provider/source: N/A — the browser calls no provider or API in Phases 0–1.
- Endpoint/coverage: web-process liveness only.
- License/attribution: supplied project assets have no licence statement in the pack; no external publication is claimed.
- Freshness/TTL: N/A — no current data is rendered.
- Failure/degraded behavior: routes show `No live data available`; login shows `Sign-in unavailable`; errors retain an emergency-path message.
- Runtime/demo has no mock or hard-coded current data: [x]

## How to run

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

## Verification evidence

Commands and results, run on 2026-09-21 after rebasing onto
`origin/main` `3353f158787f2d7df6b997ab8ff0aa209615e01c`:

```text
command: Dockerized packages/contracts npm run check from "How to run"
result: OpenAPI valid (2 intentional ignores); 31 schemas compiled; 6 examples
        validated; M01 TypeScript consumer compiled; 0 failures

command: Dockerized bundle + TypeScript regeneration and byte comparison
result: bundled OpenAPI and 2,829-line public-api.d.ts match committed artifacts

command: docker run --rm smart-travel-web:pr-check-contract-rebase pnpm lint
result: exit 0; 0 ESLint findings

command: docker run --rm smart-travel-web:pr-check-contract-rebase pnpm format
result: all matched files use Prettier code style

command: docker run --rm smart-travel-web:pr-check-contract-rebase pnpm typecheck
result: exit 0; 0 TypeScript findings

command: docker run --rm smart-travel-web:pr-check-contract-rebase pnpm test
result: 2 test files passed; 4 tests passed; 0 failed; 0 skipped (53.22 s)

command: docker compose -f compose.yaml -f compose.dev.yaml config --quiet
result: exit 0; rebased combined Compose configuration valid

command: docker build --target runtime --tag smart-travel-web:phase1-contract-rebase apps/web
result: Next.js 16.3.5 compiled and typechecked; 9 static pages generated; exit 0

command: docker exec smart-travel-web-contract-rebase-check id
result: uid=100(app) gid=101(app) groups=101(app)

command: curl --fail --silent --show-error http://127.0.0.1:33000/api/health
result: {"status":"ok","service":"web"}

command: docker inspect ... '{{.State.Status}} health={{.State.Health.Status}}'
result: running health=healthy

command: Dockerized Playwright command from "How to run"
result: 3 Chromium tests passed; 0 failed; 0 skipped (46.0 s)
```

- UI screenshots/video: attach `/private/tmp/web-after-login-final.png`, `/private/tmp/web-after-dashboard-final.png`, and `/private/tmp/web-after-mobile-final.png` when opening the PR.
- Sanitized curl/trace/request IDs: health JSON above; no user/API request or trace exists in this slice.
- Visual diff/accessibility result: mobile touch/keyboard and desktop navigation E2E passed; full axe/visual diff is Phase 8.
- Migration up/down result: N/A — no migration.
- Contract compatibility: current Phase 0/1 runtime does not consume API payloads; compile-time checks confirm later UI code can distinguish unevaluated routes from measured-open routes and retain unnamed emergency POIs.
- Final base freshness: `3353f15` only adds `docs/handoffs/m04-records/**`; it does not change the contract, Compose, or web inputs validated above.
- Production image: `smart-travel-web:phase1-contract-rebase`, digest `sha256:031821102a7013ea054c2a0b4adc22100d9c1b92ee64733426f94bab0815649b`, 91,716,820 bytes.

## Safety, security and privacy

- [x] Input validated at boundary — public environment values are Zod-validated; invalid/missing cases are tested.
- [ ] Timeout/cancellation/retry/idempotency handled — N/A until Phase 2 API/SSE work.
- [x] No secret, token, PII or exact location leaked to logs/fixtures.
- [ ] Provenance, timestamps, quality and version retained — N/A because no live data is rendered.
- [x] Official warning cannot be weakened — no warning processing or safety claim exists in this slice.
- [ ] LLM/provider/RAG text treated as untrusted — N/A; none is consumed.
- [ ] Consent/retention requirements implemented where applicable — N/A until location/profile features.
- [x] Error messages expose no internal stack/secret.

Local dependency/image/secret scans were not run; repository-required CI must
still pass before merge.

## Test coverage

- [x] Success path — route build, navigation, liveness, runtime health.
- [x] Invalid/unauthorized path — missing/invalid environment values; authentication is not implemented and clearly unavailable.
- [ ] Dependency timeout/429/5xx — N/A; no dependency call.
- [ ] Stale/conflicting/partial data — N/A; no current data.
- [x] Boundary values and regression case — mobile 390×844, 44 px tap target, disclosure/keyboard activation, desktop shell.
- [x] Contract test with producer/consumer — official contract check, M01 TypeScript consumer compilation, and generated TypeScript parity all passed.
- [x] E2E — 3 shell interaction cases against the production Docker image.

## Risks and limitations

- This is a navigable visual shell, not a releasable travel application: auth,
  API/SSE integration, live maps/data, consent, and safety actions are later phases.
- Phase 2+ UI code must not coerce `RouteCandidate.exposure: null` to an open
  route or discard an `EmergencyPoi` whose provider supplied no name.
- Supplied asset licensing is not stated; confirm before external publication.
- Full axe/visual/localization/200%-zoom/performance coverage remains Phase 8.
- The local development check image is 1.4 GB; the production image is 91.7 MB.

## Rollback

- Code rollback: revert the squash commit or redeploy the prior web image, then verify `/api/health` and route smoke tests.
- Database/schema rollback or forward-fix: N/A — no state or migration.
- Feature flag/provider disable path: N/A — no feature flag/provider is introduced.

## Handoff

- Completion report: `docs/handoffs/M01-web-shell.md`.
- What the next owner must do: implement only Phase 2 on `feat/01-auth-api-client`, agree browser auth/SSE handoff with M02, and preserve the no-runtime-mock rule.
- Reviewer focus areas: desktop/mobile shell semantics, explicit unavailable states, updated route/POI consumer assumptions, server/client boundary, public-only environment variables, and standalone non-root Docker runtime.
