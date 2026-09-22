# [M08] Implement Recommendation Delivery, Verified Directory, and Feedback Governance Layer

## Summary
Implements Module 08 end-to-end:
1. **Deterministic Final Recommendation Construction**: Assembles customer-facing responses from decision outputs, route candidates, hazard context, and emergency contacts with strict `locked_action` verification and immutable persistence.
2. **Verified Official Emergency Directory**: Maintains an authoritative emergency directory (`emergency-directory/sources.yaml`) with official Thailand numbers (191, 1155, 1669, 199, 1784), checksum validation, and review schedules.
3. **Governed Feedback & Safety Review Queue**: Captures user feedback with automated PII redaction (phones, emails, coordinates), routes critical safety issues (`UNSAFE`, `INCORRECT`, `ROUTE_ISSUE`) to an operator review queue, and enables pseudonymized dataset export for offline model evaluation (zero live online retraining).
4. **Live Alert Subscriptions & Delivery**: Evaluates hazard reassessments with cooldown tracking, ensuring **higher severity escalations bypass cooldowns unconditionally**, with multi-channel dispatchers (Redis in-app, WebPush, Email, SMS).

---

## Scope

### In scope:
- OpenAPI 3.1 contract (`packages/contracts/openapi/internal-recommendation.yaml`)
- Alembic database migration for PostgreSQL `recommendation` schema (6 tables)
- Fast, deterministic recommendation builder enforcing decision immutability
- Emergency directory YAML validation and multilingual contact resolver
- Feedback repository, PII scrubbing, safety queue state machine, and offline export CLI
- Alert subscription manager, meaningful change detector, and channel dispatchers
- Internal FastAPI service with `/health/live`, `/health/ready`, `/metrics`, and `/internal/v1` routes
- Docker Compose topology integration (`compose.yaml` and `compose.dev.yaml` port 8006)
- Comprehensive test suite (30 unit, contract, and integration tests passing)

### Out of scope:
- Live online retraining of upstream ML models (governed offline dataset export used instead).
- Upstream decision logic implementation (owned by Module 07).

---

## Ownership and dependencies
- **Module/owner**: Module 08 (`services/recommendation`)
- **Depends on PR/contract**: Contract v1.0.0 (`internal-recommendation.yaml`), Module 07 Decision Contract (Mock-free contract validation)
- **Downstream consumers**: Module 02 (`api`), Frontend (`web`)

---

## Contract, database and configuration changes
- **API**: Internal OpenAPI 3.1 spec added at `packages/contracts/openapi/internal-recommendation.yaml`
- **Database Schema**: `recommendation` schema with tables `recommendations`, `feedback`, `safety_review_queue`, `subscriptions`, `delivery_log`, `emergency_contacts`
- **Configuration**: `PORT=8006`, `POSTGRES_SCHEMA=recommendation`, `REDIS_URL=redis://redis:6379/0`, `EMERGENCY_DIRECTORY_PATH=/app/emergency-directory/sources.yaml`
- **Docker Topology**: Added `recommendation` service to `compose.yaml` and `compose.dev.yaml`

---

## Real data and provenance
- Verified Official Emergency Contacts:
  - 191 (Royal Thai Police) — Authority: OFFICIAL
  - 1155 (Tourist Police Bureau) — Authority: OFFICIAL
  - 1669 (National Institute for Emergency Medicine) — Authority: OFFICIAL
  - 199 (Department of Disaster Prevention & Mitigation Fire & Rescue) — Authority: OFFICIAL
  - 1784 (DDPM National Disaster Warning) — Authority: OFFICIAL
- Zero mock / fake runtime data: [x] Confirmed. Missing country coverage returns structured limitation (`UNSUPPORTED_EMERGENCY_DIRECTORY_COVERAGE`).

---

## How to run

```bash
# Run pytest test suite
cd services/recommendation
uv run python -m pytest -v

# Run lint and type checking
uv run ruff check .
uv run mypy app

# Verify emergency directory
uv run recommendation-verify-directory --path emergency-directory/sources.yaml

# Check contracts
cd ../../packages/contracts
npm run check
```

---

## Verification evidence

```text
command: uv run python -m pytest -v
result: 30 passed in 9.57s

command: uv run ruff check .
result: All checks passed!

command: uv run mypy app
result: Success: no issues found in 37 source files

command: npm run check (in packages/contracts)
result: 31 schemas compiled, 7 examples validated, 0 lint errors
```

---

## Safety, security and privacy
- [x] Input validated at boundary with Pydantic v2
- [x] Official closure/warning priority preserved
- [x] Decision `locked_action` verification prevents downstream tampering
- [x] Zero secrets, tokens, PII or raw coordinates logged or stored in feedback
- [x] Escalation to higher severity is never suppressed by cooldown
- [x] Feedback routed to operator review queue without live online model retraining
- [x] Error messages adhere to standard error envelopes without leaking stack traces

---

## Test coverage
- [x] Success path (normal, change route, avoid actions)
- [x] Invalid / tampered decision path (`locked_action == False` rejected with 422)
- [x] Cooldown suppression and higher-severity escalation bypass
- [x] Emergency directory expiration and missing coverage fallback
- [x] Feedback PII redaction and safety review state machine transitions
- [x] Offline pseudonymized feedback dataset export CLI
- [x] Health and readiness probes (`/health/live`, `/health/ready`)

---

## Rollback
- **Code rollback**: Revert merge commit on `main`.
- **Database rollback**: `alembic downgrade base` (drops `recommendation` schema tables).
- **Service disable**: Remove `recommendation` from Docker Compose app profile.

---

## Handoff
- Completion report: `docs/handoffs/M08-recommendation-feedback.md`
- Module 07 handoff notes: Ensure decision engine emits payload satisfying `validation.locked_action == True` and conforms to contract schema.
