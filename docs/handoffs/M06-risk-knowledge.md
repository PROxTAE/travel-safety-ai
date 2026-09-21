# [M06] Risk and Knowledge Contracts and Service Foundation Report

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | Module 06 — Risk and Knowledge Services |
| Issue/PR | Draft PR #12; body mirrored in `docs/handoffs/M06-risk-knowledge-pr-body.md` |
| Branch | `contract/06-risk-evidence-route-schema` |
| Base/final commit SHA | `9007d524f1f85d999c7729b95f9969456fef5454` / current PR #12 head (reported after push) |
| Date/time/timezone | 2026-09-21 +07:00 (Asia/Bangkok) |
| Reviewers | Required: Team Lead plus contracts/security reviewer; contract consumers: modules 03, 05, and 07 |
| Contract version | `1.0.0` |
| Docker image digest/tag | `sta-risk-knowledge:phase1`, `sha256:f4f488e484659b7fa5cd8320a7d9f63a3b2789241e963cf78a9d5bcceab56c5d` |
| Related model/policy/prompt/collection version | feature `1.0.0`; route policy `1.0.0` pending approval; fallback `fallback-safety-1.0.0`; no active model or collection |

## 2. Executive summary

This report covers Phase 0 and Phase 1 only. It defines the versioned internal
risk, knowledge, route, status, and evidence-package contracts, plus fail-closed
governance documents whose numeric safety values remain deliberately unapproved.
It implements a persistent FastAPI service backed by the module-owned PostgreSQL
`knowledge` schema, Qdrant lifecycle controls, signed artifact verification,
internal authentication, health/readiness, Prometheus metrics, OpenTelemetry,
structured logs, Docker hardening, and conservative deterministic fallbacks.

The service never fabricates current data: without approved model and knowledge
artifacts it returns `UNKNOWN`/`DEGRADED` or explicit unavailable states. Phase
0/1 implementation is complete. PR #12 has merged, and the Team Lead's temporary
acceptance of the upstream-unfixed base-image CVE is now recorded in ADR-006
with mandatory operating conditions. Phases 2–8 are explicitly
out of scope and remain required for the full module.

## 3. Original responsibility and acceptance criteria

### Phase 0 — Contracts and governance

- [ ] Lock risk/evidence/route API with modules 03/05/07 — proposed contract and producer tests are complete; consumer-owner approvals remain external work.
- [ ] Lock feature schema, meanings, and null policy with module 05 — proposal fails closed; module 05 approval remains external work.
- [x] Create model acceptance config, model card, data-manifest schema, and approval guard — `services/risk-knowledge/governance` and `training`.
- [ ] Create approved knowledge-source review process with Team Lead — workflow and schema exist; Team Lead approval remains external work.
- [ ] Define route formula/hard constraints/version — hard constraints and formula shape are defined; numeric coefficients intentionally remain `null` pending modules 05/06/07 approval.

### Phase 1 — Service/storage foundation

- [x] FastAPI, internal auth, health/readiness, metrics, traces, structured logs, and standard error envelopes.
- [x] Shared `INTERNAL_SERVICE_TOKEN` auth and standardized FastAPI/Starlette HTTP errors, including router-level 404 responses.
- [x] PostgreSQL migration, least-privilege module role, Qdrant collection/alias lifecycle, and local MLflow training profile.
- [x] Artifact loader verifies approved `ACTIVE` metadata, path containment, SHA-256, Ed25519 signature, key, and feature schema before availability.
- [x] Non-root/read-only Docker runtime with 2 CPU/2 GiB limits and bounded warmup/dependency readiness.
- [x] Deterministic fallback never emits `LOW` without a model, preserves official hard constraints, and returns empty RAG evidence explicitly.

ADR: `docs/adr/006-risk-knowledge-contract-foundation.md`. The scope was
intentionally stopped after Phase 1 at the user's direction.

## 4. What was implemented

