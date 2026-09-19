# Field ownership matrix — contract v1.0.0

Who is allowed to write each part of the shared contract, and who only reads it. Written as step 1
of Phase 0 in [`02_API_BACKEND_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md).

The point is narrow but load-bearing: eight modules are built in parallel against one set of
entities, and the expensive failure mode is two owners quietly disagreeing about who decides a
field's meaning. A field with one writer has one definition. A field with two has two, and the bug
surfaces at integration time when everything is already built.

## How to read this

- **Producer** — the module that fills the field in. Changing its meaning is that module's call.
- **Consumers** — modules that read it. They are review-required on any change and must not
  re-derive the value locally.
- Schemas live in `packages/contracts/jsonschema/common/`; the public API in
  `packages/contracts/openapi/public-api.yaml`.

Module numbers follow `00_SHARED_PROJECT_CONTEXT.md` §6: 01 web, 02 api, 03 agent,
04 external-data, 05 data-integration, 06 risk-knowledge, 07 decision-engine, 08 recommendation.

## Entities

| Entity | Producer | Consumers | Notes |
| --- | --- | --- | --- |
| `UserProfile`, `ConsentRecord`, `EmergencyProfile` | 02 | 01, 08 | Only 02 writes `identity`. 08 reads consent through 02's API, never the tables. |
| `Trip` | 02 | 01, 03 | `revision` and `selected_route_id` are set by 02 alone; a client cannot assert either. |
| `TravelRequest` | 02 | 03, 05 | 02 normalises locale, timezone and modes before the agent sees them. |
| `RunRef`, `RunState` | 02 | 01 | 02 owns the public run state; 03 owns the internal one and 02 projects it. |
| `LocationRef` | 04 | 01, 02, 05 | 04 produces it from a geocoding provider; 02 proxies. `confirmed_by_user` is set by 01 and enforced by 02. |
| `SourceProvenance` | 04 | all | Every module attaches it; only 04 mints one from a provider fetch. |
| `DataQuality` | 05 | 06, 07, 08, 01 | `formula_version` belongs to 05; consumers read flags, never recompute the score. |
| `WeatherForecastPoint`, `WeatherObservation` | 04 → 05 | 06, 07 | 04 normalises per provider, 05 makes it canonical and deduplicates. |
| `TransportStatus` | 04 → 05 | 06, 07, 01 | `ON_TIME` may only be set from real-time evidence. |
| `DisasterEvent` / official alert | 04 → 05 | 06, 07, 08, 01 | An active official alert may not be removed by any downstream module. |
| `RouteCandidate` | 04 → 06 | 07, 08, 01 | 04 returns provider geometry; 06 evaluates and ranks. `exposure.closed` is 06's to set. |
| `IntegratedTravelContext` | 05 | 06, 07 | Immutable. A refresh is a new `snapshot_id` with `supersedes_snapshot_id`. |
| `RiskAssessment` | 06 | 07 | `reason_codes` is a controlled vocabulary in the contract, not free text. |
| `RetrievedEvidence` | 06 | 07, 08 | Below the retrieval threshold no passage is returned at all. |
| `DecisionResult` | 07 | 08, 02 | `action_code` is locked before the LLM is called. |
| `RecommendationResponse` | 08 | 02, 01 | 02 revalidates against the schema before it reaches the browser. |
| `OfficialContact` | 08 | 02, 01 | From a reviewed directory only. Never from a model, never from a neighbouring country. |
| `EmergencyPoi` | 04 | 02, 01 | A navigation aid, not a phone directory. |
| `SafetyEvent` | 05 | 02, 01 | Map projection of a canonical event. |
| `Conversation` | 03 | 02, 01 | 02 exposes summaries; transcripts stay internal. |
| `FeedbackEvent`, `AlertSubscription` | 08 | 02, 01 | 02 checks ownership and consent before proxying. |
| Envelope (`meta`, `page`, `error`) | 02 | all | 02 maintains the shape; every service emits it. |
| SSE event payloads | 02 | 01 | 02 translates agent progress into the public event contract. |

## Fields with a single writer, called out

These are the ones where a second writer would be a safety problem rather than a merge conflict.

| Field | Only writer | Why it matters |
| --- | --- | --- |
| `DecisionResult.action_code` | 07 | The action is decided from evidence by policy, before any language model runs. Nothing downstream may change it, and `validation.locked_action` records that it did not. |
| `RouteCandidate.exposure.closed` | 06 | Derived from an official closure intersecting the corridor. A closed route can never be recommended, and no user acknowledgement overrides it. |
| `DisasterEvent.official` | 04 | Decides whether the record gets official-source priority in the decision policy. |
| `Trip.revision` | 02 | The basis of optimistic concurrency. If anything else incremented it, two tabs could overwrite each other silently. |
| `Trip.selected_route_id` | 02 | Set only by apply-route, after the server has checked the route is not closed. |
| `ConsentRecord.granted` / `revoked_at` | 02 | The record of what the user agreed to. Append-only so it stays auditable. |
| `SourceProvenance.observed_at` | 04 | Null when the provider publishes no observation time. Substituting `fetched_at` would make stale data look current, which is the failure mode this system exists to avoid. |
| `DataQuality.formula_version` | 05 | Without it, a score cannot be compared across time. |

## Shared surfaces and who reviews them

| Surface | Maintainer | Review also required from |
| --- | --- | --- |
| `packages/contracts/jsonschema/common/**` | 02 | Every module that produces or consumes the entity |
| `packages/contracts/openapi/public-api.yaml` | 02 | 01, 03, 08 |
| `packages/contracts/generated/**` | nobody — generated | n/a; CI fails if it does not match the source |
| `compose*.yaml`, `.env.example`, `.github/**` | lead | affected owner |
| Migrations touching another module's schema | forbidden without an ADR | lead |

## Contract version

`1.0.0`. Adding an optional field is a minor change. Renaming a field, changing its type, making it
required, or removing an enum member is breaking and needs `/v2` or a deprecation window with an
adapter — see `00_GIT_DOCKER_DELIVERY_RULES.md` §7.
