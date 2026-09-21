# `packages/contracts/openapi/`

**เจ้าของ:** shared · maintainer คนที่ 2 (02-api)

| File | Surface | Owner |
| --- | --- | --- |
| `public-api.yaml` | Everything a browser may call — `/api/v1/**` plus `/health/*` | 02, reviewed by 01, 03, 08 |

The internal service APIs (`internal-agent.yaml`, `internal-external-data.yaml` and the rest listed
in the contract document) are added by their own module owners on their own `contract/` branches.

Entities are not defined here. They live in [`../jsonschema/common/`](../jsonschema/common/) and are
referenced with relative `$ref`s, so the public API, the internal APIs and the Python services all
describe the same objects instead of three near-copies.

```bash
cd packages/contracts
npm run lint      # redocly, with the rules in ../redocly.yaml
npm run bundle    # -> ../generated/openapi/public-api.bundled.yaml
```

Read plan: [`IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md`](../../../IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md)

## Available contracts

- `internal-risk-knowledge.yaml` — OpenAPI 3.1 contract version `1.0.0` for
  Module 06. It references the matching JSON Schema vocabulary and defines
  explicit degraded/unavailable behavior.

Contracts for the remaining services are still owned by their module owners.
