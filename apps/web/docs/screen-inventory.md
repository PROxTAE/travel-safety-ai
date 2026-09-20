# Web screen and contract inventory

Phase 0 inventory for `feat/01-web-shell`, reviewed 2026-09-21. The supplied
screens are visual masters only: all cities, weather, risk, timing, contacts,
and availability labels shown in them are examples and must never be runtime
defaults.

## Sources reviewed

- `IMPLEMENTATION_PLANS/00_SHARED_PROJECT_CONTEXT.md`
- `IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md`
- `IMPLEMENTATION_PLANS/01_WEB_APP_IMPLEMENTATION.md`
- `assets/README.md`
- `assets/ui-screens/00-login.png` through `06-route-comparison.png`
- `packages/contracts/openapi/public-api.yaml` and generated TypeScript types

All seven screen references are RGB PNGs at 1672 × 941. Reusable branding and
mascot PNGs are RGBA. No bundled font files were found; Phase 1 uses the system
font stack until a licensed font is supplied. Asset licenses are not stated in
the pack; they remain project-supplied assets and no derivative is produced in
this phase.

## Shared visual system

| Area           | Required behavior                                                                                      | Phase |
| -------------- | ------------------------------------------------------------------------------------------------------ | ----- |
| App shell      | Fixed sidebar at desktop, header, clear active item, keyboard navigation, responsive mobile navigation | 1     |
| Status         | A persistent offline/degraded area that does not obscure Emergency                                     | 2     |
| Data freshness | Every data card exposes its `updated_at` or freshness detail                                           | 2+    |
| Maps           | Interactive MapLibre source/layers; decorative maps never represent live data                          | 3+    |
| Accessibility  | Text and icon convey risk; visible focus, semantic landmarks, WCAG 2.1 AA contrast                     | 1+    |

The required tokens are `#08B88A`, `#087B73`, `#DDF9EE`, `#F5FFFC`, `#101A4B`,
`#2F86F6`, `#FF9D1F`, and `#F24E54`. Screens consistently use rounded white
cards, mint page surfaces, navy headings, and coral only for emergency actions.

## Route inventory

| Route                           | Visible layout and interactions                                                    | Runtime data/status requirement                                                           | Delivery phase |
| ------------------------------- | ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | -------------- |
| `/login`                        | Split illustration and sign-in panel; SSO, guest and emergency entry               | Auth state and provider errors are real; emergency stays public                           | 2              |
| `/dashboard`                    | Summary cards, trip card, route map, recommendation, emergency and assistant cards | `/me`, active trip, recommendation, events; card detail sheets and unavailable states     | 4              |
| `/trips/new`, `/trips/[tripId]` | Trip form, confirmation map, mode/preferences, route cards                         | Autocomplete, confirmed locations, create/update, assessment SSE, unavailable coverage    | 3              |
| `/safety-map`                   | Layer controls, map markers/detail, time selector, avoid-area action               | Viewport/time/layer API queries, attribution, clustering, source/freshness                | 5              |
| `/assistant/[conversationId]`   | Recent chats, conversation, quick prompts, trip context, live-location control     | Conversation REST/SSE, sanitized markdown, consented location, citations                  | 6              |
| `/emergency`                    | Three-second SOS hold, confirmation progression, location, local service cards     | Consent before share; verified contacts and nearby results; explicit unavailable fallback | 7              |
| `/trips/[tripId]/compare`       | Original/safer map overlay, comparison cards, risk acknowledgement, notifications  | Server routes and metrics, confirmed route application, subscription state                | 4              |

## Contract readiness

The baseline v1 OpenAPI provides the Phase 1 external assumptions: unauthenticated
`/health/live` and `/health/ready`, bearer-token authentication for application
routes, response metadata, and the generated `RecommendationResponse` model.
It also defines later trip, location-search, assessment/SSE, recommendation,
route-application, and safety-event endpoints. `RecommendationResponse` contains
the action, risk, routes, sources, freshness, limitations, and degraded-services
fields needed by the planned UI; no field is missing for Phase 1.

Auth.js callback shape, server-side token handoff, and browser SSE authentication
are Phase 2 decisions. The browser will only call the public API and web routes.
No runtime fixture, mock switch, hard-coded conditions, or provider token is
permitted.

## Phase 1 acceptance checklist

- [x] All empty application routes render inside the responsive shell — production build generated every route and Dockerized Playwright covered mobile/desktop navigation.
- [x] Login and Emergency render without authentication — verified in the production image; authentication remains Phase 2.
- [x] Keyboard users can navigate the visible route links and focus remains clear — Playwright keyboard activation passed at the 390 px breakpoint.
- [x] Environment parsing rejects absent/invalid public API and map configuration — three Vitest cases passed.
- [x] `/api/health` returns liveness without contacting the API — returned `{"status":"ok","service":"web"}` from the production container.
- [x] Production image uses Next standalone output, runs as uid 100 `app`, and reached Docker `healthy` status.
