# `packages/contracts/`

**เจ้าของ:** shared · maintainer คนที่ 2 (02-api) + lead

Source of truth for how every service in this system talks to every other one, and for the shape of
the entities they exchange. Eight modules are built in parallel; this folder is what stops them
from inventing eight slightly different versions of the same object.

Plan: [`IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md`](../../IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md)

Changing anything here needs the affected module owners plus the lead — see
[`00_GIT_DOCKER_DELIVERY_RULES.md` §7](../../IMPLEMENTATION_PLANS/00_GIT_DOCKER_DELIVERY_RULES.md).

## Layout

```text
packages/contracts/
├─ jsonschema/common/     canonical entities — the source of truth
├─ openapi/               public-api.yaml, which $refs those entities
├─ examples/              fixtures, validated in CI (see examples/README.md)
├─ consumer-checks/       TypeScript that must keep compiling against the generated types
├─ scripts/               lint, validate, bundle, generate
└─ generated/             GENERATED — never edited by hand
   ├─ openapi/public-api.bundled.yaml
   ├─ typescript/public-api.d.ts
   └─ python/smart_travel_contracts/
```

## Commands

```bash
cd packages/contracts
npm install

npm run check          # lint + schema validation + example validation + consumer typecheck
npm run generate       # bundle -> TypeScript -> Python  (needs uv on PATH)
./scripts/check-generated-clean.sh   # what CI runs: regenerate, fail if the tree moved
```

The Python contract tests live in [`tests/contract/`](../../tests/contract/) and run with
`uv run --project tests/contract pytest`.

## Conventions that are not obvious from the files

**Entities live in JSON Schema, not in the OpenAPI document.** `public-api.yaml` `$ref`s them. That
way the same definitions serve the public API, the internal service APIs and the Python services,
instead of each restating them.

**The schemas carry no `$id`.** Relative `$ref`s resolve by file name, which is what redocly,
openapi-typescript, ajv and datamodel-code-generator all do. Adding `$id` back would re-root every
reference at an unfetchable URL and break all four.

**Responses are open, requests are closed.** Entity and response schemas do not set
`additionalProperties: false`, so adding an optional field stays backward compatible for consumers
that validate strictly. Request bodies do set it, because an unrecognised field on input is either
a client bug or an attack, and ignoring it hides both.

**A value the provider did not supply is `null`, and the field is still required.** Zero
precipitation and unknown precipitation are different facts. Making the field optional would let a
consumer confuse "absent from the payload" with "not measured".

**Anything that can influence a safety decision carries `source` and `quality`.** That is what lets
the UI show where an answer came from and how old it is, and what lets a reviewer trace a
recommendation back to a feed.

**Coordinates are `[longitude, latitude]`, always.** `Position` bounds each element separately so a
swapped pair fails validation rather than quietly relocating a Bangkok trip into the Indian Ocean.

## Known limitation in the generated Python

`datamodel-code-generator` flattens JSON Schema `prefixItems` into a plain length-checked list, so
the generated Pydantic `Position` accepts a longitude of 1000. Coordinate ranges must therefore be
validated at the API boundary rather than by trusting the model. This is pinned by
`tests/contract/test_generated_python_models.py::test_generated_python_does_not_enforce_coordinate_bounds`,
which will fail if a generator upgrade closes the gap.

## Changing a contract

1. Open an issue or a short ADR naming the producer, the consumers and the rollout.
2. Branch `contract/<module>-<description>` from `main`.
3. Edit the JSON Schema or `public-api.yaml`, update or add an example, run `npm run check`.
4. Run `npm run generate` and commit the generated output in the same commit as the source.
5. Add or update a test in `tests/contract/` that would have caught the old behaviour.
6. Adding an optional field is backward compatible. Renaming, retyping, removing, or making a field
   required is breaking: it needs a version bump and a migration path, not a quiet edit.