### Features

| Feature | Behavior now | Entry point | Status |
| --- | --- | --- | --- |
| Internal contract | Versioned OpenAPI plus Draft 2020-12 producer schemas | `packages/contracts/openapi/internal-risk-knowledge.yaml` | Complete, approval pending |
| Risk fallback | Active official closure/evacuation/extreme warning can force `HIGH`; otherwise unavailable model returns `UNKNOWN/PARTIAL` | `POST /internal/v1/risk/assess` | Complete for Phase 1 |
| Knowledge fallback | No passage is returned without an approved active collection | `POST /internal/v1/knowledge/retrieve` | Complete for Phase 1 |
| Route fallback | Removes hard-closed routes and does not invent ranking/recommendation | `POST /internal/v1/routes/evaluate` | Complete for Phase 1 |
| Registries | Persistent model/collection stage metadata and activation guards | PostgreSQL repositories and CLI | Complete for Phase 1 |
| Health/telemetry | Process liveness, dependency readiness, metrics, correlation/trace IDs | `/health/*`, `/metrics` | Complete |
| Evidence package | Honest 503 until immutable snapshot retrieval is implemented | `POST /internal/v1/evidence/package` | Deliberately unavailable until Phase 7 |

### Important flows

```text
Authenticated request -> header/body validation -> conservative computation
-> module-owned PostgreSQL persistence -> versioned degraded response

Startup/readiness -> DB migration check -> Qdrant alias/DB registry agreement
-> signed model artifact verification -> ready/degraded/not_ready

Collection prepare -> Qdrant DRAFT collection + PostgreSQL DRAFT metadata
-> external approval metadata -> atomic active alias switch -> previous active retired
```

### What is explicitly not implemented

- Historical ingestion, reproducible labeled dataset, trained/calibrated model, metrics, and promotion (Phases 2–4).
- Approved authority-document ingestion, embeddings, hybrid retrieval, reranking, and citations (Phase 5).
- Numeric full-corridor route exposure/ranking (Phase 6).
- Combined evidence package execution and full real snapshot E2E (Phases 7–8).
- Any runtime mock data, default credentials, synthetic current conditions, or fake success response.

## 5. Actual architecture and code design

### Folder/file map

| Path | Purpose | Important owner/consumer |
| --- | --- | --- |
| `packages/contracts/openapi/internal-risk-knowledge.yaml` | Internal HTTP contract | contracts maintainer; modules 03/05/07 |
| `packages/contracts/jsonschema/risk-knowledge/` | Shared producer/consumer schemas | modules 03/05/06/07 |
| `services/risk-knowledge/app/` | Runtime service, persistence, fallbacks, telemetry | module 06 |
| `services/risk-knowledge/migrations/` | `knowledge` schema revision | module 06 / platform DB operator |
| `services/risk-knowledge/governance/` | feature, acceptance, route-policy gates | modules 05/06/07 and Team Lead |
| `services/risk-knowledge/knowledge/` | approved-source manifest schema and workflow | module 06 / Team Lead |
| `services/risk-knowledge/training/` | dataset manifest and model-card templates | module 06 |
| `infra/postgres/init/01-risk-knowledge-role.sh` | idempotent module-role bootstrap | platform DB operator |

### Main components/classes/functions

| Symbol | Responsibility | Inputs/outputs | Design notes |
| --- | --- | --- | --- |
| `RuntimeState` | Refresh model/knowledge availability | registry + artifact/Qdrant -> status | hard timeout avoids stalled readiness cancellation |
| `ArtifactVerifier` | Verify artifact trust before serving | `ActiveModel` -> verified artifact | SHA-256, Ed25519, path containment, approval metadata |
| `QdrantManager` | Prepare collections and atomically move alias | version/vector size -> collection/alias | activation CLI requires DB `APPROVED` record |
| `assess_with_conservative_fallback` | Safety-preserving risk output | immutable snapshot + route IDs | never returns `LOW` without approved model evidence |
| `enforce_hard_constraints_without_ranking` | Remove unusable routes | candidates + IDs -> usable/unusable | does not fabricate recommendation labels |

