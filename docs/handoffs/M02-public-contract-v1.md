# [M02] Public API contract v1 — Completion Report

Phase 0 of `IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md`. The service phases (1 onward)
have their own report in `M02-public-api-foundation.md`; this one covers the contract alone, because
it merges on its own branch and every other module depends on it before any service exists.

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 02 — API and backend. `packages/contracts` is shared, maintained by 02 |
| Issue/PR | [#15](https://github.com/PROxTAE/travel-safety-ai/pull/15) |
| Branch | `contract/02-public-travel-schema` |
| Base/final commit SHA | base `b633480`; final SHA recorded on the PR after the last push |
| Date/time/timezone | 2026-09-20, Asia/Bangkok |
| Reviewers | 01 (TypeScript client), 03 (`TravelRequest`, `RunRef`, SSE), 04 (producer records), 08 (`RecommendationResponse`, `OfficialContact`) |
| Contract version | 1.0.0 — the baseline |
| Docker image digest/tag | N/A — nothing here is built into an image |
| Related model/policy/prompt/collection version | N/A |

## 2. Executive summary

Freezes the vocabulary all eight modules build against: 31 canonical entities as JSON Schema
draft 2020-12, a public OpenAPI 3.1 document covering all 23 operations from §4 of
`00_API_AND_DATA_CONTRACTS.md`, and TypeScript and Python clients generated from that one source.

The value is preventing a specific, expensive failure. Eight modules are being written in parallel;
without one definition of `Trip`, `RouteCandidate` and `RecommendationResponse`, each invents its
own, and the disagreement surfaces at integration time when everything is already built.

Review found that the first version of these schemas rejected every record module 04 actually
produces — four disagreements, none of which the self-consistent fixture tests could have caught.
That is fixed, and a real producer test now validates module 04's own Pydantic models against these
schemas so it cannot happen again silently.

Nothing is implemented here. This is contract, tooling, fixtures and tests. It is ready to merge:
the pipeline is green, the producer tests pass against a real module, and `npm audit` is clean.

## 3. Original responsibility and acceptance criteria

Phase 0 of the module plan, step by step:

- [x] **Read 8 module inputs/outputs and write a field ownership matrix** — `docs/api/field-ownership-matrix.md`
- [x] **Create the public OpenAPI v1 and the common JSON Schemas from the contract doc** —
  `packages/contracts/openapi/public-api.yaml`, `jsonschema/common/*.schema.json` (31 entities)
- [x] **Add sanitized success/error/SSE examples** — `examples/structural/` and
  `examples/real-sanitized/`, six fixtures, each validated against the schema it names
- [x] **Set up lint + generator** — redocly lint, ajv schema and example validation, bundling,
  TypeScript and Python generation, all gated in `.github/workflows/contracts.yml`
- [ ] **Breaking-change check** — **not done.** `oasdiff` against `origin/main` is not wired. There
  is no previous version to diff against for a baseline, but the gate must exist before the first
  change lands. Owner: 02. See §15.
- [ ] **Review by 01/03/08 before merging the contract PR** — requested on #15, not yet given.
  Blocking by the plan's own wording, and 04's review has already changed the contract materially.

Scope change from the plan: the plan says "OpenAPI public v1 and common JSON Schema". The six
internal service documents named in §9 of the contracts doc are **not** here — each belongs to its
module owner, and writing them centrally would have meant guessing six teams' internals.

## 4. What was implemented

### Features

| Feature | Behavior now | Entry point | Status |
| --- | --- | --- | --- |
| Canonical entities | 31 schemas, draft 2020-12, cross-referencing by file name | `jsonschema/common/` | Complete |
| Public API description | 23 operations from §4, plus `/health/live` and `/health/ready` | `openapi/public-api.yaml` | Complete |
| Field ownership matrix | Who may write each entity and field | `docs/api/field-ownership-matrix.md` | Complete |
| Lint / validate | redocly, ajv over all schemas and examples, TS consumer compile | `npm run check` | Complete |
| Client generation | Bundled OpenAPI, TypeScript types, Pydantic v2 models | `npm run generate` | Complete |
| Generated-tree gate | Regenerates and fails if the working tree moves | `scripts/check-generated-clean.sh` | Complete |
| Producer/consumer tests | 75 tests, including 16 against module 04's real models | `tests/contract/` | Complete |
| Breaking-change detection | — | — | **Not implemented** |

### Important flows

```text
jsonschema/common/*.schema.json  +  openapi/public-api.yaml
        -> redocly bundle          -> scripts/bundle.mjs normalises
        -> generated/openapi/public-api.bundled.yaml
        -> openapi-typescript      -> generated/typescript/public-api.d.ts
        -> datamodel-code-generator-> generated/python/.../public_api.py
        -> CI regenerates and fails if the tree moved
```

### What is explicitly not implemented

- The six internal service OpenAPI documents (§5 of the contracts doc) — owned per module
- Breaking-change detection between contract versions
- Any runtime behaviour: no service, no endpoint, no database

## 5. Actual architecture and code design

### Folder/file map

| Path | Purpose | Important owner/consumer |
| --- | --- | --- |
| `packages/contracts/jsonschema/common/` | 31 canonical entities | 02 maintains; every module consumes |
| `packages/contracts/openapi/public-api.yaml` | The public surface | 02; reviewed by 01, 03, 08 |
| `packages/contracts/generated/` | Bundled spec, TS types, Pydantic models | Nobody — generated, CI-enforced |
| `packages/contracts/examples/` | Structural and real-sanitized fixtures | Tests only; no runtime code may read them |
| `packages/contracts/scripts/` | bundle, validate, generate, clean-check | 02 |
| `tests/contract/` | 75 producer and consumer tests | 02 |
| `docs/api/field-ownership-matrix.md` | Who writes what | All |

### Main components

| Symbol | Responsibility | Inputs/outputs | Design notes |
| --- | --- | --- | --- |
| `scripts/bundle.mjs` | Bundle and normalise | source YAML → bundled YAML | Strips `$schema`/`$defs`, folds duplicate file-derived component names, exits non-zero if one cannot be resolved |
| `scripts/generate-python.sh` | Pydantic models | bundled YAML → `public_api.py` | Pins the generator version; forces UTF-8 so a non-ASCII description does not produce an undecodable file on Windows |
| `scripts/check-generated-clean.sh` | The gate CI runs | working tree → exit code | Regenerates and fails if anything moved |
| `primitives.schema.json#/$defs/RecordId` | Producer-minted identity | — | Stable and reproducible; see the decision below |
| `primitives.schema.json#/$defs/ContentHash` | Algorithm-prefixed digest | — | `sha256:<hex>` |

### Decisions/trade-offs

**Decision: a producer's record id is a stable `RecordId`, not a UUID.**
Alternatives considered: UUIDv5 derived from provider key plus record id, which is also stable but
unreadable in a log. Reason: module 05 deduplicates by source id, so fetching the same earthquake
twice must produce the same identifier; a fresh UUID per fetch makes deduplication impossible and
would have the same hazard arrive as a new event on every poll. Consequence: ids are provider-shaped
strings like `usgs:us7000abcd`, readable in a trace, and the format is wide enough that a service
minting a record with no upstream identity can still use a UUID.

**Decision: `DataQuality.score` is nullable, and a null score is not a quality problem.**
Alternatives considered: requiring a score and letting each producer invent a formula. Reason: no
weighted formula has been agreed with module 05 yet, and a placeholder number is indistinguishable
from a measured one by the time a decision is made on it. Consequence: consumers must handle a null
score, and `score_version` is conditionally required so a number that cannot be attributed to a
formula cannot validate.

**Decision: `score_version`, not `formula_version`.**
Alternatives considered: keeping `formula_version`, which is arguably less ambiguous. Reason: module
04 has already shipped `score_version` to `main`; forcing a rename in merged code to satisfy an
unmerged contract is the more disruptive direction. Consequence: the description has to carry the
disambiguation the name does not. **Module 05 owns this field and should say if it disagrees.**

**Decision: `content_hash` names its algorithm.**
Reason: a bare hex digest is ambiguous the moment a second algorithm appears, and an unprefixed
value compares unequal to a prefixed one silently rather than failing.

**Decision: `magnitude` requires `magnitude_unit`.**
Reason: 5.8 Mw and 5.8 mb are different measurements of different things. Comparing them as one
number is a safety error, not a rounding one.

**Decision: responses open, request bodies `additionalProperties: false`.**
Reason: an added optional field stays backward compatible for readers, while an unrecognised field
on input is a client bug or an attack and ignoring it hides both.

**Decision: no `$id` on the schemas.**
Reason: with `$id`, relative `$ref`s re-root at an unfetchable URL, and redocly, ajv,
openapi-typescript and datamodel-code-generator all fail to resolve them.

**Technical debt accepted:** no breaking-change gate (§15).

## 6. API, contract and event changes

| Producer | Method/path/event | Request schema | Response schema | Consumer | Compatibility |
| --- | --- | --- | --- | --- | --- |
| 02 | 23 public operations under `/api/v1` | `*Request` schemas, closed | `*Response` envelopes | 01 | New — baseline |
| 04 | canonical records | — | `SourceProvenance`, `DataQuality`, `WeatherForecastPoint`, `DisasterEvent`, `LocationRef` | 02, 05, 06 | **Changed during review** — see below |

Changes made after review, all to make the schemas accept records module 04 already produces. The
contract has not merged and nothing consumes it yet, so this amends the 1.0.0 baseline rather than
bumping it:

| Field | Was | Now | Why |
| --- | --- | --- | --- |
| `SourceProvenance.source_id` | `Uuid` | `RecordId` | Must be stable for deduplication |
| `SourceProvenance.content_hash` | `Sha256Hex`, required non-null | `ContentHash`, nullable | Producers emit `sha256:<hex>`; a record assembled from several responses has no single payload |
| `SourceProvenance.source_url` | required non-null | nullable | A bulk feed has no per-record address |
| `DataQuality.score` | required number | nullable | No agreed formula yet; a placeholder is worse than none |
| `DataQuality.formula_version` | required | `score_version`, nullable, conditionally required | Matches the shipped producer |
| `DataQuality.conflicts[].source_ids` | `Uuid` | `RecordId` | References provenance ids |
| `WeatherForecastPoint.id`, `WeatherObservation.id`, `TransportStatus.id`, `DisasterEvent.event_id`, `EmergencyPoi.poi_id`, `SafetyEvent.event_id` | `Uuid` | `RecordId` | Producer-minted |
| `DisasterEvent` | — | `+ magnitude_unit`, `+ depth_km` | A magnitude without its scale is not a measurement |
| `RouteCandidate.exposure.closure_source_ids`, `IntegratedTravelContext.source_ids`, `DecisionResult` source references, `RiskAssessment.SafetyOverride.evidence_source_ids` | `Uuid` | `RecordId` | All reference provenance ids |

- **Generated client command/result:** `npm run generate` — bundled 3,966 lines, TypeScript 2,818
  lines, Python 1,545 lines. Reproducible; CI fails if regeneration moves the tree.
- **Contract lint result:** `Woohoo! Your API description is valid.` — 0 failed, 2 explicitly
  ignored (`/health/*` document no 4xx; the reason is in `.redocly.lint-ignore.yaml`).
- **Breaking check result:** none — not wired. See §15.
- **Deprecation/migration plan:** from here, adding an optional field is minor; renaming, retyping,
  removing, or making a field required is breaking and needs `/v2` or a deprecation window.
- **Sanitized example location:** `packages/contracts/examples/`.

## 7. Database, cache and storage changes

### Migrations

None. No table, index, Redis key or Qdrant collection is created by this PR.

- Empty DB → head: N/A
- Previous main → head: N/A
- Restart persistence: N/A
- Backup/restore: N/A
- Retention/cleanup: N/A
- Encryption/access control: N/A

### Redis/Qdrant/artifact changes

None.

## 8. External providers and real data

| Provider/source | Endpoint/capability | Coverage | Credential ref | Freshness/TTL | License/attribution | Last canary |
| --- | --- | --- | --- | --- | --- | --- |
| Open-Meteo Geocoding | `/v1/search?name=Bangkok&count=2` | One fixture only | none — public endpoint | `captured_at: 2026-09-19T08:11:38Z` | Open-Meteo terms; GeoNames-derived data CC BY 4.0, attribution carried in the fixture | 2026-09-19, manual |

- **Runtime/demo contains no mock or hard-coded current data:** [x] — there is no runtime here at
  all. A test in `tests/contract/` asserts that nothing under `services/*/app` reads a fixture folder.
- **Test fixture source/captured_at/redaction/license:** every file in `examples/real-sanitized/`
  carries `source_url`, `captured_at`, `upstream_content_hash`, `license` and a redaction note.
  `examples/structural/` is hand-written with synthetic values and is kept separate on purpose.
- **Unsupported/unavailable capability behavior:** described in the schemas rather than implemented:
  a value the provider did not supply is `null` and the field is still required, so "zero" and
  "unknown" cannot be confused.
- **Schema drift/quota/failover behavior:** the fixture records the upstream content hash, so drift
  is detectable rather than silent.

## 9. Configuration and Docker

### Environment variables added/changed

None.

### Run commands

```bash
cd packages/contracts
npm ci

npm run lint              # redocly
npm run validate:schemas  # compiles all 31 schemas with ajv
npm run validate:examples # every fixture against the schema it names
npm run typecheck         # the TypeScript consumer check compiles
npm run generate          # bundle -> TypeScript -> Python   (needs uv on PATH)
./scripts/check-generated-clean.sh   # what CI runs

cd ../..
uv run --project tests/contract pytest tests/contract
```

- **Container user / ports / networks / volumes:** N/A — nothing runs.
- **Health/readiness behavior:** N/A.
- **CPU/RAM/disk measured:** N/A.
- **Image size/digest:** N/A.

## 10. Tests and verification

| Test type | Command | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Lint | `npm run lint` | 1 | 0 | 2 ignored | `Woohoo! Your API description is valid.` |
| Schema validation | `npm run validate:schemas` | 31 | 0 | 0 | `31 schemas compiled.` |
| Example validation | `npm run validate:examples` | 6 | 0 | 0 | `6 examples validated.` |
| Type (TS consumer) | `npm run typecheck` | 1 | 0 | 0 | `tsc` exit 0 |
| Contract | `uv run --project tests/contract pytest tests/contract` | 75 | 0 | 0 | includes 16 real-producer tests |
| Generated-tree gate | `./scripts/check-generated-clean.sh` | 1 | 0 | 0 | `Generated contract output matches the source.` |
| Security (dependencies) | `npm audit` | — | 0 | 0 | `found 0 vulnerabilities` (was 18: 2 critical, 5 high, 11 moderate) |
| Integration / E2E / load / accessibility | — | — | — | — | N/A — nothing runs |

### Scenarios verified

- **Success:** every fixture validates; both generators produce working output; module 04's real
  `SourceProvenance`, `DataQuality`, `WeatherForecastPoint`, `DisasterEvent` and `LocationRef`
  validate against the canonical schemas.
- **Invalid input/unauthorized:** the contract documents 401 on every authenticated operation and a
  test asserts it; request bodies are closed and a test asserts that too.
- **Timeout/429/5xx:** the codes are defined and tested for presence. Nothing runs, so behaviour is
  not exercised here.
- **Stale/partial/conflicting data:** `DataStatus`, `QualityFlag`, the `PARTIAL` recommendation
  fixture, and a producer test for `DataQuality.unavailable()`.
- **Cancellation/idempotency/concurrency:** the contract requires `Idempotency-Key` or `If-Match` on
  every mutating operation, and a test enforces it.
- **Restart/rollback:** N/A.

Negative cases are asserted as well as positive ones: a `score` without its `score_version`, and a
`magnitude` without its `magnitude_unit`, must both fail validation.

No request/correlation/trace IDs — nothing serves a request yet.

## 11. UI evidence

N/A — no UI in this work.

## 12. Safety, security and privacy review

- [x] official warning/closure priority preserved — `RouteCandidate.exposure.closed` and
      `DecisionResult.validation.locked_action` are required; `DisasterEvent` documents that an
      active official alert is never dropped because another provider stopped answering
- [x] LLM/provider/RAG data treated as untrusted — stated in every schema carrying provider or model
      text, and `DisasterEvent.description` says so explicitly
- [x] no secret/PII/exact location in code/log/trace/fixture — a test greps the contract sources for
      secret-shaped strings; the one real fixture describes a city, not a person
- [x] consent/auth/ownership enforced — `ConsentRecord` is append-only and versioned;
      `EmergencyProfile` documents application-layer encryption and log exclusion; a resource owned
      by another user is specified as 404, not 403, so ids cannot be enumerated
- [x] timeout/retry/cancel/idempotency bounded — required on every mutating operation by the
      contract and asserted by a test
- [x] source/freshness/quality/version retained — `SourceProvenance` and `DataQuality` are required
      on every safety-relevant entity
- [x] fallback/degraded behavior does not invent data — a provider-absent value is `null` and the
      field stays required; `observed_at` is null rather than borrowing `fetched_at`
- [x] dependency/image/secret scans passed — `npm audit` reports 0 vulnerabilities after bumping
      `@redocly/cli` to 2.53.3, `ajv` to 8.20.0, `yaml` to 2.9.1 and `openapi-typescript` to 7.13.0.
      No image is built here.

**Findings and resolutions:** the dependency scan found 18 vulnerabilities including 2 critical
(`form-data`) and 5 high (`js-yaml`, `@faker-js/faker`), all transitive under `@redocly/cli` 1.34.2.
Resolved by upgrading rather than by an override, and the major bump to redocly 2.x was verified not
to change lint output.

## 13. Problems encountered and resolutions

| Problem | Root cause | Evidence | Resolution/workaround | Remaining risk |
| --- | --- | --- | --- | --- |
| Every module-04 record rejected | Schemas specified UUID ids, bare-hex hashes and a required quality score; the shipped producer does none of those, and was right not to | `tests/contract/test_real_producer_records.py` failed on all four before the fix | `RecordId`, `ContentHash`, nullable `score`, `score_version`, `magnitude_unit` | Other producers (05–08) have not shipped, so their records are still unverified against these schemas |
| `$id` broke `$ref` resolution | With `$id`, relative refs re-root at an unfetchable URL | redocly, ajv and both generators all failed | Removed `$id` from all 31 schemas; refs resolve by file name | A future tool that requires `$id` would need this revisited |
| `datamodel-codegen` refused a single output file | Bundling registers a duplicate component named after the source file (`consent-record.schema`), and the dot makes it demand a package | "Modular references require an output directory" | `bundle.mjs` folds each onto its canonical name and exits non-zero if one cannot be resolved | A new entity without an explicit `components.schemas` entry fails the build — deliberately |
| Generated Python file was undecodable | `datamodel-codegen` wrote the system code page on Windows; an em-dash in a description became byte `0x97` | `UnicodeDecodeError: invalid start byte` at position 31129 | `generate-python.sh` exports `PYTHONUTF8=1`, `PYTHONIOENCODING`, `LC_ALL` | None — CI on Linux never saw it, which is why it needed catching here |
| Contract pipeline failed on the runner | Shell scripts lost their exec bit on Windows; `pytest` with no path collected every service suite | exit 126, then `ModuleNotFoundError: pydantic_settings` | `git update-index --chmod=+x`, invoke via `bash`, pass the test path explicitly | None |
| `Uuid` with both `format` and `pattern` broke Pydantic generation | The pattern forced the value back to a bare string | Generator error | Dropped the pattern, kept `format: uuid` | None |

## 14. Performance and operational behavior

| Metric | Target | Actual | Test condition | Pass |
| --- | --- | --- | --- | --- |
| Full contract pipeline | < 2 min | ~32 s | GitHub-hosted runner, `ubuntu-latest` | Yes |
| Contract test suite | < 5 s | 0.63 s | 75 tests, local | Yes |

- **Metrics/dashboard/alerts added:** none — nothing runs.
- **Log fields/redaction verified:** N/A.
- **Circuit/rate/quota/cache behavior:** N/A.
- **Incident disable/rollback steps:** §18.

## 15. Known limitations and technical debt

| Limitation/debt | User/safety impact | Workaround | Owner | Priority | Follow-up |
| --- | --- | --- | --- | --- | --- |
| No breaking-change detection | A breaking change could merge without a version bump, and the first sign would be a consumer failing | Review plus the consumer checks | 02 | **High** — must land before the first contract change | Wire `oasdiff` against `origin/main` in `contracts.yml` |
| Only module 04's records are verified against the schemas | Modules 05–08 may hit the same class of rejection this review found | Extend `test_real_producer_records.py` as each producer ships | Each producer owner | High | — |
| `DataQuality.conflicts` shapes disagree | Module 04 types it as `list[str]`; the contract expects objects. 04 never populates it today | A test fails the day 04 starts using it | 05 (owns conflict detection) | Medium | — |
| `datamodel-code-generator` flattens `prefixItems` | Generated Pydantic `Position` accepts a longitude of 1000; the JSON Schema does enforce the range | The API validates coordinates at the boundary | 02 | Medium | Pinned by `test_generated_python_does_not_enforce_coordinate_bounds`, which fails if a generator upgrade closes the gap |
| `packages/contracts` uses npm, `apps/web` will use pnpm | Two lockfile formats in one repository | — | 01 + 02 | Low | Fold into the pnpm workspace when `apps/web` lands |
| Module-08 entities were drafted by 02 | 08 may disagree with its own entities | Owner 08 should treat them as a proposal | 08 | Medium | Review on #15 |
| Six internal service OpenAPI documents absent | Cross-service calls are described in prose, not schema | Each owner writes their own | 03–08 | Medium | — |

## 16. Handoff to other members

| Recipient/module | What is ready | What they must change/do | Contract/config | Blocking? |
| --- | --- | --- | --- | --- |
| 01 web | `generated/typescript/public-api.d.ts` | Import types from there; do not restate request/response shapes | `packages/contracts/generated/typescript` | Yes — review requested on #15 |
| 03 agent | `TravelRequest`, `RunRef`, `RunState`, SSE event payloads | Confirm the stage vocabulary and the SSE envelope match the graph | `sse-events.schema.json`, `run-state.schema.json` | Yes — review requested |
| 04 external-data | `SourceProvenance`, `DataQuality`, record schemas now accept real output | **Nothing to change.** The contract moved to match the code. Confirm `RecordId`, `ContentHash` and `magnitude_unit` are what you intended | `jsonschema/common/` | Yes — review requested; your feedback drove these changes |
| 05 data-integration | `IntegratedTravelContext`, `DataQuality` | Decide whether `score_version` is the right name, and reconcile `conflicts` as objects vs strings | `data-quality.schema.json` | Yes — you own the formula |
| 06 risk-knowledge | `RiskAssessment`, `RetrievedEvidence`, `RouteCandidate` | Confirm `reason_codes` vocabulary; note `contract/06-…` is open in parallel and may collide | `risk-assessment.schema.json` | No, but coordinate |
| 07 decision-engine | `DecisionResult` | Confirm `rules_fired` and `validation` | `decision-result.schema.json` | No |
| 08 recommendation | `RecommendationResponse`, `OfficialContact`, `FeedbackEvent`, `AlertSubscription` | These were drafted here because the public API cannot be described without them. Treat as a proposal, not a decision | `jsonschema/common/` | Yes — review requested |

Everything above is on branch `contract/02-public-travel-schema`, PR #15. Generated clients live at
`packages/contracts/generated/{typescript,python}` and must never be edited by hand.

## 17. Commit and PR inventory

```text
contract(contracts): add public API v1 and canonical entity schemas
build(contracts): add contract lint, validation and client generation
test(contracts): add contract fixtures and producer/consumer tests
ci(contracts): gate pull requests on the contract pipeline
fix(ci): make the contract pipeline pass on a runner
fix(ci): scope the contract test run to its own directory
fix(contracts): accept the records real producers emit
build(contracts): bump the toolchain off vulnerable transitive dependencies
docs(contracts): add the phase 0 completion report
```

- **PR review comments resolved:** the four contract findings and the dependency audit finding are
  resolved in this push. The breaking-change gate is accepted as debt (§15).
- **Required checks status:** `contracts` green, `ci` green.
- **Rebased on main SHA:** `b633480`.
- **Squash title proposed:** `[M02] Freeze public API contract v1 and wire client generation (#15)`

## 18. Rollback and recovery

1. **Feature flag/provider disable:** N/A — nothing runs.
2. **Application rollback image/tag:** N/A.
3. **Migration downgrade or forward-fix:** N/A — no migrations.
4. **Model/policy/prompt/knowledge rollback:** N/A.
5. **Data/cache cleanup:** N/A. No volume or database is touched by this work.
6. **Verification after rollback:** revert the merge commit; nothing consumes the contract yet, so
   there is no compatibility window to manage. Confirm with `npm run check` on `main`.

## 19. Final declaration

- [x] Work in scope is complete against the evidence above, with two exceptions recorded in §3 and
      §15: breaking-change detection is not wired, and downstream review has not been given.
- [x] No required work is hidden. The unfinished items are named with an owner and a priority.
- [x] Documentation, env, contracts and migrations are updated — no env or migration changes exist
      in this work, and `docs/api/field-ownership-matrix.md` is updated for `score_version`.
- [x] Downstream owners have a handoff (§16).
- [x] Ready to merge — pipeline green, producer tests passing against a real module, audit clean.
- [ ] Ready to release — N/A. A contract alone is not releasable; it becomes releasable with the
      service that serves it.

ผู้จัดทำ: module 02 owner
