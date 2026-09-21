# Golden fixtures from module 04

`tests/fixtures/golden/` holds sanitized module 04 responses used as deterministic test evidence. [`MANIFEST.json`](../tests/fixtures/golden/MANIFEST.json) records the endpoint, request, HTTP status, record counts, capability outcomes and SHA-256 of each capture.

## Capture again

With module 04 running on localhost port 8002 and `INTERNAL_SERVICE_TOKEN` available in the environment or the repo-root `.env`, run from the repo root:

```bash
python services/data-integration/scripts/capture_fixtures.py
```

The script calls `/internal/v1/context/query` for four public landmark cases, prints HTTP status and record counts, stores sanitized responses with SHA-256 provenance, and never prints or stores the token. Rerunning replaces time-dependent captures.

The fixtures are test evidence only. At runtime the service must query current providers. The route case exposes a module 04 envelope mismatch: `ROUTE=UNAVAILABLE` while `meta.degraded_services` is empty (P0-06).