### Decisions/trade-offs

- Decision: numeric model and route thresholds remain null until approved.
- Alternatives considered: invent placeholder thresholds or return optimistic defaults.
- Reason: a placeholder could create a false-negative safety claim.
- Consequence: readiness is degraded and route ranking/model inference remain unavailable.
- ADR: `docs/adr/006-risk-knowledge-contract-foundation.md`.

Technical debt is limited to later planned phases and two upstream TestClient
deprecation warnings. They do not affect production runtime behavior.

## 6. API, contract and event changes

| Producer | Method/path | Request schema | Response schema | Consumer | Compatibility |
| --- | --- | --- | --- | --- | --- |
| M06 | `POST /internal/v1/risk/assess` | `RiskAssessRequest` | `RiskAssessResponse` | M03/M07 | new v1 |
| M06 | `POST /internal/v1/knowledge/retrieve` | `KnowledgeRetrieveRequest` | `KnowledgeRetrieveResponse` | M03/M07 | new v1 |
| M06 | `POST /internal/v1/routes/evaluate` | `RouteEvaluateRequest` | `RouteEvaluateResponse` | M03/M07 | new v1 |
| M06 | `POST /internal/v1/evidence/package` | `EvidencePackageRequest` | `EvidencePackageResponse` contract; 503 in Phase 1 | M03/M07 | new v1, unavailable capability |
| M06 | `GET /internal/v1/models/current` | headers | `ModelStatusResponse` | operations/M07 | new v1 |
| M06 | `GET /internal/v1/knowledge/status` | headers | `KnowledgeStatusResponse` | operations/M07 | new v1 |

- Generated client: not generated; downstream approval is pending.
- Contract lint: OpenAPI valid; Redocly reports four advisory warnings (license metadata and no artificial 4xx response on public health/metrics operations).
- Breaking change: none; these are new version-1 surfaces.
- Sanitized examples: `services/risk-knowledge/tests/fixtures/usgs_route_context.json` and producer tests.

## 7. Database, cache and storage changes

### Migrations

| Revision | Schema/table/index | Upgrade | Downgrade/forward fix | Data impact |
| --- | --- | --- | --- | --- |
| `20260919_0001` | `knowledge.model_versions`, `risk_assessments`, `documents`, `chunks`, `collection_versions`, `route_evaluations` plus indexes/constraints | creates six service tables | drops six tables; retains Alembic table/schema | new schema objects only |

- Empty DB -> head: 7 tables including `alembic_version`, revision `20260919_0001`.
- Previous main -> head: bootstrap owns `knowledge`; migration succeeds as `risk_knowledge`.
- Upgrade -> downgrade base -> upgrade: passed as the least-privilege module role.
- Restart persistence: smoke records remained after service restart; final smoke persisted risk/route records.
- Backup/restore: not executed in Phase 1; required before destructive production rollback.
- Access control: module role owns `knowledge`; negative test to create `integration.forbidden_role_test` returned `permission denied for schema integration`.

For an existing PostgreSQL volume, init scripts do not rerun automatically.
Apply the idempotent role bootstrap explicitly before Alembic:

```bash
docker compose exec postgres bash /docker-entrypoint-initdb.d/01-risk-knowledge-role.sh
docker compose run --rm risk-knowledge alembic upgrade head
```

### Redis/Qdrant/artifact changes

- Qdrant prefix `sta-knowledge-*`; active alias `sta-knowledge-active`.
- `prepare` is DRAFT-only; alias activation requires approved checksums, approver, and timestamp.
- Artifact volume is read-only; active model verification fails closed.
- No active model or collection is shipped. Rollback selects a previous approved record/alias; it never deletes the old collection automatically.

