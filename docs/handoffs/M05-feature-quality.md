# [M05] Feature vector and quality gate completion report

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 05 Data Integration |
| Issue/PR | Pending review PR, stacked on `feat/05-route-corridor-geometry` |
| Branch | `feat/05-feature-quality` |
| Base/final commit SHA | Base `origin/main` `3353f15`; phase commits `2b97108`, `ceab738`, `f925c43`, `dca15c8`, `550e39b` |
| Date/time/timezone | 2026-09-21 Asia/Bangkok |
| Reviewers | Module 06 feature owner (schema consumer), module 03/07 (quality gate), contract owner |
| Contract version | Canonical v1; feature schema `1.0.0` as proposed by module 06 at `origin/contract/06-risk-evidence-route-schema` `e85d589` |
| Docker image digest/tag | `smart-travel-data-integration:runtime` `sha256:67942c6dfa7eb644b8287866845d5e50f11572243643c3e1d48eee9ecc5da840` |
| Related model/policy/prompt/collection version | Quality policy version is caller-supplied through `QualityPolicy.version` |

## 2. Executive summary

This phase turns aligned route evidence into the 13 features that module 06 proposed in `feature_schema.v1.yaml`. It also adds a versioned quality gate that returns PASS, DEGRADED, or BLOCK. The builder is pure and deterministic. It never turns an unavailable source into `0` or `False`. Evidence fetched, published, or observed after the recommendation time is dropped before any value is computed. The schema file is a verbatim copy of the module 06 proposal, so both modules validate against the same names, units, and ordinals.

## 3. Original responsibility and acceptance criteria

From `IMPLEMENTATION_PLANS/05_DATA_INTEGRATION_IMPLEMENTATION.md` §6, §7 and Phase 5:

- [x] Deterministic feature builder following the schema agreed with module 06: `app/pipeline/features.py`.
- [x] Missing values stay missing, and the leakage cutoff uses the recommendation time. `FeatureVector.null_features` lists every null value.
- [x] Quality gate PASS/DEGRADED/BLOCK with a versioned policy: `app/pipeline/quality.py`.
- [ ] Weighted quality score (freshness/completeness/coverage/agreement/authority). The owner decided to move this to the next PR.
- [ ] Snapshot, content hash, and endpoints belong to PR 7 (`feat/05-snapshot-api`).

## 4. What was implemented

### Features

| Feature | Behavior now | Entry point | Status |
| --- | --- | --- | --- |
| Route size | `route_distance_m`, `route_duration_seconds`, `route_transfer_count` copied from the provider route | `build_features` | Complete |
| Official alert flags | Closure and EXTREME are computed from official events active in the travel window. Evacuation is always null because no producer publishes evacuation orders. | `_disasters` | Flagged |
| Hazard area | Share of route length whose sample lies inside an active Polygon/MultiPolygon at its ETA. Dateline-safe. | `_disasters`, `_in_area` | Complete |
| Weather | Severity ordinal, precipitation probability as a ratio, and gust, all taken from forecasts matched to route ETA | `_weather` | Complete |
| Transport | Worst mapped status across linked transit segments. A stale or unmatched status maps to UNKNOWN (4). | `_transport` | Complete |
| Evidence coverage | Minimum of weather coverage, disaster availability, and transit status coverage (transit modes only) | `_coverage` | Partial: unweighted |
| Evidence freshness | Oldest `freshness_seconds` among the critical sources. Null if any critical age is unknown. | `_freshness` | Partial: reported age |
| Quality gate | BLOCK for invalid identity or geometry, or missing critical evidence. DEGRADED for low, unknown, stale, or conflicting evidence. | `summarize_quality` | Complete |

### Important flows

1. The caller passes the route, its ETA samples from `sample_route`, and the provider records. A list of `None` means the source was unavailable; `[]` means the source answered with nothing.
2. `_before_cutoff` removes records known after `recommendation_at`. If every record is removed, the source is treated as unavailable at the cutoff.
3. Each group computes its values. `build_features` then walks the schema in order, rejects a null for a non-nullable feature, and rejects any computed name that the schema does not declare.

### What is explicitly not implemented

- `route_region_h3_features` from the earlier v0.1.0 draft. Module 06 v1.0.0 does not include it.
- Weighted quality score, snapshot persistence, and endpoints.

## 5. Actual architecture and code design

### Folder/file map

| Path | Purpose | Important owner/consumer |
| --- | --- | --- |
| `services/data-integration/app/pipeline/feature_schema.yaml` | Verbatim copy of module 06 `feature_schema.v1.yaml` (`e85d589`) | Module 06 owns the source file |
| `services/data-integration/app/pipeline/features.py` | Pure feature builder | Snapshot builder (PR 7), module 06 |
| `services/data-integration/app/pipeline/quality.py` | Quality summary and gate | Snapshot builder, modules 03/07 |
| `services/data-integration/tests/test_features.py` | 11 feature cases on module 04 captures | |
| `services/data-integration/tests/test_quality.py` | Gate boundary cases | |

