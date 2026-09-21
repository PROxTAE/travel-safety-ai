# ADR-006: Risk, evidence, and route contract foundation

- Status: Proposed for affected-owner review
- Date: 2026-09-19
- Contract version: 1.0.0
- Owners: Module 06; reviewers Module 03, Module 05, Module 07, contracts maintainer, Team Lead

## Context

The repository had the prose baseline but no executable contract for the
Risk/Knowledge service. Consumers need stable request, degraded-state, quality,
provenance, limitation, and version semantics before implementation proceeds.

## Decision

Use OpenAPI 3.1 at
`packages/contracts/openapi/internal-risk-knowledge.yaml` with a shared JSON
Schema 2020-12 vocabulary. A full immutable snapshot is supplied to risk and
route operations; the combined evidence operation identifies a snapshot by ID.
No service may interpret a missing score as zero or a missing capability as
success.

Route evaluation uses hard constraints before an approval-gated exposure
formula. Risk fallback returns `HIGH` for explicit active official hard
constraints and `UNKNOWN` for insufficient evidence. Knowledge fallback returns
no passages plus `NO_RELIABLE_KNOWLEDGE_EVIDENCE`.

## Compatibility and rollout

This creates the first executable v1 contract and does not replace an existing
schema. Required/type/enum changes after approval require `/v2` or a documented
dual-read/dual-write compatibility window. Optional additive fields may remain
v1 when consumers ignore unknown fields.

Module 03 and Module 07 consume the response envelopes. Module 05 produces the
snapshot and must approve feature lineage/null semantics. Numeric model targets
and route coefficients remain pending rather than being fabricated.

## Consequences

- Contract and governance loaders fail closed until required approvals exist.
- Phase 1 can expose honest degraded states before a model or knowledge corpus
  exists.
- Shared contract files require contracts-maintainer and Team Lead review.