## 8. External providers and real data

| Provider/source | Endpoint/capability | Coverage | Credential ref | Freshness/TTL | License/attribution | Last canary |
| --- | --- | --- | --- | --- | --- | --- |
| USGS | Earthquake event/feed fixture | deterministic contract boundary only | none | captured `2026-09-19T09:21:51Z`; not runtime current data | USGS-authored public-domain data; URL in fixture | 2026-09-19 fixture capture |

- Runtime/demo has no mock or hard-coded current data: [x]
- Fixture: event `us7000tiib`, public URL/feed, redaction note, capture time, license, and canonical record SHA-256 embedded in the file.
- Unsupported capabilities return `NO_APPROVED_ACTIVE_MODEL`, `NO_ACTIVE_KNOWLEDGE_COLLECTION`, or `NO_RELIABLE_KNOWLEDGE_EVIDENCE`.
- Live provider drift/quota/failover is Phase 2/5 work; no runtime downloader accepts user URLs.

## 9. Configuration and Docker

### Environment variables added/changed

| Variable/group | Required | Secret | Default/example | Used by | Failure if missing |
| --- | --- | --- | --- | --- | --- |
| `INTERNAL_SERVICE_TOKEN` | yes when running M06 | yes | blank | shared internal auth | M06 readiness 503; protected endpoints 503 |
| `RISK_KNOWLEDGE_DB_USER/PASSWORD` | yes only when running M06 | password yes | `risk_knowledge` / blank | role bootstrap/service | shared PostgreSQL skips M06 role; M06 DB readiness 503 |
| `RISK_KNOWLEDGE_DATABASE_URL` or `POSTGRES_*` | yes | password/URL yes | host `postgres` | SQLAlchemy/Alembic | DB unavailable/readiness 503 |
| `QDRANT_URL`, `QDRANT_API_KEY` | URL yes; key optional | key yes | `http://qdrant:6333` | collection lifecycle | knowledge unavailable |
| `RISK_KNOWLEDGE_ARTIFACT_*` | key path required for active signed model | public key no | signature required | artifact verifier | model unavailable |
| `RISK_KNOWLEDGE_QDRANT_*` | no | no | documented in `.env.example` | collection naming/vector size | defaults used |
| `RISK_KNOWLEDGE_*_TIMEOUT_SECONDS` | no | no | dependency 2s, artifact 15s | readiness/warmup | validated settings defaults |
| `OTEL_*` | exporter optional | endpoint may be sensitive | service `risk-knowledge` | tracing | local spans only/no exporter |

### Run commands

```bash
docker build --build-context contracts=packages/contracts --target test -t sta-risk-knowledge:test services/risk-knowledge
docker run --rm sta-risk-knowledge:test ruff check app migrations tests
docker run --rm sta-risk-knowledge:test ruff format --check app migrations tests
docker run --rm sta-risk-knowledge:test mypy app
docker run --rm sta-risk-knowledge:test pytest --cov=app --cov-report=term

docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
docker compose exec postgres bash /docker-entrypoint-initdb.d/01-risk-knowledge-role.sh
docker compose run --rm risk-knowledge alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml --profile app up -d risk-knowledge
```

- Container user: `app` (UID/GID 10001), read-only root, all capabilities dropped, no-new-privileges.
- Port: internal 8004; volumes: read-only model artifacts; PostgreSQL/Qdrant named volumes.
- Readiness: `200 ready/degraded` when critical DB/auth work; `503 not_ready` when critical dependency/config is unavailable. Liveness checks process only.
- Limits: 2 CPUs and 2 GiB RAM; load/peak memory not measured in Phase 1.
- Image: 336,800,932 bytes, image ID `sha256:f4f488e...`.

## 10. Tests and verification

