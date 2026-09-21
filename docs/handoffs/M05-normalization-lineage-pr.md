# [M05] Validate and normalize canonical provider records

## Summary

Add generated v1 input models from the shared JSON Schemas and use them at the module 05 storage boundary. Normalize provider records deterministically, retain source lineage, quarantine invalid input, and persist valid records idempotently in PostgreSQL/PostGIS.

## Scope

In scope: weather, disaster, route, transport, and emergency POI input validation; route `sources[]`; UTC/unit/place/severity/geometry transforms; polygon topology checks; field lineage; Docker packaging; sanitized producer/consumer fixtures.

Out of scope: dedup/conflict, corridor exposure, feature schema, immutable snapshots, online/offline parity, and final service integration. Those have separate review slices.

## Ownership and dependencies

- Owner: M05 Data Integration.
- Depends on the three generated contract branches `contract/05-integrated-context-schema`, `contract/05-integration-input-dependencies`, and `contract/05-integration-input-records`; module 04's route `sources[]` contract is already on `main`.
- Review requested from the contract owner, module 04 producer, and module 06 consumer.
- Completion report: `docs/handoffs/M05-normalization-lineage.md`.

## Contract, database, and configuration changes

- Existing v1 JSON Schemas remain unchanged; the pinned generator now emits Python input models for the five canonical record types.
- `integration.canonical_records` migration `0003` stores versioned payload, geometry, and lineage with a unique source/hash key. Invalid records go to `integration.quarantine` without raw content.
- Compose uses a named build context to copy generated models into dev and runtime images. No new secret or environment variable.
- A producer shape change requires matching shared contract and module 05 consumer tests before rollout.

## Real data and provenance

- Tests use sanitized module 04 records derived from USGS, Open-Meteo, openrouteservice, OpenStreetMap POI, and MTA captures.
- Each test fixture records source URL, capture time, actual HTTP status, license, and redaction note from module 04's fixture manifest.
- Runtime/demo contains no mock or hard-coded current weather, alert, transport, or route data.
- Missing or invalid input is quarantined; this phase does not turn unavailable coverage into empty success.

## How to run

```bash
docker compose -f compose.yaml -f compose.dev.yaml config --quiet
docker compose -f compose.yaml -f compose.dev.yaml build data-integration
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run pytest -q
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff format --check app tests
docker compose -f compose.yaml build data-integration
uv run --project tests/contract pytest tests/contract -ra
bash packages/contracts/scripts/check-generated-clean.sh
```

## Verification evidence

```text
Compose config: exit 0
Dev image build: exit 0
Module Docker pytest: 22 passed in 3.09s
Module Docker Ruff lint: All checks passed!
Module Docker Ruff format: 33 files already formatted
Runtime image build: exit 0, sha256:14c6c730792caf825db05fce9936d292ddbc16180efb0c90f1c8eac53c9e8d75
Shared contract pytest: 92 passed in 0.88s
Generated clean check: Generated contract output matches the source.
```

No UI screenshot applies. Migration tests run against fresh PostgreSQL in Docker. No live provider call is needed for deterministic fixtures.

## Safety, security, and privacy

- [x] Generated schema and strict semantic checks run before persistence.
- [x] Invalid records are quarantined without raw provider bodies.
- [x] Source timestamps, nullable measurements, quality flags, versions, and field lineage survive normalization.
- [x] Unevaluated routes retain `exposure=null` and `risk_level=UNKNOWN`.
- [x] No credential or personal data appears in code, fixtures, commits, or this PR body.

## Test coverage

- [x] Current producer samples for all five record types.
- [x] Duplicate input idempotency and invalid input quarantine.
- [x] Null versus zero, non-finite numbers, timezone, coordinate order, and copied observation time.
- [x] Polygon/MultiPolygon acceptance and self-intersection rejection through PostGIS.
- [x] Shared producer/contract and Docker consumer checks.

## Risks and limitations

Generated Pydantic models do not implement every JSON Schema conditional; local semantic models and PostGIS topology checks remain required. This PR does not create `IntegratedTravelContext` or expose snapshot endpoints. Dedicated least-privilege PostgreSQL credentials await infrastructure review.

## Rollback

Revert application and generated contract slices in reverse dependency order, rebuild the image, and rerun health/migration/consumer checks. Preserve canonical data before any migration downgrade; do not remove database volumes.

## Handoff

- Report: `docs/handoffs/M05-normalization-lineage.md`.
- Module 04 owner: review input parity and fixture provenance.
- Contract owner: review generator reproducibility and shared package exports.
- Module 06 owner: use later Phase 5 feature schema for inference; no feature meaning is finalized here.