### Main components/classes/functions

| Symbol | Responsibility | Inputs/outputs | Design notes |
| --- | --- | --- | --- |
| `build_features` | Compute and validate all schema features | `FeatureInputs`, `FeaturePolicy` → `FeatureVector` | Output order follows the schema; any undeclared name raises |
| `FeatureVector` | `schema_version`, `values`, `null_features` | | `null_features` feeds the MISSING flag the schema requires |
| `OFFICIAL_ALERT_FEATURES` | Official alert booleans, null when alerts are unavailable | | Nullable per Lead decision on #43 |
| `summarize_quality` | Gate plus flags | Per-source `DataQuality` → `QualitySummary` | An unknown score stays `None`, never 0 |

### Decisions/trade-offs

- The builder follows the module 06 v1.0.0 proposal instead of the module 05 v0.1.0 draft, because module 06 rejects unknown features and unsupported versions.
- Staleness comes from the producer's `status`. A single global age threshold would call an eight-day-old road graph stale.
- Hazard fraction is computed with a pure even-odd test on route samples, so the builder does not need a database session. The precision is one sample interval.

## 6. API, contract and event changes

| Producer | Method/path/event | Request schema | Response schema | Consumer | Compatibility |
| --- | --- | --- | --- | --- | --- |
| M05 | None in this PR | | `features` map inside `IntegratedTravelContext` (already typed as `number/string/boolean/null`) | M06 | No shared schema change |

The feature set follows module 06's proposal as amended by the Lead decision on #43 and #44: the three `corridor_official_*` booleans are `nullable: true`, and `corridor_official_evacuation_active` is `critical: false` until a provider supplies evacuation orders. The local schema copy carries both changes; module 06 applies the same change in PR #12.

## 7. Database, cache and storage changes

None in this phase. There are no migrations and no Redis or Qdrant changes.

## 8. External providers and real data

| Provider/source | Endpoint/capability | Coverage | Credential ref | Freshness/TTL | License/attribution | Last canary |
| --- | --- | --- | --- | --- | --- | --- |
| Open-Meteo (via M04 capture) | Hourly forecast, Bangkok | Test fixture only | Keyless | Captured 2026-09-19T07:45:37Z | CC-BY-4.0 | n/a |
| USGS (via M04 capture) | Earthquake feed | Test fixture only | Keyless | Captured, HTTP 200 | Public domain | n/a |
| MTA GTFS-Realtime (via M04 capture) | Trip update | Test fixture only | per M04 | Producer marked STALE | per M04 | n/a |

Test-only route lines and hazard squares sit on the captured coordinates. The runtime has no mock or hard-coded current data.

## 9. Configuration and Docker

No new environment variables. `pyyaml==6.0.3` is now a declared dependency; before this it was only installed through `uvicorn[standard]`. `uv.lock` changes by 2 lines.

```bash
docker compose -f compose.yaml -f compose.dev.yaml build data-integration
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run pytest -q
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run ruff format --check app tests
docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration uv run --with mypy==1.13.0 --with types-PyYAML mypy app
docker compose -f compose.yaml build data-integration
```

## 10. Tests and verification

| Test type | Command | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Lint | `ruff check app tests` | all | 0 | 0 | `All checks passed!` |
| Format | `ruff format --check app tests` | 49 files | 0 | 0 | `49 files already formatted` |
| Type | `mypy app` | new files clean | 23 pre-existing | 0 | `Found 23 errors in 4 files (checked 37 source files)`, all in `normalize.py`, `dedup.py`, `canonical_repo.py`, `alignment.py`; none in this phase's files |
| Unit + DB integration | `pytest -q` | 53 | 0 | 0 | `53 passed in 3.87s` |
| Runtime image | `docker compose -f compose.yaml build data-integration` | exit 0 | | | digest in §1 |
| Contract/E2E/Load | n/a | | | | Endpoints arrive in PR 7 |

### Scenarios verified

- Success: captured Bangkok forecast produces probability ratio 0.39, gust 19.8, severity ordinal 5 (UNKNOWN), coverage 1/3.
- Unavailable source: every dependent feature is null and listed in `null_features`; coverage is 0.
- Answered empty: closure and EXTREME are `False` and hazard fraction is 0; evacuation stays null.
- Stale/partial/conflicting: a stale MTA feed saying DELAYED maps to UNKNOWN (4). An official quake with UNKNOWN severity leaves the EXTREME flag null.
- Boundary: hand-computed hazard fraction of 1/3, once on a normal route and once on a route crossing 180°.
- Leakage: a forecast fetched after the recommendation time is excluded.
- Determinism: two builds serialize identically.

## 11. UI evidence

Not applicable: this phase changes an internal service only.

## 12. Safety, security and privacy review