| Test type | Command | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Format/lint | `docker run --rm sta-risk-knowledge:test ruff check ...` and `ruff format --check ...` | 43 files formatted; lint pass | 0 | 0 | post-rebase run |
| Type | `docker run --rm sta-risk-knowledge:test mypy app` | 30 source files | 0 | 0 | strict mode |
| Unit + contract | `docker run --rm sta-risk-knowledge:test pytest --cov=app --cov-report=term` | 41 | 0 | 0 | 90.77% branch-aware coverage; threshold 80%; 2 upstream deprecation warnings |
| Shared contracts | `npm run check --prefix packages/contracts` | 31 schemas and 6 examples; OpenAPI lint and TypeScript typecheck pass | 0 | 0 | run after rebasing onto M02/M04 main |
| Repository CI compatibility | Python 3.11 `py_compile` over `git ls-files '*.py'` | 118 tracked files | 0 | 0 | matches temporary shared workflow interpreter |
| OpenAPI | `npx --yes @redocly/cli@1.34.5 lint ...` | valid | 0 | 0 | four advisory warnings documented above |
| Integration | real PostgreSQL/Qdrant containers; migration up/down/up; HTTP/DB smoke | pass | 0 | 0 | revision/ownership/persistence verified |
| Security/privacy | network-disabled Gitleaks branch scan; containerized `pip-audit`; prior Docker Scout evidence | source and Python dependencies pass | 1 previously recorded upstream-unfixed high | 0 | see Section 12 |
| E2E | full model/RAG/routes evidence chain | 0 | 0 | N/A | Phases 2–8 out of scope |
| Accessibility/visual | N/A | 0 | 0 | N/A | no UI change |
| Load/performance | N/A | 0 | 0 | N/A | scheduled for Phase 8 |

### Scenarios verified

- Success/degraded: readiness 200 degraded; risk 200 `UNKNOWN/DEGRADED`; route 200 usable hard-constraint fallback; knowledge 200 empty/unavailable.
- Invalid/unauthorized: standard 422 contract errors and 401 `AUTHENTICATION_REQUIRED`.
- Route selection: both risk and route endpoints reject duplicate IDs and IDs absent from the supplied immutable snapshot with 422.
- HTTP routing: both FastAPI-raised 403 and Starlette router 404 use the standard versioned error envelope.
- DB outage: liveness 200; readiness 503 `not_ready`, DB unavailable, 2.027 seconds.
- Shared Compose: validates without `RISK_KNOWLEDGE_DB_PASSWORD`; PostgreSQL init exits 0 after explicitly skipping only the M06 role.
- Missing artifacts: explicit unavailable status; no fake model/RAG success.
- Rollback: migration down/up and Qdrant alias design verified; no active production artifact exists.
- Sanitized IDs: request `50000000-0000-4000-8000-000000000001`, correlation `...0002`, trace `0123456789abcdef0123456789abcdef`.

## 11. UI evidence (if applicable)

Not applicable. Phase 0/1 changes no UI-owned path or screen.

## 12. Safety, security and privacy review

- [x] official warning/closure priority preserved
- [x] provider/RAG data is modeled as evidence and no user URL is ingested
- [x] no secret/PII/exact personal location in module code/log/fixture
- [x] service-to-service auth and schema ownership enforced
- [x] timeout/cancellation bounded for readiness and registry I/O
- [x] source/freshness/quality/version retained in contracts
- [x] fallback/degraded behavior does not invent data
- [ ] dependency/image/secret scans passed without exception

Findings:

