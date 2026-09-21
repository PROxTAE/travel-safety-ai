# Model card: `<model-name>` `<version>`

Status: `CANDIDATE | APPROVED | ACTIVE | RETIRED`

## Ownership and approval

- Owner:
- Approver(s):
- Approved at:
- Git commit:
- Artifact URI (no credential):
- Artifact SHA-256:
- Signature algorithm/key ID:
- Feature schema version:
- Threshold policy version:

## Intended use and prohibited use

- Prediction unit: one route candidate, departure window, and immutable snapshot.
- Intended downstream consumer: deterministic decision policy.
- This model does not choose the final action and must not weaken an official
  closure, evacuation, no-go order, or extreme warning.
- Prohibited: safety guarantees, autonomous retraining, or inference with an
  unknown feature schema.

## Training data

- Dataset manifest ID/checksum:
- Source authorities/licenses:
- Query window and prediction cutoff:
- Label method and review sample:
- Time/geography split:
- Class distribution:
- Known coverage gaps:

## Evaluation

Record point estimates and confidence intervals. Include per-geography,
season, hazard, travel-mode, and degraded-coverage slices.

| Metric | Overall | Required target | Result |
| --- | ---: | ---: | --- |
| HIGH recall | | | |
| HIGH false-negative rate | | | |
| PR-AUC | | | |
| ROC-AUC | | | |
| Brier score | | | |
| Expected calibration error | | | |
| Inference p95 (ms) | | 300 | |
| Peak memory (MiB) | | | |

Attach confusion matrices, calibration plots, subgroup results, and the
rule-only baseline comparison. Do not promote while required targets are null
or unmet.

## Explainability and safety

- Controlled reason-code mapping:
- Calibration method and leakage control:
- Safety overrides verified:
- Missing/unknown behavior:
- Known false-negative patterns:

## Operational use

- Warm-up behavior:
- CPU/RAM requirements:
- Drift signals:
- Rollback version and command:
- Retirement reason/date:
