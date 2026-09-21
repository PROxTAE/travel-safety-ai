# [M05] Phase 6 completion report: parity, operations, metrics and load

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 05 Data Integration |
| Issue/PR | #68 (6a parity), #71 (6b operations), #72 (6c metrics), 6d load PR |
| Branch | `test/05-parity-spatial-resilience` stacked on `feat/05-pipeline-metrics` |
| Base/final commit | Phase 5 tip `8ad0167`; Phase 6 tip `8bfb9cb` plus this report |
| Date/time | 2026-09-21 Asia/Bangkok |
| Reviewers | Module 06 (batch features), operations/observability owner, database owner |
| Contract version | unchanged: `IntegratedTravelContext` 1.0.0, feature schema 1.0.0 |
| Docker image | `smart-travel-data-integration:runtime` `sha256:ada3c36dced4bfd0acb8d86b2912c714302c4c716421469bd2fefaf5eac8fb7d` |

## 2. Executive summary

Phase 6 is complete.
- **Parity:** the training pipeline gets the same feature code the API uses (`python -m app.cli.features`), and a test proves online and batch features are byte-identical.
- **Maintenance commands:** backfill, purge and rebuild are all idempotent. `rebuild` re-runs a stored request and reports whether the snapshot is reproducible, which is why migration `0006` now keeps the request with each snapshot.
- **Metrics:** the pipeline exports bounded metrics for gate, flags, conflicts, coverage, freshness, rejections and latency.
- **Load test:** it found and fixed a real defect. Under a generic prepared plan, the corridor query re-parsed the route GeoJSON for every row and took 1.5 s at 50,000 events; it now takes about 50 ms in every plan mode.

## 3. Original responsibility and acceptance (plan §Phase 6)