- Gitleaks `origin/main..HEAD`: 12 post-rebase commits / approximately 417 KB scanned read-only with the container network disabled; no leaks found.
- Containerized `pip-audit`: no known dependency vulnerabilities; the local project itself is correctly skipped because it is not a PyPI package.
- Docker Scout actionable gate (`--only-fixed`, critical/high): last completed scan had 0 findings.
- Docker Scout full critical/high scan: last completed scan had 0 critical, **1 high** — `CVE-2026-85091` in Debian 13 `zlib 1:1.3.dfsg+really1.3.1-1`; Scout reported `Fixed version: not fixed`. Team Lead temporarily accepted the risk in PR #12 review at `2026-09-19T19:20:11Z`, conditioned on an internal-only service with no direct external-input exposure and a complete image re-scan at least weekly and on every base-image/lockfile change. Module 06 owns the re-scan, with Platform/Security oversight. Revisit immediately when a fixed package/base image appears, service exposure changes, or a scan reports another critical/high finding. This is not a VEX statement and does not claim the package is fixed; the authoritative record is ADR-006.
- SPDX 2.3 SBOM generation passed: 180 packages, 854,495 bytes; generated artifact SHA-256 `bea0c0dd9e1668ed506ed3f82e0c8cb253f5ab463bc5421db10c843998b8b926` (CI should retain the artifact rather than commit generated output).

## 13. Problems encountered and resolutions

| Problem | Root cause | Evidence | Resolution/workaround | Remaining risk |
| --- | --- | --- | --- | --- |
| Alembic URL contained masked password | SQLAlchemy URL string default hides passwords | connection attempted with `***` | explicit non-logging render for Alembic only | none observed |
| Module role migration initially failed | `CREATE SCHEMA IF NOT EXISTS` still requires DB-level CREATE | PostgreSQL `InsufficientPrivilegeError` | admin bootstrap owns schema; Alembic manages only owned objects | existing volumes require explicit bootstrap command |
| Readiness blocked 42 seconds during paused DB | driver cancellation waited for stalled server | structured readiness log | hard timeout plus skip optional DB probes after critical DB failure | cancelled driver task drains after dependency returns |
| Initial image had 5 critical/52 high | old Debian/Python and runtime dependencies | Docker Scout | Python 3.12.14/Debian 13 and patched dependency lock | one upstream-unfixed zlib high remains |
| Test commands were not reproducible in runtime image | production image correctly omitted dev dependencies/contracts | executable-not-found and contract path failures | separate self-contained Docker `test` target with named contract context | test image is intentionally larger than runtime |
| Temporary shared CI rejected valid Python 3.12 generic syntax | repository workflow compiles every tracked Python file with Python 3.11 | Actions run #29 failed on pre-rebase commit `f6649ab`; local 3.11 compile reproduced the syntax incompatibility | retained the Python 3.12 runtime while expressing the helper with `TypeVar`; all 118 tracked Python files compile on 3.11 | shared workflow still needs Team Lead alignment with the authoritative Python 3.12 standard |
| Shared Compose required an M06-only DB secret | interpolation happened even when another member did not start M06 | Compose review and config reproduction without the variable | optional interpolation plus an explicit no-secret role-bootstrap skip; M06 itself remains not-ready without credentials | existing volumes still need explicit role bootstrap before M06 migration |
| Per-service auth token diverged from team contract | initial M06 name introduced an unnecessary second credential | review against `.env.example` and M04 shared-token convention | M06 now reads only `INTERNAL_SERVICE_TOKEN` | shared secret rotation remains a platform concern |
| Router 404 escaped the standard error envelope | Starlette raises its own HTTP exception for unmatched routes | regression test against an unknown route | register both FastAPI and Starlette HTTP exception classes | none observed |
| Route evaluation accepted IDs outside the supplied snapshot | runtime model enforced only shape, while subset validation existed only on risk assessment | regression tests for unknown and duplicate IDs on both endpoints | shared runtime validator enforces uniqueness and snapshot membership before persistence | none observed |

## 14. Performance and operational behavior

| Metric | Target | Actual | Test condition | Pass |
| --- | --- | --- | --- | --- |
| Healthy readiness | no formal Phase 1 target | 38 ms observed | local Docker, DB/Qdrant reachable, no active artifacts | informational |
| DB-outage readiness | bounded by dependency timeout | 2.027 s | PostgreSQL container paused | yes |
| Risk fallback | no formal Phase 1 target | about 8 ms observed | local Docker + one route + persistence | informational |

