# Risk and Knowledge service

Module 06 owns route-level risk evidence, approved emergency knowledge, route
hard constraints/ranking, the PostgreSQL `knowledge` schema, and Qdrant
collection lifecycle.

This branch implements Phase 0 and Phase 1 only. It intentionally does not
ship a trained model, indexed authority documents, dense/BM25 retrieval, or
the approved numeric route exposure formula. Until later phases provide those
artifacts, runtime returns explicit degraded states:

- official closure, evacuation, or extreme official warning -> deterministic
  `HIGH` override;
- otherwise missing model evidence -> `UNKNOWN/PARTIAL`, never `LOW`;
- no approved active knowledge collection -> no passages plus
  `NO_RELIABLE_KNOWLEDGE_EVIDENCE`;
- route fallback removes hard-closed candidates but does not label another
  candidate as recommended.

## API

Internal endpoints require `Authorization: Bearer ...`, `X-Request-ID`,
`X-Correlation-ID`, `traceparent`, and `X-Contract-Version: 1`.

| Method/path | Phase 1 behavior |
| --- | --- |
| `GET /health/live` | Process-only liveness |
| `GET /health/ready` | DB/auth critical readiness plus model/Qdrant degraded details |
| `GET /metrics` | Prometheus metrics |
| `POST /internal/v1/risk/assess` | Persisted deterministic conservative fallback |
| `POST /internal/v1/knowledge/retrieve` | Empty evidence with explicit unavailable limitation |
| `POST /internal/v1/routes/evaluate` | Persisted hard-constraint-only fallback |
| `POST /internal/v1/evidence/package` | Explicit 503 until snapshot retrieval is implemented in Phase 7 |
| `GET /internal/v1/models/current` | Verified active artifact metadata or unavailable reason |
| `GET /internal/v1/knowledge/status` | Approved DB/Qdrant alias agreement or unavailable reason |

Source contract: `packages/contracts/openapi/internal-risk-knowledge.yaml`.

## Run

The platform bootstrap in `infra/postgres/init` creates the `knowledge`
schema and transfers ownership to the module role before Alembic runs.
Alembic intentionally does not require database-wide `CREATE` permission.

```powershell
Copy-Item .env.example .env
# Set POSTGRES_PASSWORD, RISK_KNOWLEDGE_DB_PASSWORD,
# KEYCLOAK_ADMIN_PASSWORD, and the shared INTERNAL_SERVICE_TOKEN.
docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
# Required once for existing postgres-data volumes; do not delete the volume.
docker compose exec postgres bash /docker-entrypoint-initdb.d/01-risk-knowledge-role.sh
docker compose -f compose.yaml -f compose.dev.yaml run --rm risk-knowledge alembic upgrade head
docker compose -f compose.yaml -f compose.dev.yaml --profile app up -d risk-knowledge
curl.exe -fsS http://localhost:8004/health/live
curl.exe -i http://localhost:8004/health/ready
```

Readiness is `200 degraded` when PostgreSQL migrations and internal auth are
ready but the optional model/knowledge capabilities are unavailable. It is
`503 not_ready` when PostgreSQL or the service credential is unavailable.

## Verify

```bash
docker build --build-context contracts=packages/contracts --target test -t sta-risk-knowledge:test services/risk-knowledge
docker run --rm sta-risk-knowledge:test ruff check app migrations tests
docker run --rm sta-risk-knowledge:test ruff format --check app migrations tests
docker run --rm sta-risk-knowledge:test mypy app
docker run --rm sta-risk-knowledge:test pytest --cov=app --cov-report=term
docker compose build risk-knowledge
docker compose run --rm risk-knowledge alembic upgrade head
docker compose run --rm risk-knowledge alembic downgrade base
docker compose run --rm risk-knowledge alembic upgrade head
docker compose run --rm risk-knowledge risk-knowledge-verify-model
```

The final command exits `2` with `NO_APPROVED_ACTIVE_MODEL` until a signed,
approved `ACTIVE` model exists. That failure is the expected honest state for
Phase 1.

## Artifact and collection controls

An active model loads only when registry stage, approver/timestamp, feature
schema, SHA-256 checksum, artifact path containment, Ed25519 signature, and
configured public key all pass. The container mounts the artifact volume
read-only.

Prepare Qdrant collections without changing the active alias:

```bash
docker compose run --rm risk-knowledge risk-knowledge-qdrant prepare --version 1.0.0
```

Activation requires a matching PostgreSQL record in `APPROVED` stage with
manifest/evaluation checksums and approver metadata. MLflow is local training
infrastructure only:

```bash
docker compose -f compose.yaml -f compose.dev.yaml --profile training up -d mlflow
```

No runtime endpoint downloads models or knowledge documents from user-supplied
URLs.
