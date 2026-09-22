# Decision Policy v1

## Governance

- Policy version: `1.0.0`
- Contract version: `1.0.0`
- Runtime status: `APPROVED` in the policy file
- Governance record: `../registry.yaml`
- Policy checksum: recorded in the registry and verified during release review
- Rollback: activate the previous registry entry only after checksum verification and approval

The evaluator uses first-match semantics in ascending priority order. A higher-priority
matched rule locks the action; later rules are recorded as not matched and cannot weaken it.

## Thresholds

| Name | Value | Boundary behavior |
| --- | ---: | --- |
| `high_risk_score` | `0.65` | At or above means high risk |
| `materially_safer_delta` | `0.15` | At or above the delta qualifies an alternative |
| `alternative_min_quality` | `0.60` | At or above is usable |
| `delay_risk_score` | `0.45` | At or above may delay when time-dependent |
| `max_delay_minutes` | `180` | Duration must be at or below the limit |
| `minimum_confidence` | `0.60` | Below escalates; it never upgrades NORMAL |
| `threshold_margin` | `0.05` | Near-threshold risk escalates for review |
| `max_uncertainty` | `0.25` | At or above escalates |

## Priority and conflict matrix

| Priority | Rule | Action | Conflict behavior |
| ---: | --- | --- | --- |
| 1 | `R001_OFFICIAL_CLOSURE` | `AVOID` | Always wins over model score and alternatives |
| 2 | `R002_HIGH_RISK_NO_SAFE_ROUTE` | `AVOID` | High risk without a usable safer route |
| 3 | `R003_MATERIALLY_SAFER_ROUTE` | `CHANGE_ROUTE` | Requires delta and alternative quality thresholds |
| 4 | `R004_TIME_DEPENDENT_RISK` | `DELAY` | Requires score, reason code, and duration thresholds |
| 5 | `R005_LOW_RISK_USABLE_EVIDENCE` | `NORMAL` | Only after all stronger rules fail |

Inconsistent identifiers, stale/conflicting evidence, unknown risk, or missing assessments
produce a conservative result and `escalation_required`; they never default to NORMAL.

## Reason-code ownership

The evaluator may emit only reason codes already defined by the shared risk contract,
including `OFFICIAL_CLOSURE`, `CONFLICTING_EVIDENCE`, `INSUFFICIENT_EVIDENCE`,
`ACTIVE_DISASTER_ON_CORRIDOR`, `LONG_EXPOSURE_WINDOW`, `SPARSE_DATA_COVERAGE`, and
`NO_ACTIVE_RESTRICTION`. LLM prose cannot create new reason codes.