- Metrics: request count/latency, dependency status, degraded-result counters.
- Logs: JSON application request logs include service, environment, route, status, duration, request/correlation/trace IDs, and stable error code; no bearer value/body is logged.
- OTLP exporter is optional; no dashboard/alert provisioning is owned by this slice.
- Disable/rollback: stop the service or leave model/collection unapproved; fallback remains explicit.

## 15. Known limitations and technical debt

| Limitation/debt | User/safety impact | Workaround | Owner | Priority | Follow-up |
| --- | --- | --- | --- | --- | --- |
| No trained active model | no numeric/local learned risk | `UNKNOWN` or official-rule `HIGH` | M06 | high | Phase 2–4 |
| No approved indexed documents | no guidance passages | explicit empty evidence/unavailable | M06 + Team Lead | high | Phase 5 |
| Route coefficients unapproved | no safer-route ranking | enforce hard constraints only | M05/M06/M07 | high | Phase 6 approval |
| Evidence package unavailable | consumers call sub-capabilities or handle 503 | stable error envelope | M06 | high | Phase 7 |
| One temporarily accepted unfixed base CVE | exposure remains while no upstream fix exists | weekly and change-triggered full-image scan; internal-only/no direct external-input exposure; rebuild when fixed | M06 + Platform/Security | high | ADR-006; dependency bot/base rebuild |
| TestClient deprecation warnings | test-only future maintenance | migrate when FastAPI/Starlette finalizes `httpx2` path | M06 | low | later maintenance |
| `RouteCandidate.route_id` is a canonical `RecordId`, while `RiskAssessment.route_id`, request route IDs, and knowledge persistence remain UUID | Phase 2 assessment/route APIs cannot consume provider-derived route IDs end to end yet | this compatibility slice aligns snapshot ingestion only; do not change assessment/persistence identity without an owner-approved contract decision | Contract owner + M03/M06/M07 | high | contract decision before Phase 2 |
| Quality-gate outcome exists only in `quality_summary.notes` | consumers would need to parse free text | retain the merged representation and do not invent a field until affected owners approve one | Contract owner + M03/M07 | high | Issue #63 |

## 16. Handoff to other members

| Recipient/module | What is ready | What they must change/do | Contract/config | Blocking? |
| --- | --- | --- | --- | --- |
| M02 API | incompatibility evidence from real M04 payload | settle `source_id` type and `score_version`/`formula_version` name | canonical provenance/quality schema | blocks merge |
| M03 agent | stable v1 request/response and degraded semantics | review evidence/status consumption | OpenAPI + JSON Schema 1.0.0 | approval blocks merge |
| M05 integration | merged canonical snapshot, provider inputs, feature/null policy, lineage/version fields, and compatibility fixture | review this M06 consumer-alignment PR and keep the canonical example stable | `IntegratedTravelContext` 1.0.0 plus feature schema 1.0.0 | snapshot ingestion ready after this PR; Issue #63 remains |
| M07 decision | risk/route/evidence inputs and hard constraints | approve acceptance targets/route policy | governance 1.0.0 | approval blocks model/ranking |
| Team Lead | source workflow and numeric gates | record approvals or requested versioned changes | governance/source workflow | blocks later phases |
| Platform/Security | role bootstrap, Compose, image evidence | oversee ADR-006 CVE conditions and re-scan results | env/Compose/migration/SBOM | blocks release if conditions fail |

## 17. Commit and PR inventory

```text
c0218be feat(contracts): define risk evidence route contract
1f8cdfb feat(risk): add service registry foundation
9a5d60e build(risk): add self-contained test image
39715ad docs(risk): add phase one handoff evidence
8079541 fix(risk): support repository CI Python version
e28bcf9 docs(risk): refresh post-rebase verification
3cb5edb fix(risk): address phase one review findings
f4b2074 docs(risk): record review fix evidence
da10df1 fix(risk): validate selected snapshot routes
5165fd1 docs(risk): record route validation evidence
```

