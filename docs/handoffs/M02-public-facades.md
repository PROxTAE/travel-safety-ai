# [M02] Public API facades & remaining endpoints — completion report

Covers Phase 6 (items 1 to 5) of `IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`: recommendations fetch and route selection, conversation histories and follow-ups, map viewport safety events, reviewed emergency directory and nearby places, and traveller feedback and alert subscriptions.

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 02 — API and backend |
| Issue/PR | PR #31 (`feat/02-public-facades`) |
| Branch | `feat/02-public-facades` |
| Base/final commit SHA | rebased on `origin/main`; PR #31 |
| Date/time/timezone | 2026-09-21, Asia/Bangkok |
| Reviewers | Lead; owner 01 (Web App), owner 03 (Agent), owner 04 (External Data), owner 08 (Recommendation) |
| Contract version | `1.0.0` |
| Docker image digest/tag | `smart-travel-api:dev` / `smart-travel-api:runtime` |
| Related model/policy/prompt/collection version | Contract v1.0.0 (`packages/contracts`) |

## 2. Executive summary

Phase 6 of module 02 (Public API) implements the remaining public facades and integrates with module 03 (Agent), module 04 (External Data), and module 08 (Recommendation & Decision Engine).

- **Recommendations (`GET /api/v1/recommendations/{id}`)**: Revalidates stored payload against schema contract, enforces caller ownership, and exposes degraded dependency status.
- **Route Selection (`POST /api/v1/trips/{id}/apply-route`)**: Implements optimistic concurrency with `If-Match`, checks route closures (`422 PolicyValidationFailed`), requires risk acknowledgement for medium/high/critical risk routes (`422 PolicyValidationFailed`), bumps trip revision, and kicks off background agent assessment runs.
- **Conversations (`GET /api/v1/conversations`, `POST /api/v1/conversations/{id}/messages`)**: Provides user-scoped conversation listings and follow-up question endpoints with idempotency and agent run orchestration.
- **Safety Events (`GET /api/v1/safety/events`)**: Validates viewport bounding box ranges (`[-180, 180]`, `[-90, 90]`, `south <= north`), filters layers (`WEATHER`, `DISASTER`, `TRANSPORT`, `OFFICIAL_ALERT`), and proxies to external-data service.
- **Emergency Services (`GET /api/v1/emergency/contacts`, `GET /api/v1/emergency/nearby`)**: Provides static reviewed official emergency numbers by coordinate bounding box, and queries nearby emergency facilities gated on active `LOCATION_ONCE` or `LOCATION_LIVE` consent (returning `403 Forbidden` if missing).
- **Feedback & Alert Subscriptions (`POST /api/v1/feedback`, `POST /api/v1/alert-subscriptions`, `DELETE /api/v1/alert-subscriptions/{id}`)**: Redacts sensitive PII (emails, phone numbers, GPS coordinates) from user feedback before forwarding to module 08, and manages trip alert subscriptions with active `ALERT_NOTIFICATION` consent checks.

Ready to merge into main.

## 3. Original responsibility and acceptance criteria

### Phase 6 — Remaining public facades (items 1–5)

- [x] **Item 1: Recommendations & Apply Route**
  - `GET /api/v1/recommendations/{id}` with schema contract revalidation & ownership isolation.
  - `POST /api/v1/trips/{id}/apply-route` with `If-Match` revision concurrency, route closure check, risk acknowledgement check, and background agent run kick-off.
- [x] **Item 2: Conversations**
  - `GET /api/v1/conversations` user-scoped listing.
  - `POST /api/v1/conversations/{id}/messages` with `Idempotency-Key` and agent run initiation.
- [x] **Item 3: Safety Events**
  - `GET /api/v1/safety/events` with bounding box validation, layer filtering, and module 04 integration.
- [x] **Item 4: Emergency Contacts & Nearby Facilities**
  - `GET /api/v1/emergency/contacts` reviewed official emergency contacts dataset with coordinate bounds.
  - `GET /api/v1/emergency/nearby` module 04 places proxy with mandatory `LOCATION_ONCE`/`LOCATION_LIVE` consent check.
- [x] **Item 5: Feedback & Alert Subscriptions**
  - `POST /api/v1/feedback` with regex-based PII redaction and audit logging.
  - `POST /api/v1/alert-subscriptions` with `ALERT_NOTIFICATION` consent check.
  - `DELETE /api/v1/alert-subscriptions/{id}` cancellation forwarding.

## 4. What was implemented

### Features

| Feature | Behavior now | Entry point | Status |
| --- | --- | --- | --- |
| Recommendation Retrieval | Validates recommendation by ID, checks trip owner | `GET /api/v1/recommendations/{id}` | Complete |
| Route Selection | Applies route, checks closure & risk acknowledgement | `POST /api/v1/trips/{id}/apply-route` | Complete |
| Conversation History | Returns user conversations | `GET /api/v1/conversations` | Complete |
| Conversation Messages | Sends question, creates assessment run | `POST /api/v1/conversations/{id}/messages` | Complete |
| Safety Events Viewport | Queries hazards in bounding box | `GET /api/v1/safety/events` | Complete |
| Emergency Directory | Returns verified country emergency numbers | `GET /api/v1/emergency/contacts` | Complete |
| Emergency Nearby Places | Queries nearby facilities with consent check | `GET /api/v1/emergency/nearby` | Complete |
| Feedback Submission | Redacts PII, forwards to module 08 | `POST /api/v1/feedback` | Complete |
| Alert Subscription | Subscribes to trip alerts with consent | `POST /api/v1/alert-subscriptions` | Complete |
| Alert Cancellation | Deletes alert subscription | `DELETE /api/v1/alert-subscriptions/{id}` | Complete |

### Important flows

