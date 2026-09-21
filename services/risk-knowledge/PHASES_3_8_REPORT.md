# M06 Phases 3–8 implementation report

## Implemented

- Calibrated leakage-safe logistic baseline, rule baseline, metrics, subgroup evaluation,
  model card, checksum and reproducible candidate artifact.
- Fail-closed promotion gates and verified local inference with strict feature-schema and
  critical-quality validation.
- Versioned official-priority overrides and privacy-safe drift aggregates without automatic
  retraining.
- Approved HTTPS/PDF/checksum ingestion, procedure-preserving chunks, effective/expiry filters,
  hybrid BM25 plus multilingual character-vector retrieval, and resolvable citations.
- Full-corridor geometry intersection, official hard constraints and deterministic ranking when
  approved numeric coefficients exist.
- Existing risk endpoint uses a verified active predictor when available and preserves the
  conservative fallback otherwise.
- Release gate validates active stage, model-card safety language, golden cases and checksums.

## Verification

```text
docker compose run --rm risk-knowledge uv run ruff check .
All checks passed!

ruff format --check: 65 files already formatted
mypy: Success: no issues found in 48 source files
pytest: 80 passed; coverage 85.83% (gate 80%)
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
- The combined evidence endpoint still fails closed until immutable snapshot retrieval and active
  model/knowledge/route dependencies are all available.
- A real-provider/full-system Phase 8 acceptance run was not fabricated. It must run with approved
  artifacts, provider credentials and recorded cross-module decisions.

## Rollback

Revert this commit. Runtime continues using the existing deterministic fallback whenever no
verified ACTIVE model or knowledge collection is available.
