# [M06] Establish risk evidence contracts and service foundation

## Summary

Implements Module 06 Phase 0 and Phase 1 only: versioned risk/knowledge/route
contracts and governance gates, plus a persistent FastAPI/PostgreSQL/Qdrant
service foundation with explicit degraded behavior. No trained model, indexed
knowledge corpus, numeric ranking policy, or fake current data is shipped.

This update rebases Phase 0–1 onto `origin/main` at `9007d52`, preserves the
M01 web, M02 API, M04 external-data, and M06 risk-knowledge/MLflow Compose
services, and applies the approved null-policy decisions from Issues #43 and
#44. Official-alert booleans are nullable, missing evidence remains `UNKNOWN`,
and `corridor_official_evacuation_active` is temporarily non-critical until M04
has real provider coverage.

This PR must remain draft until consumer/governance approvals and the documented
upstream-unfixed `zlib` CVE disposition are recorded.

## Scope

In scope:

- OpenAPI 3.1 and Draft 2020-12 contracts for risk, knowledge, route, evidence, and status.
- Feature/model/source/route governance documents that fail closed while approvals are pending.
- FastAPI internal auth, error envelope, correlation/trace propagation, health/readiness, Prometheus, OTLP, and JSON logs.
- Module-owned PostgreSQL migration and least-privilege role bootstrap.
- Qdrant DRAFT/APPROVED/ACTIVE alias lifecycle and signed model artifact verification.
- Conservative persisted fallbacks for unavailable model/RAG/ranking.
- Hardened production image and self-contained test image target.

Out of scope:

- Phases 2–8: historical dataset, trained model, monitoring, RAG ingestion/retrieval, numeric route exposure/ranking, combined evidence package, and full real E2E.
- UI changes.
- Consumer implementation changes in modules 03/05/07.

## Ownership and dependencies

- Module/owner: M06 Risk and Knowledge Services.
- Depends on: PostgreSQL/PostGIS, Qdrant, contract approval by modules 03/05/07, Team Lead approval of governance/source workflow.
- Downstream consumers: M03 agent and M07 decision engine; M05 produces immutable integrated snapshots/features.
- ADR: `docs/adr/006-risk-knowledge-contract-foundation.md`.

## Contract, database and configuration changes

- API/OpenAPI/JSON Schema: adds internal v1 risk, knowledge, route, evidence-package, and status contracts.
- Migration: `20260919_0001` creates six tables in `knowledge` with constraints/indexes; Alembic version table remains in the same schema.
- Role: `risk_knowledge` owns only `knowledge`; a verified negative test cannot create in `integration`.
- Environment: M06 uses the team-wide `INTERNAL_SERVICE_TOKEN`; module-specific database, Qdrant, artifact, timeout, and OTEL variables have no usable secret defaults.
- Shared Compose: PostgreSQL no longer requires the M06 database password when another module starts shared infrastructure; the M06 role bootstrap explicitly skips only that role when its secret is absent.
- Rollout: on an existing PostgreSQL volume, explicitly run the idempotent role bootstrap before Alembic because entrypoint init scripts run only for empty volumes.
- Compatibility: new contract version `1.0.0`; numeric governance values remain null and cannot activate unsafe capability.
- Feature null policy: official-alert booleans accept null without coercing it to false; closure/extreme remain critical, while evacuation is temporarily non-critical per Issues #43/#44.

## Real data and provenance

- Provider/source: USGS earthquake event/feed, deterministic test fixture only.
- Endpoint/coverage: event `us7000tiib`, contract boundary and official-alert fallback tests.
- License/attribution: USGS-authored public-domain data; source/feed URLs are embedded.
- Capture: `2026-09-19T09:21:51Z`; redaction note and canonical-record SHA-256 included.
- Failure/degraded behavior: no approved model/collection returns explicit unavailable/degraded state and never runtime mock content.
- Runtime/demo has no mock or hard-coded current data: [x]

## How to run

```bash
docker build --build-context contracts=packages/contracts --target test -t sta-risk-knowledge:test services/risk-knowledge
docker run --rm sta-risk-knowledge:test ruff check app migrations tests
docker run --rm sta-risk-knowledge:test ruff format --check app migrations tests
docker run --rm sta-risk-knowledge:test mypy app
docker run --rm sta-risk-knowledge:test pytest --cov=app --cov-report=term

cp .env.example .env
# Fill POSTGRES_PASSWORD, RISK_KNOWLEDGE_DB_PASSWORD,
# KEYCLOAK_ADMIN_PASSWORD, and the shared INTERNAL_SERVICE_TOKEN.
docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
docker compose exec postgres bash /docker-entrypoint-initdb.d/01-risk-knowledge-role.sh
docker compose run --rm risk-knowledge alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml --profile app up -d risk-knowledge
curl -i http://localhost:8004/health/live
curl -i http://localhost:8004/health/ready
```

## Verification evidence

Commands and results:

