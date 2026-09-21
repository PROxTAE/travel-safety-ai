# [M05] Build the module 06 feature vector and the evidence quality gate

## Summary

Add a deterministic builder that turns aligned route evidence into the 13 features proposed by module 06 (`feature_schema.v1.yaml`, v1.0.0). Add a versioned PASS/DEGRADED/BLOCK quality gate alongside it. An unavailable source stays null and is never read as `0` or `False`. Evidence learned after the recommendation time is excluded.

## Scope

In scope:

- `app/pipeline/features.py` and a verbatim copy of the module 06 schema (`e85d589`).
- `app/pipeline/quality.py` gate and flags.
- `pyyaml` declared as a direct dependency (2-line lock change).

Out of scope:

- Weighted quality score (next PR), snapshot persistence, content hash, and endpoints (PR 7). H3 region features, which v1.0.0 does not include.

## Ownership and dependencies

- Module/owner: M05 Data Integration.
- Depends on PR/contract: the M05 stack through `feat/05-route-corridor-geometry`. The feature names come from M06 `contract/06-risk-evidence-route-schema`.
- Downstream consumers: M06 (features), M03/M07 (gate).
- Issue/ADR: follow-up issues listed below.

## Contract, database and configuration changes

- API/OpenAPI/JSON Schema: no change. `features` in `IntegratedTravelContext` is already a `number/string/boolean/null` map.
- **Lead decision on #43/#44 applied:** the three `corridor_official_*` booleans are `nullable: true` and return null when the alert source is unavailable (an absent source cannot prove "no closure"); `corridor_official_evacuation_active` is `critical: false` until a provider exists. Module 06 applies the same change in PR #12.
- Migration/table/index: none.
- Environment variables: none.
- Backward compatibility/rollout: nothing calls the builder at runtime until PR 7.

## Real data and provenance

- Provider/source: module 04 captures in `tests/fixtures/m04-*.json`, namely Open-Meteo Bangkok (HTTP 200, CC-BY-4.0), USGS (HTTP 200, public domain), and MTA GTFS-RT (producer status STALE).
- Endpoint/coverage: test fixtures only. Route lines and hazard squares are test-only geometries placed on the captured coordinates.
- Freshness/TTL: the producer's `DataQuality.status` is used as-is.
- Failure/degraded behavior: an unavailable source gives null features plus `null_features`, and coverage 0.
- ยืนยันว่า runtime/demo ไม่มี mock หรือ hard-coded current data: [x]

## How to run

```bash
docker compose -f compose.yaml -f compose.dev.yaml build data-integration
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run pytest -q
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff format --check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run --with mypy==1.13.0 --with types-PyYAML mypy app
docker compose -f compose.yaml build data-integration
```

## Verification evidence

```text
command: uv run pytest -q
result: 53 passed in 3.87s (0 failed, 0 skipped)

command: uv run ruff check app tests
result: All checks passed!

command: uv run ruff format --check app tests
result: 49 files already formatted

command: uv run --with mypy==1.13.0 --with types-PyYAML mypy app
result: Found 23 errors in 4 files (checked 37 source files)
        all in normalize.py, dedup.py, canonical_repo.py, alignment.py from earlier phases;
        features.py and quality.py report none

command: docker compose -f compose.yaml build data-integration
result: exit 0, sha256:67942c6dfa7eb644b8287866845d5e50f11572243643c3e1d48eee9ecc5da840
```

- UI screenshots/video: n/a (internal service)
- Migration up/down result: n/a (no migration)

## Safety, security and privacy

- [x] Input validated at boundary (canonical pydantic models)
- [ ] Timeout/cancellation/retry/idempotency handled: n/a, pure functions
- [x] No secret, token, PII or exact location leaked to logs/fixtures
- [x] Provenance, timestamps, quality and version retained
- [x] Official warning cannot be weakened: UNKNOWN severity leaves the EXTREME flag null, never `False`
- [x] Provider text treated as untrusted
- [ ] Consent/retention: n/a
- [x] Error messages expose no internal stack/secret

## Test coverage

- [x] success path
- [x] invalid path: a non-nullable null or a feature not in the schema raises
- [ ] dependency timeout/429/5xx: n/a, no I/O
- [x] stale/conflicting/partial data
- [x] boundary values and regression case (hazard fraction, dateline, leakage cutoff)
- [ ] contract test with producer/consumer: pending the M06 schema approval
- [ ] E2E: n/a until PR 7

## Risks and limitations

- `corridor_official_evacuation_active` is always null because no producer publishes evacuation orders; it is non-critical per the Lead decision (#44), so it no longer forces UNKNOWN.
- `align_disaster` crashes on Polygon events. The builder does not use it for areas, but the corridor pipeline does.
- About 780 changed lines in total (quality 175, features 604 including the 133-line verbatim schema), over the 400-line guideline. The work can be split: quality gate (`2b97108`..`ceab738`) as one PR and the feature vector (`f925c43`..`550e39b`) stacked on it.

## Rollback

- Code rollback: revert the five commits. Nothing calls the builder at runtime yet.
- Database/schema rollback or forward-fix: none.
- Feature flag/provider disable path: n/a.

## Handoff

- Completion report: `docs/handoffs/M05-feature-quality.md`
- What the next owner must do: M06 approves the schema and decides whether the official booleans can be null. M04 says whether evacuation orders can be sourced.
- Reviewer focus areas: the null and `False` semantics in `_disasters`, the leakage cutoff in `_before_cutoff`, and the schema copy matching the Lead decision on #43/#44.

## Follow-up issues

1. M06 feature schema: allow null for the `corridor_official_*` booleans.
2. No source for official evacuation or no-go orders.
3. `align_disaster` crashes on Polygon and MultiPolygon events (`alignment.py:127`).
4. `quality.py` compares every source with one freshness threshold, so car routes are always DEGRADED.
5. `critical_evidence_freshness_seconds` uses the reported age, not the age at snapshot time.
6. Add mypy to the data-integration dev deps and the Makefile `typecheck` target, and fix the 23 existing errors.