- [x] Official warning/closure priority preserved: an official EXTREME cannot be hidden, and an UNKNOWN severity cannot become `False`.
- [x] Provider data treated as untrusted: canonical models validate every input.
- [x] No secret, PII, or exact user location in code or fixtures.
- [x] Source, freshness, quality, and version are retained: `FeatureVector.schema_version`, `QualityPolicy.version`.
- [x] The fallback never invents data: unavailable becomes null, never 0 or `False`.
- [ ] Dependency/image scans: not run in this phase.

## 13. Problems encountered and resolutions

| Problem | Root cause | Evidence | Resolution/workaround | Remaining risk |
| --- | --- | --- | --- | --- |
| Two feature schemas | M05 drafted v0.1.0 (26 features) while M06 proposed v1.0.0 (13 features, rejects unknown) | `origin/contract/06-risk-evidence-route-schema:services/risk-knowledge/governance/feature_schema.v1.yaml` | Owner chose M06 v1.0.0; the v0.1.0 draft is retired | The proposal is not yet approved by both sides |
| Official booleans non-nullable | The M06 proposal set `nullable: false` | Schema lines 36-56 | Lead decided nullable (#43); schema copy updated and guarded by a test | M06 PR #12 must carry the same change |
| No evacuation data | No M04 provider or contract carries evacuation orders | `git grep -i evacuat` finds nothing in contracts or external-data | Always null | Critical feature null means M06 always returns UNKNOWN |
| Stale route misread | Road graph age (689760 s) compared with a realtime threshold | M04 route fixture | Features use producer `status` | `quality.py` still applies the global threshold; issue raised |
| Lockfile churn | Container uv 0.5.14 is older than the lock's writer | 413-line diff | Re-locked with host uv 0.11.1: 2-line diff | Container and host uv versions differ |

## 14. Performance and operational behavior

The builder is pure Python at O(samples × records). It has not been benchmarked; load targets belong to PR 8.

## 15. Known limitations and technical debt

| Limitation/debt | User/safety impact | Workaround | Owner | Priority | Follow-up issue |
| --- | --- | --- | --- | --- | --- |
| Evacuation feature always null | No longer blocks assessments: Lead set it non-critical (#44) | None | M04 provider | Medium | #44 |
| Official booleans nullable | Resolved by Lead decision (#43) | n/a | M06 PR #12 | Done on M05 side | #43 |
| `align_disaster` assumes Point geometry | Crashes on Polygon events | Builder avoids it for areas | M05 | High | Draft 3 |
| `quality.py` global freshness threshold | Car routes always DEGRADED | None | M05 | Medium | Draft 4 |
| Coverage is unweighted min | Conservative, not the §7 weighted score | Min is safe-side | M05 | Medium | Next PR |
| Freshness is reported age, not age at snapshot time | Understates age by the time since fetch | Snapshot can add elapsed time | M05 | Low | Draft 5 |
| 23 pre-existing mypy errors, no typecheck gate | Type bugs can slip, as with the Polygon crash | Run mypy manually | M05 | Medium | Draft 6 |
| PR larger than 400 lines (about 780 including quality commits) | Heavier review | Split option in PR body | M05 | Low | n/a |

## 16. Handoff to other members

| Recipient/module | What is ready | What they must change/do | Contract/config | Blocking? |
| --- | --- | --- | --- | --- |
| M06 | Features that match your v1.0.0 names, units, and ordinals | Approve the schema; decide whether the official booleans can be null | `feature_schema.v1.yaml` | Yes, for the snapshot handoff |
| M04 | n/a | Say whether any source can supply evacuation or no-go orders | canonical v1 | No |
| M03/M07 | Gate semantics | Agree on the DEGRADED/BLOCK handling | `QualitySummary` | No |

## 17. Commit and PR inventory

- `2b97108` feat(integration): add versioned evidence quality gates
- `ceab738` test(integration): align quality conflict fixture with contract
- `f925c43` build(integration): declare the YAML parser the feature schema needs
- `dca15c8` feat(integration): build the module 06 feature vector v1.0.0
- `550e39b` test(integration): verify feature units, nulls, hazard area, and cutoff
- Rebased on main SHA: `3353f15` (current `origin/main`)
- Squash title proposed: `[M05] Build the module 06 feature vector and the evidence quality gate`

## 18. Rollback and recovery

The phase adds pure functions and a dependency declaration with no migrations. Rolling back means reverting these commits. Nothing calls the builder at runtime until PR 7.

## 19. Final declaration

- [x] The work in scope is complete, with evidence, except the weighted score, which the owner moved to the next PR.
- [x] No required work is hidden; the gaps are listed in §15.
- [x] Documentation and dependencies are updated; there are no contract or migration changes.
- [ ] Downstream owners have received the handoff (pending: issues to M06 and M04).
- [ ] Ready to merge: waits on the M06 schema decision and on review.