```text
docker run --rm sta-risk-knowledge:test ruff check app migrations tests
  All checks passed.

docker run --rm sta-risk-knowledge:test ruff format --check app migrations tests
  43 files already formatted.

docker run --rm sta-risk-knowledge:test mypy app
  Success: no issues found in 30 source files.

docker run --rm sta-risk-knowledge:test pytest --cov=app --cov-report=term
  41 passed, 0 failed, 0 skipped; total coverage 90.77% (gate 80%).
  2 upstream deprecation warnings; no test skips.

npm run check --prefix packages/contracts
  public OpenAPI lint passed; 31 JSON Schemas compiled; 6 examples validated; TypeScript typecheck passed.

$files = @(git ls-files '*.py')
docker run --rm -e PYTHONPYCACHEPREFIX=/tmp/pycache -v "H:/travel-safety-ai:/repo:ro" -w /repo python:3.11-slim python -m py_compile $files
  exit 0 for 118 tracked files; validates compatibility with the temporary repository CI interpreter.

npx --yes @redocly/cli@1.34.5 lint packages/contracts/openapi/internal-risk-knowledge.yaml
  Valid OpenAPI; 4 advisory warnings (license metadata and health/metrics 4xx rule).

docker compose -f compose.yaml -f compose.dev.yaml --profile core --profile app --profile training config --quiet
  exit 0 using a temporary placeholder-only `.env`; the file was removed immediately and was not committed.
  The merged model retains M01 web, M02 API, M04 external-data, M06 risk-knowledge, and MLflow.

docker run --rm --entrypoint bash -v "H:/travel-safety-ai/infra/postgres/init/01-risk-knowledge-role.sh:/tmp/role.sh:ro" sta-risk-knowledge:test /tmp/role.sh
  exit 0; `Skipping Module 06 role bootstrap: RISK_KNOWLEDGE_DB_PASSWORD is not set`.

alembic upgrade head -> downgrade base -> upgrade head (as risk_knowledge)
  pass; revision 20260919_0001; 7 knowledge tables including Alembic.

negative role test: CREATE TABLE integration.forbidden_role_test(...)
  rejected: permission denied for schema integration.

runtime smoke
  liveness 200; readiness 200 degraded;
  risk 200 UNKNOWN/DEGRADED; route 200 DEGRADED;
  knowledge 200 empty/UNAVAILABLE; unauthenticated request 401.

HTTP error regression
  FastAPI-raised 403 and Starlette router-level 404 both return the v1 error envelope.

Route selection regression
  `/risk/assess` and `/routes/evaluate` return 422 for duplicate route IDs and IDs absent from the supplied snapshot.

PostgreSQL paused
  liveness 200; readiness 503 not_ready/DATABASE_UNAVAILABLE in 2.027 s.

docker run --rm --network none -v "H:/travel-safety-ai:/repo:ro" ghcr.io/gitleaks/gitleaks:v8.24.3 git /repo --log-opts="origin/main..HEAD" --redact=100 --no-banner --verbose
  12 post-rebase commits and approximately 417 KB scanned with network disabled; no leaks found.

docker run --rm sta-risk-knowledge:test uv run --frozen --with pip-audit pip-audit
  no known dependency vulnerabilities.

docker scout cves --only-severity critical,high --only-fixed --exit-code local://sta-risk-knowledge:phase1
  Last completed scan: 0 critical/high actionable findings.

docker scout cves --only-severity critical,high --exit-code local://sta-risk-knowledge:phase1
  Last completed scan: 0 critical, 1 high: CVE-2026-85091 in Debian zlib; no fixed version.
```

- Runtime image: `sha256:f4f488e484659b7fa5cd8320a7d9f63a3b2789241e963cf78a9d5bcceab56c5d`, non-root `app`, read-only, 2 CPU, 2 GiB. A new external Scout metadata submission was not authorized; the previously recorded upstream-unfixed CVE disposition remains required.
- SBOM: SPDX 2.3 generated successfully, 180 packages; artifact SHA-256 `bea0c0dd9e1668ed506ed3f82e0c8cb253f5ab463bc5421db10c843998b8b926`.
- UI screenshots/video: N/A; no UI ownership or changes.
- Sanitized IDs: request `50000000-0000-4000-8000-000000000001`, correlation `...0002`, trace `0123456789abcdef0123456789abcdef`.

## Safety, security and privacy

- [x] Input validated at boundary
- [x] Timeout/cancellation handled for dependency and registry I/O
- [x] No secret, token, PII, or personal location leaked to logs/fixtures
- [x] Provenance, timestamps, quality, and version retained
- [x] Official warning/closure cannot be weakened by model/preference
- [x] Provider/RAG text is not accepted as instructions or fetched from user URLs
- [x] Consent/retention N/A for this internal Phase 1 service; no user profile is stored
- [x] Error messages expose no internal stack or secret

## Test coverage

- [x] success/degraded path
- [x] invalid/unauthorized path
- [x] dependency timeout/5xx
- [x] stale/conflicting/partial contract behavior
- [x] boundary and regression cases
- [x] producer contract tests
- [ ] full real E2E — N/A until Phases 2–8

## Risks and limitations

- Issues #43/#44 settle the official-alert null/criticality fields and are implemented here; the remaining contract/route/source approvals still require review.
- M05 generated integration models, provider-input records, immutable snapshot implementation, lineage/version implementation, and producer/consumer compatibility tests are not yet merged into `origin/main`; Phase 2 remains blocked.
- Full image scan has one upstream-unfixed high `zlib` CVE. Do not merge without a security disposition; no exception or VEX is asserted by this PR.
- No active model or knowledge collection is shipped. This is intentionally visible as degraded/unavailable.
- `/internal/v1/evidence/package` intentionally returns 503 until Phase 7.
- Route numeric ranking remains disabled until approved coefficients exist.

## Rollback

- Code: stop the service and deploy the previous approved digest; consumers retain dependency-unavailable handling.
- Database: keep additive tables by default. After backup and dependency review only, run `alembic downgrade base` as the module role.
- Model/knowledge: switch to a previous approved registry version/alias; no active artifact ships in this slice.
- Never delete PostgreSQL/Qdrant volumes as rollback.

## Handoff

- Completion report: `docs/handoffs/M06-risk-knowledge.md`.
- Next owners: modules 03/05/07 review v1 contracts; Team Lead approves acceptance/source workflow; Platform/Security reviews shared Compose/role changes and the unfixed CVE.
- Reviewer focus: null/quality/provenance semantics, official constraint precedence, schema ownership, alias activation atomicity, and unavailable/degraded responses.
