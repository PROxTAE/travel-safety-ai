# [M07] Decision and LLM Engine Completion Report

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | M07 / decision-engine |
| Issue/PR | N/A — PR draft prepared locally |
| Branch | `feat/07-decision-policy` |
| Base/final commit SHA | `e58e57d` / `bbf93e6` |
| Date/time/timezone | 2026-09-22 / local workspace time |
| Reviewers | Pending: Team Lead, risk-knowledge owner, recommendation owner |
| Contract version | `1.0.0` |
| Docker image digest/tag | `smart-travel-decision-engine:test-pr`; `sha256:a6d00448fb08abb491fe2f09d2176b6d83ea92e4956780ffbc5cdcb780c561d7` |
| Related policy/prompt version | Policy `1.0.0`; prompt `1.0.0`; approval `PENDING_REVIEW` |

## 2. Executive summary

This branch adds a deterministic, versioned decision boundary for `NORMAL`, `CHANGE_ROUTE`, `DELAY`, and `AVOID`. It validates policy structure and checksum, records audit traces, and keeps the action locked before explanation. The LLM path uses a versioned strict Jinja prompt and OpenAI Responses structured output with `store=false`; invalid, refused, incomplete, or unavailable output falls back to localized deterministic text. Redis-backed idempotency and explanation caching are optional and degraded safely when unavailable. Red-team, rollback, audit replay, and local acceptance tests pass in Docker. Human policy approval, live OpenAI canary, and cross-service E2E with modules 06/08 remain outstanding, so this branch is not release-ready.

## 3. Original responsibility and acceptance criteria

- [x] Deterministic policy and official closure priority — `app/policy/evaluator.py`, Docker tests.
- [x] Versioned policy schema/checksum/registry — `policies/`, `schemas/`, Phase 0 tests.
- [x] Input consistency, confidence, escalation, threshold and monotonic tests — Phase 2 tests.
- [x] Structured LLM explanation with strict schema and fallback — `app/llm/`, Phase 3 tests.
- [x] Idempotency/cache/validation/metrics — `app/cache.py`, `app/main.py`, Phase 4 tests.
- [x] Red-team and rollback drill — `tests/test_phase5_redteam.py`.
- [x] Sanitized audit replay and local acceptance — `app/repositories/replay.py`, Phase 6 tests.
- [ ] Human approval — approval record remains `PENDING_REVIEW`.
- [ ] Real E2E with modules 06/08 — requires dependency services and integration scope.
- [ ] Final handoff/release readiness — blocked by the two items above and security/image scans.

## 4. What was implemented

| Feature | Behavior now | Entry point | Status |
| --- | --- | --- | --- |
| Deterministic policy | First-match priority, official closure override, conservative inconsistency handling | `POST /internal/v1/decisions` | Complete locally |
| LLM explanation | Strict structured output, locked action/reasons/citations, one retry | `app/llm/service.py` | Complete without live provider |
| Fallback | Thai/English deterministic summary when LLM is disabled or fails | `app/llm/fallback.py` | Complete |
| Cache/idempotency | Redis TTL cache and replay/conflict handling | `DECISION_REDIS_URL`, `Idempotency-Key` | Complete with optional Redis |
| Audit replay | Sanitized IDs/hashes/versions/rules only | `GET /internal/v1/audit/{audit_id}` | Complete |

Flow: input -> policy/schema/consistency validation -> deterministic lock -> optional Redis lookup -> explanation/fallback -> audit persistence -> validated result.

Explicitly not implemented: live provider canary, production policy approval, cross-service E2E, final handoff document outside this branch scope, security/image scan evidence, and runtime secret provisioning.

## 5. Architecture and design

| Path | Purpose |
| --- | --- |
| `services/decision-engine/app/policy/` | Policy loading, evaluation, confidence, escalation, rollback |
| `services/decision-engine/app/llm/` | Prompt, evidence package, OpenAI client, validator, fallback |
| `services/decision-engine/app/cache.py` | Canonical hash, Redis cache, idempotency |
| `services/decision-engine/app/repositories/` | Audit, migrations, sanitized replay |
| `services/decision-engine/migrations/` | Audit and policy/prompt registry tables |
| `services/decision-engine/tests/` | Unit, property, adversarial, acceptance tests |

The safety trade-off is fail conservative: no approved policy, inconsistent input, low-quality evidence, unavailable LLM, or invalid LLM output cannot weaken the locked action.

## 6. API, contract and event changes

| Producer | Method/path | Response | Consumer | Compatibility |
| --- | --- | --- | --- | --- |
| decision-engine | `POST /internal/v1/decisions` | `DecisionResult` v1 | Agent/recommendation | Existing v1 shape |
| decision-engine | `GET /internal/v1/policy` | Policy metadata | Internal operators | Additive |
| decision-engine | `POST /internal/v1/decisions/validate` | Validation flags | Internal consumers | Additive |
| decision-engine | `GET /internal/v1/audit/{audit_id}` | Sanitized replay | Operators | Additive |

Policy schema is local to the owned service because shared contract files are outside the requested scope. No shared contract file was modified.

## 7. Database, cache and storage changes

