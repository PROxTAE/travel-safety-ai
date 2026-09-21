# [M06] Add Phase 3–8 fail-closed foundations

## Summary

Adds the Module 06 baseline-model, safety-monitoring, knowledge, route-evaluation, and release-gate foundations inside `services/risk-knowledge/`. Approval-dependent capabilities remain fail closed: no threshold, model, knowledge collection, or route coefficient is promoted or invented.

## Scope

In scope:

- Calibrated rule/logistic baselines, evaluation metrics, model card, checksum, and candidate artifact.
- Verified local inference, official-priority overrides, privacy-safe drift aggregates, and release gates.
- Approved-source PDF ingestion, procedure-aware chunks, filtered hybrid retrieval, citations, corridor geometry, hard constraints, and deterministic ranking when approved coefficients exist.
- Focused regression tests and exact Docker verification evidence.

Out of scope:

- Team Lead approval of model thresholds, artifact signatures, or route coefficients.
- Switching a Qdrant alias without an approved knowledge artifact/encoder.
- Fabricating real-provider credentials or a full-system acceptance run.
- Files outside `services/risk-knowledge/`, including the final repository handoff.

## Ownership and dependencies

- Module/owner: M06 risk-knowledge / Nonyeol.
- Depends on PR/contract: Phase 2 PR #88 is merged in `main`; shared contracts in `packages/contracts`.
- Downstream consumers: M02 API, M03 agent, M07 decision engine, M08 recommendations.
- Issue/ADR: existing M06 model/RAG/route governance records; approval decisions remain pending.

## Contract, database and configuration changes

- API/OpenAPI/JSON Schema: no shared contract change; the existing internal risk endpoint can use a verified ACTIVE predictor.
- Migration/table/index: none.
- Environment variables: none added.
- Backward compatibility/rollout: conservative fallback remains active whenever verification, quality, or approval gates fail.

## Real data and provenance

- Provider/source: consumes the Phase 2 dataset manifest and approved knowledge-source manifest only.
- Endpoint/coverage: no new live-provider call; runtime providers remain owned upstream.
- License/attribution: knowledge ingestion requires recorded authority, review approval, checksum, and HTTPS allowlist.
- Freshness/TTL: effective/expiry metadata is filtered at retrieval time.
- Failure/degraded behavior: model, RAG, evidence package, and numeric route ranking fail closed or degrade explicitly.
- ยืนยันว่า runtime/demo ไม่มี mock หรือ hard-coded current data: [x]

## How to run

```bash
docker compose run --rm risk-knowledge uv run ruff check .
docker run --rm --tmpfs /tmp:size=256m -e COVERAGE_FILE=/tmp/.coverage -v "H:/travel-safety-ai/services/risk-knowledge/app:/app/app:ro" -v "H:/travel-safety-ai/services/risk-knowledge/training:/app/training:ro" -v "H:/travel-safety-ai/services/risk-knowledge/tests:/app/tests:ro" -v "H:/travel-safety-ai/services/risk-knowledge/pyproject.toml:/app/pyproject.toml:ro" sta-risk-knowledge:phases3-8-test sh -lc "/app/.venv/bin/ruff check app training tests && /app/.venv/bin/ruff format --check app training tests && /app/.venv/bin/mypy app training && /app/.venv/bin/pytest -q --cov=app --cov-report=term"
```

## Verification evidence

Commands and results:

```text
docker compose config --quiet: passed
docker compose build risk-knowledge: passed
docker compose run --rm risk-knowledge uv run ruff check .: All checks passed
ruff format --check: 65 files already formatted
mypy: Success: no issues found in 48 source files
pytest: 80 passed, 45 warnings; total coverage 85.83% (required 80%)
credential/runtime-mock scan: no match
runtime image UID: 10001 (non-root)
```

- UI screenshots/video: N/A, internal service only.
- Sanitized curl/trace/request IDs: N/A; no live provider credentials used.
- Visual diff/accessibility result: N/A.
- Migration up/down result: N/A; no migration changed.

## Safety, security and privacy

- [x] Input validated at boundary
- [x] Timeout/cancellation/retry/idempotency handled where external ingestion applies
- [x] No secret, token, PII or exact location leaked to logs/fixtures
- [x] Provenance, timestamps, quality and version retained
- [x] Official warning cannot be weakened
- [x] LLM/provider/RAG text treated as untrusted
- [x] Consent/retention requirements implemented where applicable
- [x] Error messages expose no internal stack/secret

## Test coverage

- [x] success path
- [x] invalid/unauthorized path
- [x] dependency timeout/429/5xx
- [x] stale/conflicting/partial data
- [x] boundary values and regression case
- [x] contract test with producer/consumer
- [ ] E2E or reason N/A: blocked until approved ACTIVE model, knowledge artifact, provider credentials, and route coefficients exist.

## Risks and limitations

- `model_acceptance.yaml` is still `PENDING_TEAM_LEAD_APPROVAL`; the model remains CANDIDATE.
- Route exposure coefficients are null, so official hard constraints work but numeric ranking remains unavailable.
- No approved knowledge PDF/embedding model exists; no Qdrant active alias is switched. The auditable multilingual character-vector implementation is a temporary fallback.
- The combined evidence endpoint remains unavailable until immutable snapshot retrieval and all active dependencies exist.
- A full real-provider Phase 8 acceptance run was not fabricated.

## Rollback

- Code rollback: revert this commit.
- Database/schema rollback or forward-fix: N/A.
- Feature flag/provider disable path: omit an ACTIVE verified artifact/collection; runtime retains its conservative fallback.

## Handoff

- Completion report: `services/risk-knowledge/PHASES_3_8_REPORT.md` (kept module-local to honor this task's file boundary).
- What the next owner must do: approve/sign model thresholds and artifacts, approve route coefficients, supply an approved knowledge corpus/encoder, run real-provider Phase 8 E2E, then write the final repository handoff.
- Reviewer focus areas: fail-closed promotion, critical-evidence rejection, official hard constraints, citations/expiry filtering, deterministic ranking, and the deliberately inactive capabilities.
