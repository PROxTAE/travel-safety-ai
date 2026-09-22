# Quality gate proposal 0.1.0

**Proposal awaiting agreement from modules 03 and 07.** This document does not enable a production PASS decision. Module 04 currently leaves `quality.score=null`; module 05 must retain null until the formula and input availability are approved. Preserve flags, source times and conflict details alongside any score.

## Proposed score

For each applicable dimension, calculate a documented value in [0,1] at the assessment cutoff, then `score = 0.25*freshness + 0.20*completeness + 0.25*coverage + 0.15*agreement + 0.15*authority`. Proposed version: `quality.integrated/0.1.0`. Round only the final score to four decimal places, half-even. If any required dimension cannot be measured, score is `null` with `MISSING`/`INCOMPLETE`; do not renormalize the remaining weights or treat null as zero.

| Dimension | Proposed measurement | Unknown handling |
| --- | --- | --- |
| Freshness (0.25) | Fraction of required evidence within the approved provider/type freshness limit at the assessment cutoff. Compare forecast `valid_at` to route ETA separately from cache `fetched_at`/`expires_at`. | Missing observation/publication time remains null; no fetched-as-observed substitution. |
| Completeness (0.20) | Present applicable canonical fields divided by expected applicable fields; null differs from legitimate zero. | Provider capability unavailable makes dimension unmeasurable. |
| Coverage (0.25) | Proportion of route corridor/ETA samples with usable weather, hazards and mode-specific transport evidence. | No route geometry or coverage model gives null, not full coverage. |
| Agreement (0.15) | Fraction of comparable facts without unresolved material conflict. | If only one independent source exists, agreement is unknown, not 1. |
| Authority (0.15) | Approved authority rank mapped to a versioned [0,1] scale, weighted by relevance and active validity. | UNKNOWN authority leaves dimension unmeasurable; rank alone never deletes a warning. |

## Proposed gate (not approved)

| Outcome | Candidate rule | Required behavior |
| --- | --- | --- |
| `BLOCK` | Invalid schema/identity/route geometry, no usable route when corridor analysis is required, missing critical safety evidence, or unresolved critical official closure conflict. | Do not issue a normal risk inference; return explicit error/degraded evidence. |
| `DEGRADED` | Valid input but score null, any required capability unavailable, stale evidence, partial corridor/weather/transport coverage, or unresolved noncritical conflict. | Carry flags, unavailable capabilities, source times and lower confidence. Never present an empty 200 as safe. |
| `PASS` | No blocking/degraded condition and score ≥ 0.85 with all critical fields and approved freshness/coverage thresholds. | Preserve provenance and score version. |

`score < 0.85` without a blocking condition is proposed DEGRADED. Priority is BLOCK > DEGRADED > PASS; a high weighted score cannot overrule a safety-critical flag. The exact critical fields, freshness windows, coverage threshold and authority scale require modules 03/07 sign-off. Module 06 must agree how DEGRADED and null raw features enter inference.
