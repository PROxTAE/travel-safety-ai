# Module 08: Recommendation and Feedback Delivery Layer

## Overview
The `recommendation` service is responsible for:
1. **Deterministic Final Recommendation Construction**: Assembles the complete customer-facing recommendation response from validated upstream decision outputs (`07_DECISION_ENGINE`), route candidates (`05_ROUTING`), multi-source hazard/weather data (`03_EXTERNAL_DATA`, `04_DATA_INTEGRATION`), and verified emergency contacts (`08_DIRECTORY`).
2. **Immutable Persistence**: Stores delivered recommendations immutably in PostgreSQL (`recommendation.recommendations`) for audit, explanation provenance, and compliance.
3. **Verified Emergency Directory**: Maintains an official, provenance-verified emergency contacts directory (`emergency-directory/sources.yaml`) with strict validation against hallucinated or crowd-sourced contacts. Missing country coverage returns explicit limitations.
4. **Governed Feedback Loop & Safety Review**: Collects user feedback separated from system telemetry, automatically routing critical safety categories (`UNSAFE`, `INCORRECT`, `ROUTE_ISSUE`) into an auditable operator review queue (`recommendation.safety_review_queue`). Zero live online retraining.
5. **Live Alert Subscriptions & Meaningful Change Evaluation**: Evaluates hazard reassessments against active subscriptions with rate limiting / cooldowns, with strict bypass rule: **Escalation to higher severity is NEVER suppressed by cooldown**.

---

## Architectural Boundaries & Principles
- **Decision Integrity**: Enforces `validation.locked_action == True` from Module 07. Any mismatch or tampered payload is rejected immediately (`422 Unprocessable Content`).
- **Zero Mock / Zero Fake Data**: Runtime responses strictly derive from real database records, verified directories, and verified upstream inputs. If coverage is missing, structured `limitations` are attached.
- **Privacy & Redaction**: All feedback text is stripped of PII (phone numbers, emails, coordinate tuples) before storage and export.
- **Offline ML Governance**: Export CLI generates pseudonymized offline datasets for model benchmarking and safety auditing; no direct weight updates occur online.

---

## Internal API Endpoints (`/internal/v1`)
| Method | Path | Description |
|---|---|---|
| `POST` | `/internal/v1/recommendations/compose` | Compose, validate, and immutably persist recommendation |
| `GET` | `/internal/v1/recommendations/{id}` | Fetch stored recommendation response |
| `GET` | `/internal/v1/emergency-contacts` | Query verified official emergency directory |
| `POST` | `/internal/v1/feedback` | Submit governed user feedback |
| `GET` | `/internal/v1/feedback/safety-review` | List safety review queue items |
| `PATCH` | `/internal/v1/feedback/safety-review/{id}` | Transition review status (`TRIAGED`, `IN_REVIEW`, `RESOLVED`, `DISMISSED`) |
| `POST` | `/internal/v1/subscriptions` | Create active alert subscription |
| `DELETE` | `/internal/v1/subscriptions/{id}` | Cancel alert subscription |
| `POST` | `/internal/v1/alerts/evaluate` | Evaluate meaningful change and trigger notifications |

---

## Health, Readiness & Observability
- `GET /health/live`: Liveness check (200 OK)
- `GET /health/ready`: Readiness probe verifying PostgreSQL and Redis connections
- `GET /metrics`: Prometheus metrics including `recommendation_requests_total`, `safety_review_queue_size`, `alert_evaluations_total`, `alert_deliveries_total`

---

## CLI Tools
- **Verify Emergency Directory**:
  ```bash
  uv run recommendation-verify-directory --path emergency-directory/sources.yaml --sync-db
  ```
- **Export Governed Feedback**:
  ```bash
  uv run recommendation-export-feedback --output feedback_export.json --status RESOLVED
  ```
- **Run Data Retention Cleanup**:
  ```bash
  uv run recommendation-cleanup-retention --days 90
  ```

---

## Running Tests & Checks
```bash
# Run pytest test suite
uv run python -m pytest -v

# Run Ruff linter & formatter
uv run ruff check .
uv run ruff format --check .

# Run Mypy strict type checker
uv run mypy app
```
