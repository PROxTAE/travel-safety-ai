# `tests/contract/`

**เจ้าของ:** shared · maintainer คนที่ 2 (02-api)

Producer and consumer checks on `packages/contracts`. They read files only: no service, no
database, no network, no provider. That keeps them fast enough to gate every commit and
deterministic enough that a failure always means the contract changed.

## Run

```bash
uv run --project tests/contract pytest tests/contract
```

`uv.lock` is committed, so two machines install the same versions. The path is passed explicitly
because pytest resolves `testpaths` against the directory it was started from: from the repository
root without it, pytest would also collect every service's own suite in an environment that has
none of their dependencies.

## What each file is for

| File | Question it answers |
| --- | --- |
| `test_examples_match_schemas.py` | Do the published fixtures still match the schemas they claim, and does every captured fixture say where it came from? |
| `test_generated_python_models.py` | Can a Python service actually use the generated models, and do the safety-critical fields stay required? |
| `test_openapi_contract.py` | Does the public API still offer every endpoint the contract document promises, with authentication on by default and retries made safe? |

The JavaScript side is checked separately: `npm run check` in `packages/contracts` validates the
same fixtures with ajv and type-checks `consumer-checks/` against the generated TypeScript. Both
validators run because the services validate with Python and the web app with JavaScript, and a
schema only one of them accepts is a contract that will fail in production on the other side.

## What does not belong here

Anything that needs a running service, a database or a provider. Those are integration tests
(`tests/integration/`) or end-to-end tests (`tests/e2e/`). A contract test that reaches the network
becomes flaky, and a flaky gate gets switched off.