- PR review findings addressed locally: commit authors remain `Nonyeol`; shared Compose secret coupling is removed; shared internal token is adopted; HTTP 404 envelope and selected-route validation fail closed; Issues #43/#44 now preserve nullable official-alert evidence and `UNKNOWN` behavior.
- Required checks: Docker lint/format/mypy pass; 41 tests pass with 90.77% coverage; 31 shared schemas and 6 examples validate; branch secret scan and Python dependency audit pass. The upstream-unfixed image finding is temporarily accepted under the controls and review triggers recorded in ADR-006.
- Rebased on main SHA: `9007d524f1f85d999c7729b95f9969456fef5454`; Compose conflict resolution retains merged M01 web, M02 API, M04 external-data, and M06 risk-knowledge/MLflow services. Shared contract and Compose validation pass against the rebased tree.
- Proposed squash title: `feat(risk): establish risk evidence contracts and service foundation`.

## 18. Rollback and recovery

1. Stop `risk-knowledge`; consumers must retain explicit dependency-unavailable behavior.
2. Deploy the previous approved image digest; no model/collection is bundled with code.
3. Keep the additive schema by default. Only after backup and confirming no dependent data, run `alembic downgrade base` as `risk_knowledge`.
4. Move Qdrant alias to a previous approved collection and mark registry stages consistently; current Phase 1 ships no active alias.
5. Do not delete PostgreSQL/Qdrant volumes. Retain assessment records and registry audit metadata.
6. Verify liveness, readiness/error semantics, migration revision, alias/registry agreement, and structured logs.

## 19. Final declaration

- [x] Phase 0/1 implementation work in requested scope is represented with evidence.
- [x] Required work outside Phase 0/1 is explicitly listed, not hidden.
- [x] documentation/env/contracts/migrations are updated.
- [ ] downstream owner approvals are recorded.
- [x] PR #12 merged after required review; the unfixed-CVE temporary disposition and operating conditions are recorded in ADR-006.
- [ ] ready to release — Phases 2–8 and real approved artifacts are not implemented.

Prepared by: Codex on branch `contract/06-risk-evidence-route-schema`

Reviewer: pending

Date: 2026-09-19

## 20. Post-merge M05 snapshot consumer alignment

Branch `fix/06-canonical-snapshot-consumer` starts from `origin/main`
`0e8845a05707a02b847be296f9ac8c60a7ad73ac`. It aligns only the M06
`IntegratedTravelContext` consumer projection with the merged canonical M05
snapshot: stable route/source `RecordId` values, nullable unevaluated exposure
bound to `UNKNOWN`, `DataQuality.score_version`, structured quality conflicts,
and nullable source attribution. The complete sanitized M05 Bangkok-route
snapshot now validates unchanged through both the M06 JSON Schema and Pydantic
consumer model.

Verification for this follow-up:

- Docker Ruff lint: pass; format check: 43 files already formatted.
- Docker strict mypy: no issues in 30 source files.
- Docker pytest: 49 passed, 0 failed, 0 skipped; 91.04% coverage.
- Shared contract suite: 92 passed; 31 schemas compile and 7 examples validate.
- Generated public and integration-input models reproduce byte-for-byte.
- Compose app-profile configuration validates with process-only placeholders;
  no local `.env` file was created.
- Diff Gitleaks: no leaks in approximately 32 KB; `pip-audit`: no known Python
  dependency vulnerabilities.

Still unresolved and deliberately unchanged: Issue #63 has no approved
quality-gate representation, and `RiskAssessment.route_id`, endpoint route ID
parameters, and knowledge persistence remain UUID while canonical
`RouteCandidate.route_id` is a `RecordId`. Phase 2 must not start until affected
owners record that identity decision and a fresh readiness check passes.
