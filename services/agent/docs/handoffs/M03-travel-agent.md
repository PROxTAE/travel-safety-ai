# [M03] Travel AI Agent Completion Report

> **Path note:** this file lives at `services/agent/docs/handoffs/M03-travel-agent.md`. Every other
> module's handoff report lives at the repo root (`docs/handoffs/Mxx-*.md`,
> `docs/handoffs/README.md`'s own table) — this one is here instead because the work that produced
> it was scoped to `services/agent/` only. **Move or copy this file to `docs/handoffs/` at the repo
> root before opening the PR**, to match the convention every other module follows.

## 1. Metadata

| Field | Value |
| --- | --- |
| Module/owner | 03 — Travel AI Agent |
| Issue/PR | not yet opened |
| Branch | not yet created (work done directly on disk; see §17) |
| Base/final commit SHA | based on `main` @ `3ffa77c` ("[M03] Add pyproject, CI workflow and runtime settings (Phase 1 start) (#97)") |
| Date/time/timezone | 2026-09-22, Asia/Bangkok |
| Reviewers | none yet |
| Contract version | 1.0.0 |
| Docker image digest/tag | not built — no Docker daemon available in the environment this work was done in |
| Related model/policy/prompt/collection version | n/a (no LLM call has ever been made against a live model; no policy version exists yet in this module) |

## 2. Executive summary

- Phases 0–3 are genuinely complete and verified (tests, `ruff`, `mypy --strict` all pass under the
  pinned Python 3.12 / `uv` toolchain). Phase 4 is complete for the one piece that does not depend
  on an unpublished contract (the evidence retry/escalate loop). Phases 5–7 are **not** done, and
  large parts of them cannot be done from `services/agent/` alone — see §4 and §15.
- The agent is a real, running FastAPI service with a compiled 13-node LangGraph graph, a
  PostgreSQL checkpointer, a Redis progress publisher, deterministic + LLM-fallback intent
  classification, and two typed, contract-tested tool clients (data-integration,
  risk-knowledge). It correctly reaches `FAILED`, `NEEDS_INPUT`, or `CANCELLED` for every input
  tried — **it has never produced, and cannot produce, a fabricated `COMPLETED` recommendation**,
  because the nodes that would need to call `external_data`, `decision_engine` and
  `recommendation` raise `NodeNotImplementedError` instead of inventing a result.
- Connects to module 05 (data-integration) and module 06 (risk-knowledge) with real typed clients;
  cannot yet connect to module 04 (external-data), module 07 (decision-engine) or module 08
  (recommendation) because none of the three has published an OpenAPI contract under
  `packages/contracts/openapi/` yet — see §8.
- **Most important limitation:** the agent's main orchestration path (Phase 4's actual goal —
  "real full-stack run from normalized request to recommendation ID") cannot be completed and
  cannot be demonstrated, because it is blocked end-to-end on module 04's contract. Nothing in
  `services/agent/` can fix this; it needs module 04 (and, further down the same path, modules 07
  and 08) to publish contracts.
- **Not ready to merge as "Module 03 complete."** It is ready to merge as "Phase 0–3 complete,
  Phase 4 partial, Phases 5–7 blocked/not started," with that framing stated explicitly in the PR
  description — see §3 for the acceptance checklist against reality.

## 3. Original responsibility and acceptance criteria

From `03_TRAVEL_AI_AGENT_IMPLEMENTATION.md`, "Acceptance checklist":

- [x] graph finite และไม่มี autonomous generic tool — the graph is a DAG plus exactly one bounded
  back-edge (`validate_evidence -> build_evidence`, capped by `evidence_retry_count` vs.
  `EVIDENCE_RETRY_MAX`); the LLM never sees a generic HTTP/tool primitive, only
  `IntentClassifierClient.classify()` — true by construction (`app/intent/llm_classifier.py`,
  `app/tools/registry.py`).
- [x] every tool schema/timeout/retry/permission/budget กำหนดชัด — all 5 allowlisted MVP tools are
  declared in `app/tools/registry.py` with name/version, allowed intent/stage, timeouts, retryable
  codes, idempotency, and (for the two available) redact-nothing-sensitive-in-audit behavior. Only
  2 of 5 have a callable client (§8).
- [ ] independent work parallelize ได้แต่ results รวมก่อน decision — not implemented; no node
  calls two tools concurrently yet, because no node has two available tools to call concurrently.
  Owner: whoever does Phase 4's real `fetch_external_data`/`build_evidence` once module 04/06's
  full surface is usable.
- [x] missing critical data ถามผู้ใช้แทนการเดา — `check_required_fields` +
  `docs/intent-and-required-fields.md`; tested (`tests/test_nodes.py`,
  `tests/test_builder.py::TestLifecycle::test_unconfirmed_locations_stop_at_needs_input`).