1. **Apply Route Flow**:
   ```text
   Caller -> If-Match check -> Trip ownership check -> Recommendation lookup -> Closed route check (422) -> Risk level check (422 if not acknowledged) -> Bump revision -> Create & start assessment run (202 Accepted)
   ```
2. **Nearby Emergency Facilities Flow**:
   ```text
   Caller -> Active LOCATION_ONCE / LOCATION_LIVE consent check in DB (403 if absent) -> External Data Client (places_nearby) -> EmergencyPoiModel mapping -> DataResponse
   ```
3. **Feedback Flow**:
   ```text
   Caller -> Ownership check -> Regex PII redaction (email, phone, lat/lon) -> Idempotency check -> Forward to Recommendation Client -> Audit write -> DataResponse (201/200)
   ```

### What is explicitly not implemented (Out of Scope for Phase 6)

- **Phase 7**: Redis token-bucket per-route & per-principal rate limiting middleware, circuit breaker, distributed tracing headers (`traceparent`).
- **Phase 8**: Full load testing (Locust) and E2E production staging verification.

## 5. Actual architecture and code design

### Folder/file map

| Path | Purpose | Important owner/consumer |
| --- | --- | --- |
| `services/api/app/api/v1/recommendations.py` | Recommendation inspection facade | Web App (01) |
| `services/api/app/api/v1/trips.py` | Route selection endpoint | Web App (01) |
| `services/api/app/api/v1/conversations.py` | Conversation summaries & message turns | Web App (01), Agent (03) |
| `services/api/app/api/v1/safety.py` | Viewport hazard events | Web App (01), External Data (04) |
| `services/api/app/api/v1/emergency.py` | Emergency contacts and nearby facilities | Web App (01), External Data (04) |
| `services/api/app/api/v1/feedback.py` | Feedback and alert subscriptions | Web App (01), Recommendation (08) |
| `services/api/app/domain/emergency_directory.py` | Reviewed official emergency contacts | Emergency facade |
| `services/api/app/clients/external_data.py` | Module 04 HTTP client | External Data facade |
| `services/api/app/clients/recommendation.py` | Module 08 HTTP client | Recommendation & Feedback facade |
| `services/api/tests/test_phase6_facades_http.py` | Integration tests for Phase 6 | CI / Testing |

### Main components & functions

- `EmergencyDirectory`: In-memory reviewed emergency contact numbers with geographical coordinate bounding box resolution.
- `_parse_and_validate_bbox`: Viewport parser with boundary checks (`[-180, 180]`, `[-90, 90]`, `south <= north`).
- `redact_pii`: Regex sanitizer replacing emails, phone numbers, and coordinates with `[REDACTED_*]`.

## 6. API, contract and event changes

| Producer | Method/path | Request schema | Response schema | Consumer | Compatibility |
| --- | --- | --- | --- | --- | --- |
| 02 | `GET /api/v1/recommendations/{id}` | N/A | `RecommendationResponseModel` | 01 | Public v1 |
| 02 | `POST /api/v1/trips/{id}/apply-route` | `ApplyRouteRequest` | `ApplyRouteResponse` | 01 | Public v1 |
| 02 | `GET /api/v1/conversations` | N/A | `ConversationListResponse` | 01 | Public v1 |
| 02 | `POST /api/v1/conversations/{id}/messages` | `PostMessageRequest` | `RunRefResponse` | 01 | Public v1 |
| 02 | `GET /api/v1/safety/events` | Query params | `SafetyEventListResponse` | 01 | Public v1 |
| 02 | `GET /api/v1/emergency/contacts` | Query params | `DataResponse[list[OfficialContactModel]]` | 01 | Public v1 |
| 02 | `GET /api/v1/emergency/nearby` | Query params | `DataResponse[list[EmergencyPoiModel]]` | 01 | Public v1 |
| 02 | `POST /api/v1/feedback` | `CreateFeedbackRequest` | `DataResponse[FeedbackEventModel]` | 01 | Public v1 |
| 02 | `POST /api/v1/alert-subscriptions` | `CreateAlertSubscriptionRequest` | `DataResponse[AlertSubscriptionModel]` | 01 | Public v1 |
| 02 | `DELETE /api/v1/alert-subscriptions/{id}` | N/A | HTTP 204 No Content | 01 | Public v1 |

## 7. Database and cache changes

- Utilizes existing database models: `Trip`, `AssessmentRequest`, `Consent`, `AuditLog`, `IdempotencyRecord`.
- Redis channels utilised for event announcements: `agent:requests:accepted`.

## 8. External providers and real data

- Emergency directory: Verified national emergency numbers (Thailand: 191 Police, 1669 Medical, 199 Fire, 1155 Tourist Police, etc.) with explicit review due dates (`review_due_at: 2027-01-01`).
- External Data (04): Disaster and places queries proxied to internal service endpoints.
- Recommendation (08): Feedback and alert subscriptions proxied to internal service endpoints.
- Confirmed zero mocks in application runtime code.

## 9. How to run

```bash
# Lint check with ruff
docker compose -f compose.yaml -f compose.dev.yaml run --no-deps --rm api uv run ruff check .

# Type check with mypy
uv run --directory services/api mypy app

# Run full test suite
uv run --directory services/api pytest
```

## 10. Tests and verification

- `docker compose run --rm api uv run ruff check .`: **0 errors** (All checks passed)
- `uv run mypy app`: **0 errors** (Success: no issues found in 84 source files)
- `uv run pytest`: **502 passed**, 13 skipped
- `test_phase6_facades_http.py`: **9 passed**
- `test_contract_parity.py`: **49 passed**
- `@smart-travel/contracts` npm check: 31 schemas compiled, 6 examples validated, tsc passed.
