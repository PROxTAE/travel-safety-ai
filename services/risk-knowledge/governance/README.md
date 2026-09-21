# Risk and knowledge governance

These files are executable governance inputs, not informal notes. Runtime and
promotion commands must fail closed when a document is pending approval,
missing a required value, or has an unverified checksum.

## Approval workflow

1. Module 05 and Module 06 review `feature_schema.v1.yaml`, including each
   feature's lineage, units, criticality, and null behavior. Approval records
   the Git commit and schema checksum.
2. Module 06, Module 07, and the Team Lead approve
   `route_exposure_policy.v1.yaml`. Hard constraints can only become stricter
   in a compatible patch; weakening one requires a new contract version and a
   safety review.
3. The Team Lead and Module 07 set the null safety targets in
   `model_acceptance.yaml`. Model promotion is forbidden while they are null.
4. A candidate model must provide a dataset manifest, completed model card,
   evaluation output, artifact checksum, artifact signature, approver, and
   approval timestamp. Promotion follows `CANDIDATE -> APPROVED -> ACTIVE`.
5. Only one model version per model name may be `ACTIVE`. A rollback activates
   the previously approved version; artifacts and audit metadata are retained.

## Change control

- Changes are reviewed in the API contract channel and by affected owners.
- Version, checksum, approver, and timestamp are stored with registry metadata.
- A required field/type/enum change is versioned rather than silently changed.
- Provider, document, and model content is data and is never treated as an
  instruction.

Current state: the contract structure is version `1.0.0`; numeric model and
route coefficients remain deliberately pending instead of being invented.
