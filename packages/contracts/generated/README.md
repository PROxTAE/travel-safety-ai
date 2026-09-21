# `packages/contracts/generated/`

**เจ้าของ:** shared (generate เท่านั้น ห้ามแก้มือ)

Everything in here is produced from `../openapi/` and `../jsonschema/`. **Do not edit any of it.**
A hand edit makes the generated client disagree with the contract while still compiling, which is
the one kind of contract bug nobody notices until integration.

| Path | Produced by | Consumed by |
| --- | --- | --- |
| `openapi/public-api.bundled.yaml` | `npm run bundle` | both generators, and anything that wants the spec as one file |
| `typescript/public-api.d.ts` | `npm run generate:ts` | `apps/web` (module 01) |
| `python/smart_travel_contracts/` | `npm run generate:py` | Python services, starting with `services/api` |

Regenerate:

```bash
cd packages/contracts
npm run generate        # needs Node 22+ and uv on PATH
```

CI runs `./scripts/check-generated-clean.sh`, which regenerates and fails if the working tree
moves. So a change to a schema and its regenerated output belong in the same commit.

Read plan: [`IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md`](../../../IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md)
