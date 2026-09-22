CREATE TABLE IF NOT EXISTS decision.policy_versions (
    policy_version text PRIMARY KEY,
    contract_version text NOT NULL,
    policy_checksum text NOT NULL,
    status text NOT NULL CHECK (status IN ('DRAFT', 'PENDING_REVIEW', 'APPROVED', 'RETIRED')),
    policy_document jsonb NOT NULL,
    approval_record jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz NULL,
    retired_at timestamptz NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS policy_versions_one_approved_idx
    ON decision.policy_versions (status)
    WHERE status = 'APPROVED';

CREATE TABLE IF NOT EXISTS decision.prompt_versions (
    prompt_version text PRIMARY KEY,
    prompt_checksum text NOT NULL,
    status text NOT NULL CHECK (status IN ('DRAFT', 'PENDING_REVIEW', 'APPROVED', 'RETIRED')),
    prompt_template text NOT NULL,
    approval_record jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz NULL,
    retired_at timestamptz NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS prompt_versions_one_approved_idx
    ON decision.prompt_versions (status)
    WHERE status = 'APPROVED';