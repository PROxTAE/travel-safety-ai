# M05 Phase 2: validation and normalization handoff

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 05 Data Integration |
| Issue/PR | Pending review PRs |
| Branch | `docs/05-phase2-handoff` (stacked on `feat/05-normalization-geometry`) |
| Base/final commit | `origin/main` `3353f15`; implementation through `6b0f7cf` |
| Date/time | 2026-09-21 08:35 Asia/Bangkok |
| Reviewers | Contract owner, module 04 producer, module 06 consumer |
| Contract version | Canonical JSON Schemas v1; transform `1.0.0` plus checksum |
| Docker image | `smart-travel-data-integration:runtime` `sha256:14c6c730792caf825db05fce9936d292ddbc16180efb0c90f1c8eac53c9e8d75` |

## 2. Executive summary

Module 05 accepts current module 04 weather, disaster, route, transport, and place records. Generated Pydantic models come from the shared canonical JSON Schemas; local strict models add semantic checks that the generator cannot express. Invalid records are quarantined with a content hash and field path. Valid records are normalized to UTC, retain nullable measurements, provenance, geometry, transform version, checksum, and field lineage, then use idempotent PostgreSQL upsert. Route provenance uses `sources[]` end to end. This report covers Phase 2; later dedup, corridor, features, snapshots, and operations are separate review slices.

## 3. Responsibility and acceptance

- [x] Generated input models and strict validation: `packages/contracts/scripts/generate-integration-inputs.sh`, `app/domain/canonical.py`, Docker consumer tests.
- [x] Pure unit, time, severity, place, geometry transforms: `app/pipeline/normalize.py`.
- [x] Transform version/checksum and field lineage: stored with each canonical record.
- [x] Invalid, outlier, non-finite, null versus zero tests: `tests/test_phase2.py`; geometry topology checked by PostGIS.
- [x] Idempotent upsert: `integration.canonical_records` unique record/source/hash key.

## 4. Implementation and flows

`CanonicalRepository.ingest(kind, payload)` hashes the input, validates generated schema fields, applies strict semantic validation, normalizes, checks geometry topology with PostGIS, then stores the canonical record or a quarantine entry. No invalid payload body is retained in quarantine. Repeated identical records resolve to the same row. Missing provider measurements remain `null` and route exposure remains `null` with `risk_level=UNKNOWN` until evaluated downstream.

## 5. Architecture and decisions

| Path | Role |
| --- | --- |
| `packages/contracts/generated/python/smart_travel_contracts/integration_inputs/` | Reproducible generated input models |
| `services/data-integration/app/domain/canonical.py` | Strict producer shapes and semantic checks |
| `services/data-integration/app/pipeline/normalize.py` | Pure normalization, checksum, field lineage |
| `services/data-integration/app/repositories/canonical_repo.py` | Quarantine and idempotent persistence |
| `services/data-integration/tests/fixtures/m04-*.json` | Sanitized current producer samples with capture metadata |

Generated models alone do not enforce every JSON Schema conditional or topology rule. Local models enforce the raw route unknown-risk invariant and PostGIS rejects self-intersecting geometry. Schema and semantic checks run together at the storage boundary.

## 6. API and contract changes

No external endpoint is added in Phase 2. Shared schemas remain unchanged. The shared generator now emits input models for weather, disaster, route, transport, and emergency POI from the existing v1 schemas. Module 04 produces route `sources[]`; module 05 consumes and retains all source IDs. Shared contract tests validate current module 04 samples with the generated models. Any future schema change requires both producer and consumer tests.

## 7. Database and storage

Migration `0003_canonical_records` creates `integration.canonical_records` with a unique `(record_type, source_id, content_hash)` key, geometry index, and validity-time index. Invalid inputs enter `integration.quarantine` with `raw_content=NULL`. The Phase 2 Docker suite creates a fresh PostgreSQL database, upgrades migrations twice, and tests duplicate ingestion. Existing retention policy and least-privilege login provisioning require infrastructure review; Compose currently uses its configured PostgreSQL user.

## 8. Real data and provenance