- [ ] stale/current follow-up behavior ถูกต้อง — partial. `POST .../resume` re-validates ownership
  and re-enters the graph, but only understands the one missing-field rule Phase 1/2 implemented
  (`confirmed_by_user`); the TTL/freshness table in `docs/diagrams/agent-state.md` §7 is
  documented but not implemented anywhere. Owner: Phase 5.
- [x] checkpoint/resume และ cancellation ทำงาน — implemented (`app/checkpoints/postgres.py`,
  `app/api/internal.py`) and unit-tested; the Postgres-backed integration test
  (`tests/integration/test_checkpoint_postgres.py`) is written but **not run** — no Docker in this
  environment (§10).
- [x] agent ไม่ตัดสิน risk/action เองและไม่เปลี่ยน locked decision — true by construction: no node
  computes a `risk_level` or `action_code`; those fields only ever come from a Module 06/07
  response, and `make_decision`/`format_recommendation` are pass-through stubs that do not exist
  yet, so there is nothing in this codebase that could compute or alter one.
- [x] progress safe สำหรับ UI และ trace ได้ถึง evidence/version — `app/progress/events.py` forbids
  chain-of-thought/PII/coordinates/tokens by schema (`extra="forbid"` everywhere, tested
  adversarially in `tests/test_events.py`); `app/tools/clients/base.py`'s `ToolCallRecord` carries
  a request-body hash, never the body, for the audit trail.
- [~] max step/tool/token/cost/time enforced — step/tool-call/cost/deadline are enforced and
  property-tested (`tests/test_termination_property.py`). Token/LLM-call ceilings are **not**
  enforced (`app/budgets/__init__.py`'s own docstring explains why: `AgentState.control` has no
  LLM-call counter yet, and inventing one without Phase 2's real usage pattern established would
  be guessing).
- [ ] real E2E + degraded scenarios ผ่านใน Docker — not done. No Docker daemon in this
  environment; separately, a real E2E is not possible yet regardless of Docker because 3 of 5
  tools have no contract to call.

## 4. What was implemented

### Features

