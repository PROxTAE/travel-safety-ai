# [M07] Add deterministic decision engine and guarded LLM explanations

## Summary

Adds the M07 decision-engine service with approved-policy loading, deterministic action locking, structured OpenAI explanation, post-validation, fallback, Redis idempotency/cache, audit persistence, replay, red-team tests, and rollback verification.

## Scope

In scope:

- `services/decision-engine/**`
- Runtime service registration already present on this branch in Compose
- Docker test image and executable quality checks

Out of scope:

- Shared contract regeneration or edits outside the service
- Live OpenAI canary and secret provisioning
- Real cross-service E2E with modules 06 and 08
- Human policy approval and production release

## Ownership and dependencies

- Module/owner: M07 / decision-engine
- Depends on: IntegratedTravelContext/RiskAssessment evidence from modules 05/06
- Downstream consumers: agent module 03 and recommendation module 08
- Contract version: `1.0.0`

## Contract, database and configuration changes

- JSON Schema: `services/decision-engine/schemas/decision-policy.schema.json`
- Internal endpoints: `/internal/v1/decisions`, `/internal/v1/policy`, `/internal/v1/decisions/validate`, `/internal/v1/audit/{audit_id}`
- Migrations: `001_decision_audit.sql`, `002_policy_prompt_registry.sql`
- Environment: `OPENAI_API_KEY`, `OPENAI_EXPLAINER_MODEL`, `DECISION_REDIS_URL`, `DECISION_DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, policy settings
- Compatibility: additive internal endpoints; action remains the shared four-value enum

## Real data and provenance

- Provider: OpenAI Responses API, server-side only
- Structured output: strict JSON Schema, `store=false`, bounded timeout/tokens, one retry
- Degraded behavior: deterministic Thai/English fallback when key/provider/validation is unavailable
- Runtime contains no mock current conditions, hard-coded statuses, secrets, or raw provider fixtures
- Policy checksum: `8c05773a240273e4aa1cc9c3ea9a9b758cf286fcd6cedb97dcfb9a6febb7a788`

## How to run

```powershell
# Build the service test image
docker build --target test -t smart-travel-decision-engine:test-pr services/decision-engine

# Lint
docker run --rm smart-travel-decision-engine:test-pr ruff check app tests

# Typecheck
docker run --rm smart-travel-decision-engine:test-pr mypy app

# Full module tests
docker run --rm smart-travel-decision-engine:test-pr pytest -q
```

No push was performed.

## Verification evidence

```text
base: e58e57dd8c83e828e2d76082553c9e519a9f311d
head: bbf93e6eb8ddf7290801f517ad5738afacf176a5
lint: All checks passed!
typecheck: Success: no issues found in 22 source files
tests: 36 passed in 1.50s
image: sha256:a6d00448fb08abb491fe2f09d2176b6d83ea92e4956780ffbc5cdcb780c561d7
```

Migration execution against real Postgres, live OpenAI, security/image scans, and cross-service E2E are not claimed by this PR.

## Safety, security and privacy

- [x] Input and policy are validated at the boundary
- [x] Timeout, bounded retry, fallback, and idempotency are handled
- [x] No secret, token, PII, or exact location is in logs/fixtures
- [x] Policy/source/version/checksum information is retained
- [x] Official warning cannot be weakened
- [x] LLM/provider/RAG content is treated as untrusted
- [x] Errors avoid raw provider/SQL/secret details in normal paths
- [ ] Human approval, live canary, security scan, and cross-service E2E remain

## Test coverage

- [x] Success and all four actions
- [x] Invalid/ inconsistent inputs and unauthorized policy boundary tests
- [x] LLM refusal/incomplete/invalid output and deterministic fallback
- [x] Stale/conflicting evidence and low confidence
- [x] Threshold boundaries and Hypothesis monotonicity
- [x] Cache/idempotency replay and conflict
- [x] Adversarial injection/hallucinated action/citation/number
- [x] Rollback checksum and sanitized audit replay
- [ ] Real producer/consumer contract E2E — N/A in service-only preparation

## Risks and limitations

- Policy approval record is `PENDING_REVIEW`; production activation must remain blocked.
- `DECISION_REDIS_URL` is optional; without it cache is disabled, while deterministic decisions remain available.
- OpenAI live behavior and cost/latency have not been measured without credentials.
- Modules 06/08 integration and Postgres migration canary remain required before merge.

## Rollback

- Code: revert/squash rollback of the PR commit range.
- Database: use forward-fix/approved rollback migration; do not delete volumes.
- Policy: verify prior checksum and `APPROVED` status via `app/policy/rollback.py` before activation.
- Provider: disable `OPENAI_EXPLAINER_ENABLED`; deterministic fallback remains active.

## Handoff

- Completion report: `docs/handoffs/M07-decision-llm.md`
- Reviewer focus: action-lock invariant, policy checksum/approval status, LLM validator allowlists, Redis idempotency races, audit replay redaction, migration behavior.
- Next owner actions: obtain required policy approvals, run Postgres/Redis/OpenAI canaries, connect modules 06/08, run security/image/secret scans, then update this PR evidence.
