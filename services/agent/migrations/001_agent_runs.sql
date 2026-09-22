-- Module 03 ownership per 00_API_AND_DATA_CONTRACTS.md §8 ("agent — คน 3"). The LangGraph
-- checkpointer manages its own tables via AsyncPostgresSaver.setup() and is not touched here.
--
-- agent.runs is this service's own run-lifecycle record: one row per request_id, independent of
-- how many checkpoints that run produced. thread_id is stored explicitly (conversation_id when the
-- request has one, otherwise request_id itself — app/checkpoints/postgres.py picks it once at
-- create time) so a later resume/cancel does not have to recompute which LangGraph thread a run
-- lives on. final_state is only ever a serialized AgentState (never a raw provider payload).
CREATE SCHEMA IF NOT EXISTS agent;

CREATE TABLE IF NOT EXISTS agent.runs (
    request_id uuid PRIMARY KEY,
    trip_id uuid NOT NULL,
    conversation_id uuid,
    thread_id text NOT NULL,
    user_scope_hash text NOT NULL,
    status text NOT NULL,
    graph_version text NOT NULL,
    contract_version text NOT NULL,
    prompt_version text,
    policy_version text,
    budgets_json jsonb NOT NULL,
    final_state jsonb,
    supersedes_request_id uuid REFERENCES agent.runs (request_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS runs_conversation_id_idx ON agent.runs (conversation_id);

-- Not written by any code yet (Phase 1 has no real tool calls) — the table exists now so Phase 3's
-- typed tool clients (`03_TRAVEL_AI_AGENT_IMPLEMENTATION.md` Phase 3, "tool call audit เก็บ
-- hash/status/timing ไม่เก็บ sensitive raw body") have somewhere to write from day one.
CREATE TABLE IF NOT EXISTS agent.tool_calls (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES agent.runs (request_id),
    tool_name text NOT NULL,
    input_hash text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    duration_ms integer,
    error_code text
);

CREATE INDEX IF NOT EXISTS tool_calls_request_id_idx ON agent.tool_calls (request_id);
