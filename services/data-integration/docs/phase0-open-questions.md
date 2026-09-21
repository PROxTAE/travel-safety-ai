# Phase 0 decisions and known gaps

These items require human review before the draft semantics become version 1.0.0. The documents in this directory are proposals, not an agreed inter-service contract.

| ID | Decision / evidence | Who must agree |
| --- | --- | --- |
| P0-01 | Verify each module 04 provider-to-field/unit/time mapping, including USGS PAGER, GDACS alert color, EONET category and Open-Meteo weather code. Decide whether proposed severity thresholds in `severity-and-authority.md` are acceptable. | Module 04 with module 05; safety meaning also module 07 |
| P0-02 | **Resolved for features:** module 05 adopts the module 06 proposal `feature_schema.v1.yaml` 1.0.0 instead of its own 0.1.0 draft. Open: the official alert booleans must be allowed to be null (#43), and no source supplies evacuation orders (#44). Corridor distance/time windows and online/offline sharing remain open. | Module 06 with module 05 |
| P0-03 | Approve critical fields, dimension measurement/weights, freshness and coverage thresholds, PASS/DEGRADED/BLOCK behavior. | Modules 03 and 07 with module 05 |
| P0-04 | Decide input contract for route candidates: module 04 intentionally emits `exposure=null` and `risk_level=UNKNOWN`, while shared `RouteCandidate` schema requires `exposure`. Do not silently coerce null to safe. A versioned producer/consumer contract change may be needed. | Modules 04, 05, 06 and contract owner |
| P0-05 | Decide transport/official-alert source: module 04 combined endpoint currently emits neither a `transport` array nor a separate `official_alerts` array. `data.capabilities` does not include TRANSIT. | Modules 04, 05 and 03 |
| P0-06 | In captured `route_unavailable_no_credential`, HTTP 200 has `ROUTE=UNAVAILABLE` and `routes=[]`, but `meta.degraded_services=[]`. Confirm whether module 04 must correct its envelope or a versioned contract change is needed. Module 05 must inspect capability outcomes regardless. | Module 04 and contract owner |
| P0-07 | Global capture has 517 disaster records from USGS/GDACS/EONET, but `duplicate_groups=[]`. Establish a verified overlapping-event golden case before asserting dedup/conflict correctness. Do not invent duplicate records. | Module 04 with module 05 |
| P0-08 | ORS credential is absent, so no live canonical route geometry or actual route-across-timezone/dateline fixture was captured. The old raw ORS fixture is provider payload, not a module 04 canonical record. | Module 04 and module 05; credential/coverage owner |

Golden captures are in `tests/fixtures/golden/`. All four endpoint calls returned HTTP 200 during capture; inspect each manifest entry for counts, capability outcomes, hashes and the route degraded mismatch. A source becoming stale is tested by freezing the test clock relative to captured `fetched_at`, without altering fixture values. The files contain public landmark queries only and must never be served as current runtime data.