- [x] 1. Expose the same feature package/CLI to module 06 training: `app/cli/features.py` over `compute_route_features` (#68).
- [x] 2. Parity test batch vs online: byte-identical on four real-capture cases (#68).
- [x] 3. Idempotent cleanup/backfill/rebuild commands: `app/cli/operations.py` (#71).
- [x] 4. Metrics for invalid, quarantine, dedup conflict, coverage, freshness, schema drift and latency (#72; quarantine counting fixed in #71).
- [x] 5. Load test route/event volume and optimize the query with EXPLAIN evidence (this PR).

## 4. Behavior and flows

- **Batch:** reads one JSON line per request and writes one feature row per request, using the same `compute_route_features` as the API. An invalid line stops the batch with its line number. The rejected value is never echoed and no output file is written.
- **Backfill:** `backfill --kind <kind> --input <file>` ingests through `CanonicalRepository.ingest`. Stored rows are unique on `(record_type, source_id, content_hash)`, and an invalid record is quarantined once per source hash.
- **Purge:** `purge-quarantine [--days N]` deletes only rows older than the retention.
- **Rebuild:** `rebuild --snapshot-id <uuid>` re-runs the stored request inside a transaction that is rolled back, then compares content hashes. Exit codes: 0 reproducible, 3 drift, 4 stored before `0006`, 1 unknown id.

## 5. Architecture and design

| Path | Role |
| --- | --- |
| `app/pipeline/build.py` | `compute_route_features` (the single feature path), `evidence_from_request` |
| `app/cli/features.py`, `app/cli/operations.py` | Command-line entry points |
| `app/migrations/versions/0006_snapshot_request.py` | Nullable `snapshots.request_json` |
| `app/observability/metrics.py` | Pipeline metrics (closed-enum labels) |
| `app/pipeline/spatial.py` | `HAZARD_QUERY` with the corridor in a materialized CTE |
| `tests/load_seed.py`, `tests/perf_corridor.py`, `tests/test_spatial_index.py` | Volume data, measurement script, index plan assertion |

## 6. API and contract

No contract change. `/metrics` gains new series. Found while testing: PostgreSQL JSONB reorders object keys, so a stored snapshot returns `features` in a different key order than the schema. The values are identical, JSON object order has no meaning, and the content hash uses sorted keys.

## 7. Database and storage

`0006_snapshot_request` adds a nullable JSONB column; the downgrade drops it. The immutability trigger is untouched because the column is only written on insert. No new index: the existing `ix_canonical_geography` from `0005` is the right index; the query was the problem.

## 8. Real data and provenance

The feature, parity, operations and metrics tests use the module 04 captures in `tests/fixtures/m04-*.json`. The load volume is synthetic by design: `load_seed.py` copies the captured USGS payload onto a deterministic grid over Thailand (97–104°E, 5.5–21.5°N) with `load:` source ids. It lives in a throwaway database and is never read at runtime.

## 9. Configuration and Docker

No new variables.

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run pytest -q
docker compose -f compose.yaml -f compose.dev.yaml run --rm -T data-integration \
  uv run python -m app.cli.features --input - --output - < requests.jsonl
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration \
  uv run python -m app.cli.operations backfill --kind weather --input records.jsonl
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration \
  uv run python tests/perf_corridor.py --events 50000 --runs 30 --corridor-events 200
```

## 10. Verification evidence

| Check | Result |
| --- | --- |
| Docker pytest | `84 passed in 5.83s` (0 failed, 0 skipped) |
| Ruff lint / format | `All checks passed!` / `65 files already formatted` |
| mypy | `Found 23 errors in 4 files`, all from phases 2–4 (#48); none in Phase 6 files |
| Runtime image | exit 0, digest in §1 |
| Batch CLI in Docker | `2 feature rows written` (weather present: gust 19.8, 4 nulls; weather unavailable: 7 nulls) |
| Operations CLI in Docker, fresh DB | `0006` applied; run 1 `stored=1 quarantined=1`, run 2 `stored=1 quarantined=1`; tables after both runs: 1 canonical, 1 quarantine |

### Load and EXPLAIN (50,000 disaster rows, Bangkok–Chiang Mai test route, 596 samples, 5 km corridor)

Before the fix (inline `ST_GeomFromGeoJSON(:route)`):

```text
EXPLAIN ANALYZE, index: Index Scan using ix_canonical_geography ... rows=228   Execution Time: 52.988 ms
EXPLAIN ANALYZE, no index: Parallel Seq Scan on canonical_records ...           Execution Time: 309.531 ms
served query (asyncpg prepared), 10 runs: p50 758.4 ms, p95 1475.1 ms
same query, plan_cache_mode = force_custom_plan: p50 50.2 ms, p95 51.9 ms
```

Diagnosis: after five executions PostgreSQL switched to a generic plan, in which the route literal is not folded, so the 596-point GeoJSON was parsed and cast for every candidate row.

After the fix (corridor in `WITH corridor AS MATERIALIZED`):

```text
EXPLAIN ANALYZE, index:
  Nested Loop (actual time=4.597..51.713 rows=228)
    -> CTE Scan on corridor (rows=1)
    -> Index Scan using ix_canonical_geography on canonical_records record (rows=228)
  Execution Time: 51.800 ms
EXPLAIN ANALYZE, index disabled: Seq Scan on canonical_records ... Execution Time: 570.272 ms
served query, 30 runs: p50 49.9 ms, p95 51.9 ms
forced custom plan, 30 runs: p50 49.8 ms, p95 52.2 ms
snapshot pipeline (596 samples, 200 corridor events), 30 runs: p50 101.4 ms, p95 133.3 ms
```

Note: the timing loop of the "index disabled" variant reuses asyncpg's cached plan, so only its EXPLAIN ANALYZE line (570 ms) is a fair no-index comparison.

## 11. UI evidence

Not applicable: internal service.

## 12. Safety, security and privacy review

- [x] The batch fails closed: no partial training file, and no rejected value is echoed.
- [x] `rebuild` never writes; immutable snapshots stay immutable.
- [x] Backfill stores no raw body for invalid records.
- [x] Metric labels are closed enums; no ids or values appear as labels.
- [x] Load data is test-only and never served.

## 13. Problems encountered and resolutions

| Problem | Root cause | Evidence | Resolution | Remaining risk |
| --- | --- | --- | --- | --- |
| Corridor query 30× slower when served | Generic prepared plan re-parsed the GeoJSON per row | Timings in §10 | Materialized CTE | none measured |
| `integration_quarantined_total` never counted | Ingest bypassed `QuarantineRepository` | Code read, then a test | Ingest now goes through the repository | none |
| Rerunning a backfill duplicated quarantine rows | No check for an existing row | Test | Quarantine once per source hash | none |
| Snapshot rebuild impossible | Request not stored | Design review | Migration `0006` | snapshots stored before `0006` cannot be rebuilt |
| `test_health` assumed an empty database | Shared session database | Failed when a new test file sorted first | Compare with the table count | none |
| JSONB reorders feature keys | PostgreSQL JSONB storage | Parity test | Compare sorted serializations | consumers must not rely on key order |
| Seed grid collapsed to one point | asyncpg inferred int for float steps | Probe query | Explicit `double precision` casts | none |

## 14. Performance and operational behavior

| Metric | Target | Actual | Condition | Pass |
| --- | --- | --- | --- | --- |
| Corridor query | uses geography index | Index Scan `ix_canonical_geography` | 50k rows | yes |
| Corridor query latency | not specified | p50 49.9 ms / p95 51.9 ms | 50k rows, 596 samples | recorded |
| Snapshot pipeline latency | not specified | p50 101.4 ms / p95 133.3 ms | 200 corridor events | recorded |

The plan sets no latency target; these are baselines for Phase 7 and the team runbook.

## 15. Known limitations and technical debt

| Limitation | Impact | Owner | Follow-up |
| --- | --- | --- | --- |
| `request_json` roughly doubles each snapshot row | Storage growth | M05 / operations | retention or archive policy in Phase 7 |
| No dashboard or alert rules | Metrics exist but nobody is alerted | observability owner (`infra/`) | request after merge |
| Load measured in one local container | Not production hardware | M05 | rerun in Phase 7 integration |
| 23 pre-existing mypy errors | Type bugs can slip | M05 | #48 |

## 16. Handoff to other members

| Recipient | What is ready | What they must do | Blocking? |
| --- | --- | --- | --- |
| M06 | `python -m app.cli.features`, byte-identical to online | Run it on training requests | No |
| Operations | `backfill`, `purge-quarantine`, `rebuild`; new metrics | Schedule the purge; build dashboards | No |

## 17. Commit and PR inventory

- #68: `68c5e4c`, `e8e3f70`, `6b4aa41`, `5be6f53`
- #71: `85546f9`, `64140d1`, `1ae5001`, `fe90f5b`
- #72: two commits (metrics and tests)
- This PR: `c32369a`, `c0c91ef`, `8bfb9cb`, plus this report

## 18. Rollback and recovery

Revert from the top down. `alembic downgrade 0005_canonical_geography_index` removes `request_json`. The query change is behavior-preserving, and the existing corridor tests pass unchanged.

## 19. Final declaration

- [x] Phase 6 scope is complete, with evidence.
- [x] Gaps are listed in §15.
- [ ] Merged.