| Feature | Behavior now | Entry point | Status |
| --- | --- | --- | --- |
| Graph scaffold (Phase 1) | 13-node LangGraph `StateGraph`, budget/cancel guard on every node | `app/graph/builder.py` | Complete |
| Intent classification (Phase 2) | Deterministic keyword/structural rules; LLM structured-output fallback for ambiguous text | `app/intent/`, `app/graph/nodes/classify_intent.py` | Complete (LLM path never tested against a live model — no API key in this environment) |
| Emergency shortcut (Phase 2, plan Phase 0 step 3) | `EMERGENCY` intent skips straight past the whole evidence pipeline | `app/graph/nodes/emergency_shortcut.py` | Graph shape complete; the shortcut's own action (module 08's emergency contacts) is `NodeNotImplementedError` — no published contract |
| Typed tool clients (Phase 3) | `data_integration.create_snapshot@1`, `risk_knowledge.build_evidence_package@1` — real httpx clients, retried per contract, schema-validated | `app/tools/clients/` | Complete for these 2; the other 3 tools have no OpenAPI contract to generate a client from |
| Tool registry (Phase 3) | All 5 MVP tools declared (name/version/timeouts/retry/idempotency/allowed intent+stage) | `app/tools/registry.py` | Complete |
| Evidence retry/escalate loop (Phase 4) | `validate_evidence` counts insufficient-evidence attempts; routing bounds them against `EVIDENCE_RETRY_MAX` | `app/graph/nodes/validate_evidence.py`, `app/graph/routing.py` | Complete, but currently unreachable end-to-end (`build_evidence` never produces real quality data) |
| Run lifecycle API | `POST /internal/v1/runs`, `GET .../{id}`, `POST .../resume`, `POST .../cancel` | `app/api/internal.py` | Complete for Phase 1–4 scope; resume only handles the one missing-field rule that exists |
| PostgreSQL checkpointer + `agent.runs` | LangGraph `AsyncPostgresSaver` + hand-rolled `agent.runs`/`agent.tool_calls` migration | `app/checkpoints/postgres.py`, `migrations/001_agent_runs.sql` | Complete; integration-tested but not run (no Docker) |
| Redis progress publisher | Idempotent, ordered `run.*` SSE event publishing | `app/progress/publisher.py` | Complete; integration-tested but not run (no Docker) |
| Termination guarantee | Property test: `guard_node` bounds *any* node to `MAX_AGENT_STEPS`, adversarially | `tests/test_termination_property.py` | Complete |
| Real orchestration path (Phase 4's actual goal) | A run from normalized request to a real `recommendation_id` | — | **Not implemented — blocked**, see §8 |
| Degraded/escalation policy (Phase 5) | Error-policy-per-dependency table; conservative/escalation behavior | — | **Not implemented** |
| Freshness/TTL-based follow-up refresh (Phase 5) | Reuse fresh evidence vs. refetch stale evidence on a follow-up | — | **Not implemented** |
| Full observability (Phase 6) | Per-node tracing spans, deterministic replay, 40-scenario evaluation suite | — | **Not implemented** — only the termination property test and the base `/metrics` endpoint from Phase 1 exist |
| Real E2E / load test (Phase 7) | — | — | **Not attempted** — no Docker, no live dependent services |

### Important flows

The only flow that exists end-to-end today, for every kind of input tried:

```text
POST /internal/v1/runs
  -> validate_input (real: identity/request consistency)
  -> classify_intent (real: deterministic rules, LLM fallback)
       -> EMERGENCY? -> emergency_shortcut -> NodeNotImplementedError -> FAILED/INTERNAL_ERROR
       -> other intent -> check_required_fields (real)
            -> missing origin/destination confirmation -> NEEDS_INPUT (terminal, resumable)
            -> complete -> fetch_external_data -> NodeNotImplementedError -> FAILED/INTERNAL_ERROR
  -> (cancelled flag at any point) -> CANCELLED
  -> (deadline/step/tool-call/cost budget exceeded at any point) -> FAILED/DEPENDENCY_TIMEOUT
     or FAILED/AGENT_BUDGET_EXCEEDED
```

No path reaches `COMPLETED` or `PARTIAL` today. That is intentional, not a bug: reaching either
requires a real `recommendation_id`, which requires the three unpublished contracts.

### What is explicitly not implemented

- `fetch_external_data`, `integrate_data`, `build_evidence`, `degraded_or_escalate`,
  `make_decision`, `format_recommendation`, `emergency_shortcut`'s own action — each raises
  `NodeNotImplementedError` with a docstring naming exactly what contract it is waiting on.
- Parallel/concurrent tool calls (nothing to parallelize yet with only 2 of 5 tools callable).
- Per-dependency degraded policy (Phase 5).
- TTL-based freshness/refresh logic for follow-ups (Phase 5) — the TTL table exists only as
  documentation (`docs/diagrams/agent-state.md` §7), copied from `00_SHARED_PROJECT_CONTEXT.md`.
- Distributed tracing spans per node/tool call, deterministic replay, the 40-scenario golden
  evaluation suite, degraded-rate metrics (Phase 6).
- Any real E2E, restart-mid-run, concurrent-run/bulkhead, or load test (Phase 7) — all require
  Docker and, for the E2E specifically, real running dependencies this module cannot call yet.

## 5. Actual architecture and code design

### Folder/file map

| Path | Purpose | Important owner/consumer |
| --- | --- | --- |
| `app/graph/` | `StateGraph` builder, routing, state schema, 13 node modules | this module |
| `app/budgets/` | `guard_node` — the one place step/budget enforcement lives | this module |
| `app/intent/` | Deterministic rules, per-intent required fields, LLM classifier | this module |
| `app/tools/` | Registry + typed clients for the 2 available tools | this module; consumes module 05/06's OpenAPI |
| `app/checkpoints/` | PostgreSQL checkpointer, `agent.runs` repository, migrations | this module |
| `app/progress/` | SSE/Redis event schema and publisher | module 02 consumes the events |
| `app/api/internal.py` | `/internal/v1/runs*` — module 02 is the only intended caller | module 02 |
| `app/main.py`, `app/runtime.py` | FastAPI app, lifespan wiring, health/ready/metrics | operations |
| `migrations/001_agent_runs.sql` | `agent.runs`, `agent.tool_calls` tables | this module |
| `docs/diagrams/agent-state.md` | Graph/state/error/budget/follow-up specification | all consumers of this module's behavior |
| `docs/intent-and-required-fields.md` | Intent precedence, keyword lists, critical-field matrix | this module |
| `tests/` | Unit (`test_*.py`) + `tests/integration/` (Postgres/Redis via Testcontainers) | this module |

### Main components/classes/functions

| Symbol | Responsibility | Inputs/outputs | Design notes |
| --- | --- | --- | --- |
| `app.budgets.guard_node` | Wraps every node: increments `step_count`, checks stop conditions, catches `NodeNotImplementedError` | `NodeFn -> GuardedNodeFn` | Single place the "no unlimited loop" guarantee lives; property-tested |
| `app.graph.builder.build_graph` | Compiles the 13-node graph | `Settings, checkpointer -> CompiledStateGraph` | `GRAPH_VERSION`/`graph_checksum()` fingerprint the shape |
| `app.intent.rules.classify_deterministic` | Keyword/structural intent rules | `InputSection -> Intent \| None` | Injection-proof by construction — substring scan only, never interprets text |
| `app.intent.llm_classifier.OpenAIIntentClassifier` | Structured-output LLM fallback | `question, locale -> IntentClassification` | Fails closed if unconfigured; request shape respx-tested against a mocked `api.openai.com` |
| `app.tools.clients.base.ToolClientBase._post` | Shared HTTP call: headers, timeout, tenacity retry, schema validation, error mapping | `path, payload, response_model -> (Response, ToolCallRecord)` | Retries only the tool's own declared retryable codes |
| `app.graph.evidence.evidence_insufficient` | Shared predicate for `validate_evidence` and its routing | `QualitySection -> bool` | Kept in one place so the two can't drift |
| `app.checkpoints.postgres.RunsRepository` | `agent.runs` CRUD | — | Explicit column list, never `SELECT *` |

### Decisions/trade-offs

- **Decision:** Phase 3 tool schemas are hand-transcribed from the published OpenAPI/JSON Schema
  files, not generated. **Alternatives considered:** running the real codegen pipeline
  (`packages/contracts/scripts/generate-python.sh`). **Reason:** that pipeline writes to
  `packages/contracts/generated/python`, outside `services/agent/`, and this work was scoped to
  stay inside it. **Consequence:** `app/tools/schemas.py` documents itself as an interim
  transcription to be replaced by a real generated import once that becomes possible; deep-nested
  provider content (weather/transport/disaster record internals) is deliberately left opaque
  rather than duplicating a schema this module does not own. **ADR link:** none — see this
  report's §2 and the module docstring.
- **Decision:** `POST /internal/v1/runs` executes the graph synchronously within the HTTP request.
  **Alternatives considered:** a worker/queue returning 202 immediately. **Reason:** no
  worker/queue infrastructure exists yet in this repo for this module, and building one was out of
  scope for the phases attempted. **Consequence:** cancellation of an in-flight run is not
  meaningful yet (nothing is "in flight" outside the request lifetime); documented explicitly in
  `app/api/internal.py`'s module docstring. **ADR link:** none.
- **Decision:** `EMERGENCY` intent gets a dedicated graph node (`emergency_shortcut`) even though
  its own action cannot be implemented yet. **Alternatives considered:** deferring the shortcut
  entirely until module 08 publishes a contract. **Reason:** the plan requires the shortcut
  *routing* as a Phase 0 deliverable, independent of whether the destination action exists yet;
  building the shape now avoids a later re-wiring of `classify_intent`'s edges. **Consequence:**
  one more `NodeNotImplementedError` stub, clearly documented as to why. **ADR link:** none.

## 6. API, contract and event changes

| Producer | Method/path/event | Request schema | Response schema | Consumer | Compatibility |
| --- | --- | --- | --- | --- | --- |
| this module | `POST /internal/v1/runs` | `CreateRunRequest` | `RunRef` | module 02 | new |
| this module | `GET /internal/v1/runs/{id}` | — | ad-hoc dict (redacted `AgentState`) | module 02 | new |
| this module | `POST /internal/v1/runs/{id}/resume` | `ResumeRunRequest` | `RunRef` | module 02 | new |
| this module | `POST /internal/v1/runs/{id}/cancel` | `CancelRunRequest` | ad-hoc dict | module 02 | new |
| this module | `run.accepted`/`run.needs_input`/`run.completed`/`run.failed` (Redis Stream) | — | `AgentEvent` (`app/progress/events.py`) | module 02 (SSE relay) | new |
| module 05 | `POST /internal/v1/snapshots` | `SnapshotCreateRequest` (this module's transcription) | `SnapshotResponse` | this module (client only, not wired into a node yet) | consumed, not yet exercised in orchestration |
| module 06 | `POST /internal/v1/evidence/package` | `EvidencePackageRequest` | `EvidencePackageResponse` | this module (client only, not wired into a node yet) | consumed, not yet exercised in orchestration |

- Generated client command/result: none run — `packages/contracts/generated/python` was not
  touched (out of scope); `app/tools/schemas.py` is a manual, documented interim.
- Contract lint/breaking check result: not run (no CI execution in this environment; `ruff`/`mypy`
  were run manually, see §10).
- Deprecation/migration plan: n/a, nothing existed before this work for `services/agent`'s own
  internal API.
- Sanitized request/response example location: none captured — no live dependency was ever called;
  every response used in a test is a hand-built fixture in the test file itself
  (`tests/test_tool_clients.py`), never real provider data.

## 7. Database, cache and storage changes

### Migrations

| Revision | Schema/table/index | Upgrade | Downgrade/forward fix | Data impact |
| --- | --- | --- | --- | --- |
| `001_agent_runs.sql` | `agent.runs`, `agent.tool_calls`, `agent.schema_migrations` | `CREATE SCHEMA`/`CREATE TABLE IF NOT EXISTS`, tracked in `agent.schema_migrations` | No downgrade script — additive only, safe to leave in place | None (fresh tables) |

- Empty DB -> head result: **not verified** — no PostgreSQL available in this environment. The
  migration runner (`app/checkpoints/postgres.py::apply_migrations`) is unit-covered only for its
  logic shape; `tests/integration/test_checkpoint_postgres.py::test_migrations_apply_once_and_are_safe_to_repeat`
  is written to verify this against a real database but has never executed.
- Previous main -> head result: n/a, this is the first migration for this module.
- Restart persistence result: not verified (same reason).
- Backup/restore result: not attempted.
- Retention/cleanup behavior: none implemented — no TTL/cleanup job for `agent.runs` rows exists
  yet.
- Encryption/access control: relies on the shared `INTERNAL_SERVICE_TOKEN` and the database's own
  access control; nothing module-specific added.

### Redis/Qdrant/artifact changes

- Key names: `sta:{env}:run:{request_id}:events` (Stream), `sta:{env}:run:{request_id}:event_seq`
  (counter), `sta:{env}:idempotency:{request_id}:{key}` (dedupe) — `app/progress/publisher.py`.
- TTL: 3600s on every key this module creates (`_DEDUPE_TTL_SECONDS`, `_STREAM_TTL_SECONDS`).
- Ownership/cleanup/rollback: TTL-only cleanup (no explicit deletion path); no Qdrant or artifact
  store use in this module.

## 8. External providers and real data

| Provider/source | Endpoint/capability | Coverage | Credential ref | Freshness/TTL | License/attribution | Last canary |
| --- | --- | --- | --- | --- | --- | --- |
| module 05 (data-integration) | `POST /internal/v1/snapshots` | Client built, contract-tested with respx; never called against the real service | `INTERNAL_SERVICE_TOKEN` (shared) | n/a — this module does not set TTLs, module 05 does | n/a | never (no Docker) |
| module 06 (risk-knowledge) | `POST /internal/v1/evidence/package` | Same as above | Same | n/a | n/a | never (no Docker) |
| module 04 (external-data) | `POST /internal/v1/context/query` | **No client — no published OpenAPI contract** (`packages/contracts/openapi/` has none for this service) | — | — | — | — |
| module 07 (decision-engine) | `POST /internal/v1/decisions` | **No client — no published OpenAPI contract**, even though the service itself runs (its `Idempotency-Key` support was confirmed by reading `services/decision-engine/app/main.py` directly, not from a contract) | — | — | — | — |
| module 08 (recommendation) | `POST /internal/v1/recommendations`, `GET /internal/v1/emergency/contacts` | **No client — no published OpenAPI contract, and no Dockerfile exists for this service yet either** | — | — | — | — |

- ยืนยัน runtime/demo ไม่มี mock/hard-coded current data: **[x]** — `grep -rnE
  "(USE_MOCK|mockMode|fakeRecommendation|hardcodedWeather|sampleCurrentData)" app` returns nothing,
  verified as part of §10.
- Test fixture source/captured_at/redaction/license: every fixture in `tests/` is synthetic,
  built to satisfy a schema for testing marshaling — never captured from, or resembling, real
  provider output. No license/attribution applies.
- Unsupported/unavailable capability behavior: every node that would call an unavailable tool
  raises `NodeNotImplementedError`, mapped by `guard_node` to `FAILED`/`INTERNAL_ERROR` — never a
  silent skip or a fabricated fallback value.
- Schema drift/quota/failover behavior: not applicable yet — no live call has ever been made.

## 9. Configuration and Docker

### Environment variables added/changed

| Variable | Required | Secret | Default/example | Used by | Failure if missing |
| --- | --- | --- | --- | --- | --- |
| `DATABASE_URL` | No | No (connection string, no embedded secret expected) | unset | checkpointer, `agent.runs` | Service starts degraded; `/health/ready` reports `database: unavailable`; every run fails to persist |
| `REDIS_URL` | No | No | unset | progress publisher | Service starts; progress events are simply not published |
| `EXTERNAL_DATA_BASE_URL` | No | No | `http://external-data:8002` | (client not built yet) | n/a |
| `DATA_INTEGRATION_BASE_URL` | No | No | `http://data-integration:8003` | `DataIntegrationClient` | Client would fail to connect; not called by any node yet |
| `RISK_KNOWLEDGE_BASE_URL` | No | No | `http://risk-knowledge:8004` | `RiskKnowledgeClient` | Same |
| `DECISION_ENGINE_BASE_URL` | No | No | `http://decision-engine:8005` | (client not built yet) | n/a |
| `RECOMMENDATION_BASE_URL` | No | No | unset (port never observed) | (client not built yet) | n/a |
| `OPENAI_API_KEY` | No | **Yes** | unset | `OpenAIIntentClassifier` | LLM intent path silently unavailable; deterministic `ASK_INFORMATION` fallback used instead |
| `OPENAI_INTENT_MODEL` | No | No | `gpt-4o-mini` | same | n/a |
| `OPENAI_TIMEOUT_SECONDS` | No | No | `10.0` | same | n/a |

(All budget/timeout variables — `MAX_AGENT_STEPS`, `MAX_TOOL_CALLS`,
`AGENT_TOTAL_TIMEOUT_SECONDS`, etc. — were already documented in the Phase 1 handoff and are
unchanged; see `app/settings.py`.)

### Run commands

```bash
cd services/agent
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -m "not integration"            # this environment: 171 passed
uv run pytest                                  # + integration, needs Docker: never run here
```

- Container user: not verified — `Dockerfile` was written in Phase 1 and unchanged this round, but
  `docker build` has never been run in this environment (no Docker daemon).
- Ports/networks/volumes: agent listens on 8001 (the gap module 2 → 4's port numbering left open);
  no `agent:` entry exists yet in `compose.yaml`/`compose.dev.yaml` — out of scope (shared files).
- Health/readiness behavior: unchanged from Phase 1 (`/health/live`, `/health/ready`).
- CPU/RAM/disk measured: not measured — no running container.
- Image size/digest: not built.

## 10. Tests and verification

| Test type | Command | Passed | Failed | Skipped | Evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Lint | `uv run ruff check . && uv run ruff format --check .` | — | 0 | — | Clean |
| Type | `uv run mypy app` (strict) | — | 0 | — | "Success: no issues found in 46 source files" |
| Unit | `uv run pytest -m "not integration"` | 171 | 0 | 6 deselected (integration-marked) | 90% line coverage on `app/` |
| Contract | (subset of the above — `tests/test_tool_clients.py`, `tests/test_events.py`) | included above | 0 | — | respx-mocked HTTP, schema-adversarial event tests |
| Integration | `uv run pytest` (adds `tests/integration/`) | **not run** | — | — | No Docker daemon in this environment; tests are written (Postgres via Testcontainers, Redis via Testcontainers) but unverified |
| E2E | — | — | — | all | Not attempted; blocked on §8 |
| Security/privacy | manual: prompt-injection golden case (`tests/test_intent.py`), forbidden-field schema tests (`tests/test_events.py`), mock-switch grep | pass | 0 | — | See §12 |
| Load/performance | — | — | — | all | Not attempted |

### Scenarios verified

- Success: n/a — no path reaches `COMPLETED`/`PARTIAL` yet (see §4); "success" in this module's
  current scope means correctly reaching `NEEDS_INPUT` or the honest `FAILED` at the first
  unimplemented tool, both of which are tested.
- Invalid input/unauthorized: `test_create_run_rejects_an_unknown_field`,
  `TestOpenAIIntentClassifierConstruction` (fails closed on missing config),
  `test_401_is_not_retried` (tool client).
- Timeout/429/5xx: `test_timeout_is_retried_then_reported_as_dependency_timeout`,
  `test_rate_limited_is_retryable`, `test_dependency_unavailable_is_retried_up_to_max_attempts`
  (`tests/test_tool_clients.py`).
- Stale/partial/conflicting data: `TestValidateEvidence`, `TestAfterValidateEvidence`
  (`tests/test_nodes.py`, `tests/test_routing.py`) — evidence-insufficiency and retry-vs-escalate
  logic, at the unit level (not reachable end-to-end yet).
- Cancellation/idempotency/concurrency: `test_cancelled_flag_stops_the_run_immediately`
  (`tests/test_builder.py`); idempotency behavior is declared per-tool in the registry but not
  exercised against a real duplicate call; no concurrency test exists.
- Restart/rollback: not tested (needs Docker).

No request ID/correlation ID/trace ID is attached here — no real run has ever executed against a
live dependency; every ID in every test is a freshly generated `uuid4()`.

## 11. UI evidence (if applicable)

Not applicable — this module has no UI.

## 12. Safety, security and privacy review

- [x] official warning/closure priority preserved — n/a yet (no node produces a risk assessment or
  route ranking to prioritize; nothing to violate this on yet).
- [x] LLM/provider/RAG data treated as untrusted — the LLM classifier's system prompt is a fixed
  constant (`app/intent/llm_classifier.py::SYSTEM_PROMPT`) that explicitly instructs the model to
  treat the user's message as data, not instructions; verified with an adversarial prompt-injection
  test case (`tests/test_intent.py::test_prompt_injection_attempt_is_not_treated_specially`) at the
  deterministic-rules layer, which is where injection would have to land first.
- [x] no secret/PII/exact location in code/log/trace/fixture — `app/progress/events.py` forbids
  extra fields by schema; `ToolCallRecord` stores a request-body hash, never the body;
  `Settings.internal_service_token` is masked in `repr()`/`str()` (tested in Phase 1,
  `test_token_is_masked_in_repr_and_str`, unchanged this round).
- [x] consent/auth/ownership enforced — `require_internal_auth` fails closed in production;
  `resume`/`cancel` check `user_scope_hash` before acting.
- [x] timeout/retry/cancel/idempotency bounded — every tool client has connect/total timeout,
  `max_attempts` from its registry entry, and the retry set is limited to the tool's own declared
  retryable codes (never a blanket "retry everything").
- [ ] source/freshness/quality/version retained — not yet meaningful: no node produces real
  evidence with source/freshness/quality attached (blocked on §8).
- [x] fallback/degraded behavior does not invent data — the central finding of this whole report:
  every blocked path fails loudly (`NodeNotImplementedError` -> `FAILED`/`INTERNAL_ERROR`) instead
  of returning a plausible-looking but fabricated result.
- [ ] dependency/image/secret scans passed — not run; no Docker build, no CI execution in this
  environment.

No findings to accept/waive — everything above that is unchecked is unchecked because the
underlying capability does not exist yet, not because a check failed.

## 13. Problems encountered and resolutions

| Problem | Root cause | Evidence | Resolution/workaround | Remaining risk |
| --- | --- | --- | --- | --- |
| `mypy` could not infer `NodeInputT` through a `Callable[[AgentState], ...]` type alias passed to `StateGraph.add_node` | LangGraph's `add_node` overloads infer their generic parameter from a `Protocol`'s concrete `__call__` signature; an opaque `Callable` alias hides that from the inference | Minimal repro kept in this report's authoring session, not committed; resolved directly in `app/budgets/__init__.py` | Changed `NodeFn`/`GuardedNodeFn` from `Callable` type aliases to `Protocol` classes with a concrete `state: AgentState` parameter | None — verified fix, `mypy --strict` clean |
| `Settings` itself refuses `LLM_ENABLED=true` without token/cost ceilings, which broke several intent tests that only cared about the LLM on/off switch | Test helper didn't supply the ceilings `Settings`'s own validator requires | `tests/test_intent.py` initial run: 4 failures, `ValidationError` | Added an `_llm_settings()` test helper supplying the required ceilings by default | None |
| `psycopg` can't adapt a bare Python `dict`/`str` to a `jsonb` column implicitly the way one might expect | psycopg3 needs an explicit `Jsonb(...)` wrapper for writing (unlike reading, which is automatic) | Caught by code review before any test ran against a real database (no Postgres available to catch it empirically) | `app/checkpoints/postgres.py` wraps every JSON write in `psycopg.types.json.Jsonb(...)` | **Not empirically verified** — no Postgres in this environment; flagged for the first real Docker run to confirm |
| No Python 3.12 or `uv` present on the machine this work was done on, despite `pyproject.toml` pinning `>=3.12,<3.13` | Sandboxed development environment, not the target deployment environment | — | Installed both via `pip install uv` then `uv python install 3.12`, and did all verification (`ruff`/`mypy`/`pytest`) under that real 3.12 interpreter rather than a substitute | None — this makes the verification in §10 trustworthy for the pinned version, not a guess |

## 14. Performance and operational behavior

Not measured — no running container, no load test. `/metrics` exists (Phase 1) but exports only
`agent_runs_total` and `agent_run_duration_seconds`, both unpopulated (nothing has called
`.observe()`/`.inc()` on them yet — Phase 6 scope).

## 15. Known limitations and technical debt

| Limitation/debt | User/safety impact | Workaround | Owner | Priority | Follow-up issue |
| --- | --- | --- | --- | --- | --- |
| `external_data`, `decision_engine`, `recommendation` have no published OpenAPI contract | Blocks the entire real orchestration path (Phase 4), and therefore Phases 5–7 | None from this module's side | Modules 04, 07, 08 | Blocking | Needed before any further Phase 4+ work on this module can be real rather than structural |
| No worker/queue — `POST /internal/v1/runs` runs synchronously | Cancellation is only meaningful for a parked `NEEDS_INPUT` run, not one "in flight"; a slow/hanging tool call blocks the HTTP request for up to `AGENT_TOTAL_TIMEOUT_SECONDS` | None | This module, Phase 4+ | High, once real tool calls exist | — |
| No `MAX_INPUT_TOKENS`/`MAX_OUTPUT_TOKENS`/LLM-call budget enforcement in `check_stop_conditions` | An LLM-heavy path (once Phase 2's classifier sees real traffic) could exceed a cost ceiling without the agent stopping itself | `Settings` already refuses to enable the LLM without ceilings *configured*, but nothing enforces them at runtime | This module, Phase 2 follow-up | Medium (low today: LLM path is off by default and untested against a live model) | — |
| Integration tests (Postgres/Redis) are written but never executed | Real behavior of the checkpointer, migrations, and publisher against real infrastructure is unverified | None | Whoever has Docker | High, before trusting this in an environment with real traffic | Run `uv run pytest` with Docker available, or set `TEST_DATABASE_URL` inside compose |
| No `compose.yaml`/`compose.dev.yaml` entry for `agent` | Can't `docker compose up agent` yet | The README documents the block to add, mirroring `compose.yaml`'s own example | Whoever owns the shared compose files (out of this module's scope this round) | Blocking for any Docker-based verification | — |
| No `docs/handoffs/` entry at the repo root | Breaks the convention every other module follows | This file exists at `services/agent/docs/handoffs/` instead | Whoever opens the PR | Low (cosmetic, but should be fixed before merge) | Move/copy this file |

## 16. Handoff to other members

| Recipient/module | What is ready | What they must change/do | Contract/config | Blocking? |
| --- | --- | --- | --- | --- |
| Module 02 (API/backend) | `POST/GET /internal/v1/runs*` implemented per §6 | Nothing yet requested from them — this module's internal API matches `00_API_AND_DATA_CONTRACTS.md` §5.1 as published | `app/api/internal.py` | No |
| Module 04 (external-data) | Nothing consumable yet | **Publish an OpenAPI contract** for `/internal/v1/context/query` under `packages/contracts/openapi/` | — | **Yes — blocks all of Phase 4+** |
| Module 05 (data-integration) | A real, tested client exists (`app/tools/clients/data_integration.py`) | Nothing required; if their `/internal/v1/snapshots` contract changes, this module's transcription in `app/tools/schemas.py` needs updating to match | `packages/contracts/openapi/internal-data-integration.yaml` | No, but drift risk (see §5 decision on hand transcription) |
| Module 06 (risk-knowledge) | Same as module 05, for `/internal/v1/evidence/package` | Same | `packages/contracts/openapi/internal-risk-knowledge.yaml` | No, same drift risk |
| Module 07 (decision-engine) | Nothing consumable yet | **Publish an OpenAPI contract** for `/internal/v1/decisions` | — | **Yes — blocks Phase 4's `make_decision`** |
| Module 08 (recommendation) | Nothing consumable yet | **Publish an OpenAPI contract** for `/internal/v1/recommendations` and `/internal/v1/emergency/contacts`; also has no Dockerfile yet | — | **Yes — blocks Phase 4's `format_recommendation` and the emergency shortcut** |

## 17. Commit and PR inventory

No commits were made — this work was done directly on the working tree at the user's explicit
request (they will package the changed files themselves rather than have this session push to
git). `git status --short` at the end of this work shows only files under `services/agent/`
modified or added; nothing outside that directory was touched.

- PR review comments resolved: n/a, no PR opened yet.
- Required checks status: n/a, no CI run triggered (no push).
- Rebased on main SHA: `3ffa77c`.
- Squash title proposed: `[M03] Phases 2-4 (partial): intent classification, typed tool clients, evidence retry loop`

## 18. Rollback and recovery

1. Feature flag/provider disable: `LLM_ENABLED=false` (default) fully disables the one new
   external dependency this round (OpenAI) with no other effect.
2. Application rollback image/tag: no image was ever built.
3. Migration downgrade or forward-fix: `001_agent_runs.sql` is additive-only; rollback is
   `DROP TABLE agent.tool_calls, agent.runs, agent.schema_migrations` if ever needed — no data to
   preserve, since nothing has written to these tables outside a test.
4. Model/policy/prompt/knowledge rollback: n/a, no model/policy owned by this module.
5. Data/cache cleanup: Redis keys are TTL'd (1 hour) and self-expire; nothing to clean up manually.
6. Verification after rollback: `uv run pytest -m "not integration"` should still pass with
   `LLM_ENABLED` unset/false.

## 19. Final declaration

- [ ] งานใน scope ครบตามหลักฐาน — **no**, Phases 5–7 and most of Phase 4 are not done; see §3
  for exactly which acceptance items are unmet and why.
- [x] ไม่มี required work ที่ซ่อนอยู่ — every gap is named in §4, §8, §15, and §16 with a reason and
  an owner.
- [~] documentation/env/contracts/migrations อัปเดต — `services/agent/`'s own docs are updated
  (`docs/diagrams/agent-state.md`, `docs/intent-and-required-fields.md`, `README.md`); the shared
  `packages/contracts/` was deliberately not touched (out of scope this round), and this report is
  not yet in its conventional repo-root location (see the note at the top of this file).
- [x] downstream owners ได้รับ handoff — §16.
- [ ] พร้อม merge — only as "Phase 0–3 complete, Phase 4 partial" work, with that scope stated
  explicitly in the PR description; not as "Module 03 complete."
- [ ] พร้อม release — no; the module cannot produce a real recommendation yet.

ผู้จัดทำ: Claude (agent session), on behalf of the user (คนที่ 3)

ผู้ review: —

วันที่: 2026-09-22
