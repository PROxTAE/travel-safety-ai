# M05 Phase 3: deduplication and conflict handoff

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 05 Data Integration |
| Issue/PR | Pending review PRs |
| Branch | `docs/05-phase3-handoff` stacked on `feat/05-dedup-conflict-storage` |
| Base/final commit | Phase 2 report `94c5c47`; Phase 3 through `ab8cb00` |
| Date/time | 2026-09-21 Asia/Bangkok |
| Reviewers | Module 04 producer, contract owner, module 06 consumer |
| Contract/version | Canonical v1, `MATCH_VERSION=1.0.0` |
| Docker image | `smart-travel-data-integration:runtime` `sha256:5cc097a01f9e1237967f96efb7a1cfa95883b25c3e72b5df982f0fc21c05ef1a` |

## 2. Executive summary

Phase 3 groups exact duplicate records, marks spatial/time-similar events for review, and resolves disputed fields with retained source evidence. Matching is deterministic and versioned. Safety-critical disagreements remain visible as `CONFLICTING`; severity and closure are never averaged. Cluster members, matching reasons, confidence, selected values, and losing values persist in PostgreSQL with idempotent writes. No current conditions are fabricated.

## 3. Original responsibility and acceptance

- [x] Provider/version, cross-reference, exact-content, and spatial/time candidate rules: `app/pipeline/dedup.py`.
- [x] Candidate clustering retains members and confidence; candidate similarity does not silently merge records.
- [x] Authority, freshness, completeness, provider health, and agreement participate in field ranking.
- [x] Selected and losing source evidence persists with unresolved safety conflicts.
- [x] Concurrent repeated cluster input uses a unique key and idempotent upsert.

## 4. Behavior and flows

Canonical records enter `candidate_links`, then `exact_clusters` and `candidate_groups`. `resolve_field` ranks source evidence and returns the selected value, alternatives, and conflict status. `DedupRepository` stores immutable cluster evidence keyed by record type, cluster key, and match version. A repeated or concurrent identical write resolves to the same cluster row. Spatial/time candidates remain separate until a later rule or review establishes identity.

## 5. Architecture and design

| Path | Role |
| --- | --- |
| `app/pipeline/dedup.py` | Pure deterministic matching, candidate grouping, field resolution |
| `app/repositories/dedup_repo.py` | Idempotent persistence of cluster and conflict evidence |
| `app/migrations/versions/0004_dedup_clusters.py` | Unique cluster key and indexes |
| `tests/test_dedup.py`, `tests/test_dedup_repository.py` | Source ranking, candidate grouping, concurrency |

Source IDs and losing values remain queryable in cluster JSON. Official records from different authorities are retained as separate evidence. Field ranking is versioned; a future rule change must use a new match version.

## 6. API and contract

No external endpoint or shared schema changed in Phase 3. `MATCH_VERSION=1.0.0` is stored with clusters. The Phase 2 generated input and consumer checks remain prerequisites. No downstream risk decision is made by this phase.

## 7. Database and storage

Migration `0004_dedup_clusters` adds `integration.dedup_clusters` with unique `(record_type, cluster_key, match_version)`, member/match/conflict JSON, content hash, and creation time. The migration has a downgrade. Tests create a fresh PostgreSQL database and cover concurrent repeated writes. Retention and archive policy are later operations work; do not delete source evidence during dedup.

## 8. Real data and provenance

Tests derive event identity, times, coordinates, and source records from module 04 sanitized USGS captures with public-domain provenance. Test-only variants change source authority or nearby position to exercise matching; no runtime fixture or hard-coded live event is used. Missing provider evidence remains missing and is never converted into a successful empty match.

## 9. Configuration and Docker

No new environment variable or secret. The runtime image runs as UID 10001 and contains the generated canonical input package. Compose and readiness behavior are unchanged from Phase 2.

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run pytest -q
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff format --check app tests
docker compose -f compose.yaml build data-integration
```

## 10. Verification evidence

| Check | Actual result |
| --- | --- |
| Docker pytest | `29 passed in 3.43s` |
| Docker Ruff lint | `All checks passed!` |
| Docker Ruff format | `38 files already formatted` |
| Runtime image build | exit 0, digest above |

Success, exact duplicate, near candidate, conflicting severity, losing evidence, and concurrent persistence cases are covered. No live provider call is made by deterministic tests.

## 11. UI evidence

Not applicable: this phase changes an internal service only.

## 12. Safety, security, and privacy

No raw provider body is introduced. Source authority, timestamps, quality, provider health, and all alternative field evidence are preserved. Unresolved safety conflicts stay explicit and cannot be silently averaged or promoted to a confident value. No credentials or personal data are in test fixtures.

## 13. Problems and resolutions

| Problem | Evidence | Resolution |
| --- | --- | --- |
| Old Phase 3 branch preceded the latest generated input checks | Rebase conflict in `test_phase2.py` | Kept the current USGS source ID and content-hash count filter; Docker suite passed |
| Similar events may be separate incidents | Spatial/time candidate test | Candidate grouping does not auto-merge |

## 14. Performance and operations

No load or p95 latency claim is made here. Migration adds a unique key and created-time index. Query-plan/load evidence and dedup metrics remain Phase 6 work.

## 15. Known limitations

The cluster repository is ready but full snapshot assembly and API exposure are later phases. Spatial/time similarity requires review or stronger identity evidence. Provider health must be supplied to field ranking; an absent health signal does not become a healthy signal.

## 16. Handoff

| Recipient | Ready now | Next action |
| --- | --- | --- |
| Module 04 | Producer IDs/cross-references consumed without deletion | Review any new provider ID mapping |
| Module 06 | Cluster conflicts and field alternatives retained | Define feature and confidence treatment in Phase 5 |
| Module 07 | Explicit unresolved safety conflicts available | Consume conflict summary after snapshot API exists |

## 17. Commit and PR inventory

Phase 3 commits: `9e543dc`, `fd8d175`, `dcbae14`, `ab8cb00`. The first two are on `feat/05-dedup-conflict`; the next two are on `feat/05-dedup-conflict-storage`. PRs are pending GitHub authentication and review. Main was not changed.

## 18. Rollback and recovery

Revert Phase 3 service commits in reverse dependency order. Preserve cluster evidence before migration downgrade. Rebuild the image, then rerun migration, dedup, and consumer tests. No database volume deletion is part of rollback.

## 19. Declaration

Phase 3 behavior and tests are complete locally. Contract, producer, and downstream review remain required before merge. Later phases and production release are not covered by this report.
