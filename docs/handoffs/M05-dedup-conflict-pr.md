# [M05] Group duplicate records and retain conflict evidence

## Summary

Add deterministic, versioned duplicate matching and field-level conflict resolution. Persist exact clusters and review candidates with source evidence so downstream consumers can trace both selected and disputed values.

## Scope

In scope: exact identity rules, spatial/time candidate grouping, authority/freshness ranking, safety conflict status, idempotent PostgreSQL storage, and migration `0004`.

Out of scope: automatic merging of spatial/time candidates, corridor alignment, feature decisions, snapshot endpoints, and production load targets.

## Ownership and dependencies

- Owner: M05 Data Integration.
- Depends on Phase 2 generated input models and canonical storage branches.
- Review: module 04 producer, contract owner, and module 06 consumer.
- Completion report: `docs/handoffs/M05-dedup-conflict.md`.

## Contract, database, and configuration changes

- No shared API or JSON Schema change. Matching rules use `MATCH_VERSION=1.0.0`.
- Migration `0004_dedup_clusters` adds `integration.dedup_clusters` with a unique record type/cluster key/version constraint and indexes.
- No new secret or environment variable. Existing canonical v1 records remain valid.

## Real data and provenance

- Tests derive records from sanitized module 04 USGS captures with source URL, HTTP status, capture time, license, and redaction metadata.
- Runtime has no mock or hard-coded current provider data.
- Missing evidence stays missing; an unresolved safety disagreement is `CONFLICTING`.

## How to run

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run pytest -q
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff format --check app tests
docker compose -f compose.yaml build data-integration
```

## Verification evidence

```text
Docker pytest: 29 passed in 3.43s
Docker Ruff lint: All checks passed!
Docker Ruff format: 38 files already formatted
Runtime image build: exit 0, sha256:5cc097a01f9e1237967f96efb7a1cfa95883b25c3e72b5df982f0fc21c05ef1a
```

No UI evidence applies. Migration and concurrent idempotency tests run against PostgreSQL in Docker.

## Safety, security, and privacy

- [x] Canonical inputs are validated before matching.
- [x] Concurrent repeated cluster writes are idempotent.
- [x] Source IDs, timestamps, alternatives, confidence, and rule version are retained.
- [x] Conflicting severity and closure are not averaged or silently weakened.
- [x] No secret, personal data, or raw provider body is introduced.

## Test coverage

- [x] Exact duplicate and distinct-record paths.
- [x] Spatial/time review candidate remains unmerged.
- [x] Conflicting and partial evidence.
- [x] Concurrent repeated persistence and migration.
- [x] Producer fixture compatibility and Phase 2 regression suite.

## Risks and limitations

Similarity candidates require a stronger identity rule or review before merging. Snapshot assembly and query-plan/load evidence belong to later phases.

## Rollback

Revert application commits in reverse dependency order. Preserve cluster evidence before migration downgrade, rebuild the image, and rerun Docker checks.

## Handoff

- Report: `docs/handoffs/M05-dedup-conflict.md`.
- Module 04: review source identity and cross-reference mapping.
- Module 06: decide how unresolved conflicts affect feature confidence.
- Reviewer focus: candidate non-merge rule, safety conflict evidence, and concurrent idempotency.
