# Data Integration (module 05)

Owner: module 05. Planned service: validate and normalize canonical module 04 records, preserve lineage, resolve duplicates and conflicts, intersect hazards with the full route and ETA, then persist immutable `IntegratedTravelContext` snapshots for modules 03/06/07.

**Status: Phase 0 semantic drafts and captured test evidence.** No runtime service, database migrations or snapshot endpoint exists yet. The [implementation plan](../../IMPLEMENTATION_PLANS/05_DATA_INTEGRATION_IMPLEMENTATION.md) describes later phases. Drafts need producer/consumer review before their versions are locked.

## Phase 0 references

- [Canonical input data dictionary](docs/data-dictionary.md)
- [Transformation registry](docs/transformation-registry.md)
- [Severity and authority mapping](docs/severity-and-authority.md)
- [Raw feature schema 0.1.0](config/feature_schema.yaml)
- [Quality gate proposal](docs/quality-gate.md)
- [Open decisions and coverage gaps](docs/phase0-open-questions.md)
- [Golden fixture manifest](tests/fixtures/golden/MANIFEST.json)

## Capture real canonical fixtures

With module 04 running on localhost port 8002 and `INTERNAL_SERVICE_TOKEN` available in the environment or the repo-root `.env`, run from the repo root:

```bash
python services/data-integration/scripts/capture_fixtures.py
```

The script calls `/internal/v1/context/query` for four public landmark cases, prints HTTP status and record counts, stores sanitized responses and SHA-256 provenance, and never prints or stores the token. Rerunning replaces time-dependent captures. The fixtures are test evidence only; runtime must query current providers. The route case currently exposes a module 04 envelope mismatch: `ROUTE=UNAVAILABLE` while `meta.degraded_services` is empty.
