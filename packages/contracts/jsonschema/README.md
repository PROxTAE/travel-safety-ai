# `packages/contracts/jsonschema/`

**เจ้าของ:** shared · maintainer คนที่ 2 (02-api), review จาก owner ที่ผลิต/บริโภค entity นั้น

Canonical entities, in JSON Schema draft 2020-12. This is the source of truth: the OpenAPI
documents `$ref` these files, and both the TypeScript and the Python clients are generated from the
result.

`common/` holds the entities every module shares — `LocationRef`, `Trip`, `TravelRequest`,
`RouteCandidate`, `IntegratedTravelContext`, `RiskAssessment`, `DecisionResult`,
`RecommendationResponse` and the rest of the list in §8 of the shared context.

Conventions that are easy to get wrong are written down in
[`../README.md`](../README.md): no `$id`, open responses and closed requests, required-but-nullable
fields, and `[longitude, latitude]` ordering.

```bash
cd packages/contracts
npm run validate:schemas   # compiles every file with the validator the services use
```

Who may change which field: [`docs/api/field-ownership-matrix.md`](../../../docs/api/field-ownership-matrix.md)

Read plan: [`IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md`](../../../IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md)
