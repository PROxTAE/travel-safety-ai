# `packages/contracts/examples/`

Fixtures that every example in this repository is validated against in CI
(`npm run validate:examples`). They exist so a consumer can write a test before the producer is
built, and so a reviewer can see the shape of an answer without starting the stack.

## Two kinds, kept apart on purpose

| Folder | What it is | Where it may be used |
| --- | --- | --- |
| `structural/` | Hand-written objects that show the shape of a contract. Values are illustrative. | Documentation and deterministic tests. |
| `real-sanitized/` | Records actually captured from a real provider, with the capture recorded. | Deterministic automated tests only. |

Neither kind may be served at runtime. Nothing in `services/` or `apps/` reads this folder: a
fixture that reaches a user is indistinguishable from a fabricated safety answer, which is the one
failure mode this project cannot accept. The acceptance runbook greps for exactly that.

## File format

Every file is a wrapper so that provenance can travel with the value without breaking validation:

```json
{
  "target": "jsonschema/common/trip.schema.json",
  "kind": "structural",
  "summary": "one line about what this example shows",
  "provenance": { ... },
  "value": { ... }
}
```

- `target` — path of the schema the value is validated against, relative to `packages/contracts`.
  A JSON pointer may be appended, e.g. `jsonschema/common/weather.schema.json#/$defs/WeatherForecastPoint`.
- `kind` — `structural` or `real-sanitized`.
- `value` — the object under test. This is what a consumer copies.

For `kind: "real-sanitized"`, `provenance` is required and must carry:

| Field | Meaning |
| --- | --- |
| `provider` | Provider key, matching `SourceProvenance.provider`. |
| `source_url` | The exact URL that was called. |
| `captured_at` | When it was captured, ISO-8601 UTC. |
| `license` | The provider's terms for this data. |
| `attribution` | Text that must be shown wherever the data appears. |
| `upstream_content_hash` | SHA-256 of the canonical upstream record, so drift is detectable. |
| `redaction` | What was removed or changed, or `none` with a reason it was safe to keep. |

## Refreshing a real-sanitized fixture

Capture it again, update `captured_at` and `upstream_content_hash`, and re-run
`npm run validate:examples`. If the upstream shape changed, that is provider schema drift and it
belongs in a PR of its own with the adapter change — not a quiet fixture edit.

Never capture a response that contains personal data, a credential, a session identifier, or a
precise location belonging to a real person.