The test fixtures copy module 04 handoff records derived from sanitized USGS, Open-Meteo, openrouteservice, OpenStreetMap POI, and MTA captures. Each test fixture records the source URL, capture time, actual HTTP 200, license, and redaction note from `services/external-data/tests/fixtures/real-sanitized/MANIFEST.json`. The samples are test-only. No runtime weather, alert, transport, or route value is mocked or hard-coded.

## 9. Configuration and Docker

No new secret or environment variable. Compose passes the shared generated Python package as a named build context; both dev and runtime images include it. The runtime runs as UID 10001. Readiness and liveness are the Phase 1 endpoints.

```bash
docker compose -f compose.yaml -f compose.dev.yaml config --quiet
docker compose -f compose.yaml -f compose.dev.yaml build data-integration
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run pytest -q
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff format --check app tests
docker compose -f compose.yaml build data-integration
uv run --project tests/contract pytest tests/contract -q
```

## 10. Verification evidence

| Check | Actual result |
| --- | --- |
| Compose config | exit 0 |
| Dev image build | exit 0 |
| Module Docker pytest | `22 passed in 3.09s` |
| Module Docker Ruff lint | `All checks passed!` |
| Module Docker Ruff format | `33 files already formatted` |
| Runtime image build | exit 0, digest above |
| Shared contract pytest | `92 passed in 0.88s` |
| Generated clean check | `Generated contract output matches the source.` |

Success cases include all five current producer shapes, duplicate ingestion, and valid Polygon/MultiPolygon. Invalid numeric, timestamp, coordinate, required field, and self-intersecting polygon cases quarantine. No live provider call is made by deterministic tests.

## 11. UI evidence

Not applicable: this phase changes an internal service only.

## 12. Safety and privacy

Input validation, nullable measurements, source timestamps, quality flags, and field lineage are retained. Quarantine stores no raw body. Fixture metadata documents public capture provenance; no credentials or personal data are included. Generated schema and local semantic checks prevent an unevaluated route from claiming a safe risk level.

## 13. Problems and resolutions

| Problem | Evidence | Resolution |
| --- | --- | --- |
| Producer route changed from `source` to `sources[]` | Module 04 merge `3353f15` and route sample | Consumer updated; all source IDs retained |
| Shared generator emitted only public API models | `generate-python.sh` used `public-api.bundled.yaml` | Added pinned JSON Schema generator and reproducibility check |
| Simplified old USGS test failed generated validation | Initial Docker test returned `None` on ingest | Replaced with current sanitized module 04 record |
| Docker default build context could not see shared package | Service context was `services/data-integration` | Added named contract context and copied models into both image stages |

## 14. Performance and operations

No Phase 2 latency target or load measurement is claimed. Record geometry uses a GiST index. Query-plan and load evidence belong to Phase 4/6. Quarantine and schema drift metrics remain Phase 6 work.

## 15. Known limitations

This phase is not a complete `IntegratedTravelContext` pipeline. Provider coverage and credentials are reported by module 04; module 05 must propagate unavailable/degraded states during later snapshot assembly. Dedicated least-privilege DB credentials require shared infrastructure work. Generated Pydantic models do not replace local semantic checks or a full JSON Schema conditional validator.

## 16. Handoff

| Recipient | Ready now | Next action |
| --- | --- | --- |
| Module 04 | Current canonical sample records accepted | Review field parity when producer shape changes |
| Module 06 | Versioned canonical evidence and lineage in PostgreSQL | Review Phase 5 feature schema separately |
| Module 03/07 | No snapshot endpoint in this phase | Integrate after Phase 5 snapshot API |

## 17. Commit and PR inventory

Contract stack: `5bf986b`, `da2f914`, `215c28e`. Consumer integration: `7fc3d6f`, `493fd8a`, `6b0f7cf`. Earlier Phase 1/2 commits remain in the stacked branch history. PRs are pending GitHub authentication and review. Current base is `origin/main` `3353f15`; no merge or release is claimed.

## 18. Rollback and recovery

Revert the Phase 2 application slices and generated contract slices in reverse dependency order. Migration `0003` has a downgrade, but run it only after preserving affected canonical records. Rebuild the service image and rerun health, migration, and consumer tests. No database volume deletion is part of rollback.

## 19. Declaration

Phase 2 behavior and required tests are complete locally. Contract owner, module 04 owner, and team review remain required before merge. Later phases and production release are not covered by this report.
