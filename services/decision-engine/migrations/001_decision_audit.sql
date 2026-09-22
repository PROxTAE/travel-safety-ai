CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS decision;

CREATE TABLE IF NOT EXISTS decision.audit_events (
    audit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id uuid NOT NULL,
    request_id uuid NOT NULL,
    snapshot_id uuid NOT NULL,
    action_code text NOT NULL CHECK (action_code IN ('NORMAL', 'CHANGE_ROUTE', 'DELAY', 'AVOID')),
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    escalation_required boolean NOT NULL,
    policy_version text NOT NULL,
    policy_checksum text NOT NULL,
    rules_fired text[] NOT NULL,
    input_hash text NOT NULL,
    output_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_events_request_idx ON decision.audit_events (request_id, created_at DESC);