| Revision | Tables/indexes | Upgrade |
| --- | --- | --- |
| `001_decision_audit.sql` | `decision.audit_events`, request index | Idempotent startup migration |
| `002_policy_prompt_registry.sql` | Policy/prompt versions and one-approved indexes | Idempotent startup migration |

Redis keys: `decision:explanation:<sha256>` and `decision:idempotency:<Idempotency-Key>`, default TTL 300 seconds. Redis is not the system of record. Audit stores hashes and rule trace, not raw prompt or chain-of-thought.

## 8. External providers and real data

OpenAI Responses API is configured server-side through `OPENAI_API_KEY` and `OPENAI_EXPLAINER_MODEL`; no credential or live call was used in tests. Runtime has deterministic fallback when the provider is unavailable. No mock current conditions or provider response fixtures were added.

## 9. Configuration and Docker

| Variable | Required | Secret | Failure behavior |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | No | Yes | Deterministic fallback |
| `OPENAI_EXPLAINER_MODEL` | No | No | Defaults to configured model |
| `DECISION_REDIS_URL` | No | No | Cache disabled/degraded |
| `DECISION_DATABASE_URL` | Production | Yes | Readiness not ready |
| `DECISION_POLICY_CHECKSUM` | No | No | Policy load failure if mismatch |
| `INTERNAL_SERVICE_TOKEN` | Production | Yes | Internal auth unavailable |

Exact verification commands:

```powershell
docker build --target test -t smart-travel-decision-engine:test-pr services/decision-engine
docker run --rm smart-travel-decision-engine:test-pr ruff check app tests
docker run --rm smart-travel-decision-engine:test-pr mypy app
docker run --rm smart-travel-decision-engine:test-pr pytest -q
```

The runtime image uses non-root UID 10001, exposes port 8005, and has a liveness healthcheck. Production Compose does not publish a host port for the service.

## 10. Tests and verification

| Test type | Command | Passed | Failed | Evidence |
| --- | --- | ---: | ---: | --- |
| Lint | `docker run --rm smart-travel-decision-engine:test-pr ruff check app tests` | pass | 0 | `All checks passed!` |
| Type | `docker run --rm smart-travel-decision-engine:test-pr mypy app` | 22 files | 0 | `Success: no issues found in 22 source files` |
| Unit/property/adversarial | `docker run --rm smart-travel-decision-engine:test-pr pytest -q` | 36 | 0 | `36 passed in 1.50s` |
| Contract | Included in pytest policy schema tests | pass | 0 | Phase 0 tests |
| Integration/E2E | Not run | 0 | N/A | Modules 06/08 not connected |
| Security/image/secret scan | Not run | N/A | N/A | Required follow-up |

Verified scenarios include official closure priority, malformed/mismatched inputs, threshold boundaries, monotonic risk, LLM refusal/incomplete/invalid output, forged action/citation/number, injection isolation, cache/idempotency conflict, fallback, rollback checksum, and sanitized replay.

## 11. Safety, security and privacy review

- [x] Official warning/closure priority preserved
- [x] LLM/provider/RAG text treated as untrusted
- [x] No secret/PII/exact location in code/log/fixture
- [x] Timeout, bounded retry, idempotency and fallback implemented
- [x] Provenance/version/checksum retained
- [x] Fallback does not invent data
- [ ] Dependency/image/secret scans passed — not run in this local preparation

## 12. Problems and known limitations

| Problem | Resolution | Remaining risk |
| --- | --- | --- |
| Host lacked uv/pytest | Docker test stage added and used | CI must run equivalent image checks |
| Policy checksum changed after formatting | Registry/approval checksum refreshed and tested | Human approval still required |
| Live OpenAI not available | Provider-free mocks and deterministic fallback tests | Live API canary still needed |
| Cross-service dependencies unavailable in service-only scope | Local contract-shaped tests only | Modules 06/08 E2E remains blocking |

## 13. Handoff and rollback

- Policy approval: review `services/decision-engine/policies/v1/POLICY.md` and `approval-record.yaml`; required reviewers are Team Lead, risk-knowledge owner, recommendation owner.
- Rollback: verify previous registry entry checksum/status, then activate atomically; never delete database volumes.
- Cache cleanup: expire only namespaced Redis keys after confirming the input hash/version.
- Next owners: run migration against empty and existing Postgres, configure Redis/OpenAI secrets, execute live provider canary, and run modules 06/08 E2E.

## 14. Commit inventory

```text
bbf93e6 chore(decision): pass docker quality checks
0d4760c feat(decision): add sanitized audit replay
36840b3 test(decision): add redteam and rollback drills
132b994 feat(decision): add idempotent decision caching
fefe202 feat(decision): add structured llm explainer
3d276fe fix(decision): derive rule traces from policy
432b8d7 feat(decision): add policy registry migrations
924b50d docs(decision): specify policy v1 governance
a9a5dc7 feat(decision): complete deterministic evaluator phase
3e99e4f feat(decision): persist decision audit events
868be2f feat(decision): add approved deterministic policy engine
```

## 15. Final declaration

- [x] In-scope service implementation has executable evidence
- [x] No required limitations are hidden
- [x] Service docs/config/contracts/migrations are updated
- [ ] Human policy approval and cross-service E2E remain before merge/release

Prepared by: GitHub Copilot
Reviewers: Pending
Date: 2026-09-22
