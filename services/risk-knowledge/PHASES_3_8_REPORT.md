# M06 Phases 3–8 implementation report

## Implemented

- Calibrated leakage-safe logistic baseline, rule baseline, metrics, subgroup evaluation,
  threshold-boundary analysis, linear-SHAP reason validation, model card, checksum and
  reproducible candidate artifact.
- Fail-closed promotion gates and verified local inference with strict feature-schema and
  critical-quality validation.
- Versioned official-priority overrides and privacy-safe drift aggregates without automatic
  retraining, feedback recall proxy, and explicit model rollback.
- Approved HTTPS/PDF/checksum ingestion, procedure-preserving chunks, effective/expiry filters,
  hybrid BM25 plus multilingual character-vector retrieval, Qdrant versioned collection
  build/release/rollback, and resolvable citations.
- Full-corridor geometry/time intersection, official hard constraints and deterministic ranking
  when approved numeric coefficients exist.
- `/risk/assess`, `/knowledge/retrieve`, and `/routes/evaluate` use the implemented pipelines.
  `/evidence/package` reads one immutable M05 snapshot and runs independent model, RAG, and route
  work concurrently with explicit partial/degraded semantics and version reporting.
- Release gate validates active stage, model-card safety language, golden cases, citation/route
  safety, resource/concurrency evidence, rollback, and checksums.

## Verification

```text
docker compose run --rm risk-knowledge uv run ruff check .
All checks passed!

ruff format --check: 71 files already formatted
mypy: Success: no issues found in 53 source files
pytest: 87 passed; coverage 83.51% (gate 80%)
```

## Deliberately not activated

- `model_acceptance.yaml` is still `PENDING_TEAM_LEAD_APPROVAL` and its safety thresholds are
  null. The model remains CANDIDATE; APPROVED/ACTIVE is rejected without approved thresholds,
  approver identity, timestamp and artifact signature.
- Route exposure coefficients are still null and cross-module approval is pending. Official hard
  constraints work, but numeric ranking remains unavailable instead of inventing coefficients.
- No approved knowledge PDF artifact/embedding model has been supplied, so no Qdrant active alias
  is switched. The implementation uses an auditable multilingual character-vector fallback and
  rejects unapproved encoder names.
- The combined endpoint is implemented and returns independently degraded subparts. Its production
  ACTIVE path still requires an accessible immutable M05 snapshot, approved model/collection, and
  approved route coefficients.
- The sanitized real-provider snapshot flow is covered. A live external-provider acceptance run
  cannot be executed without deployment credentials and approved artifacts; the release gate
  requires that evidence before declaring production readiness.

## Rollback

Revert this commit. Runtime continues using the existing deterministic fallback whenever no
verified ACTIVE model or knowledge collection is available.
