# Unsupported coverage and degraded UX — for คน 1 (web) and คน 2 (public API)

Phase 0 deliverable 5. This is the honest list of what module 04 **cannot** answer,
so the UI can say so instead of rendering an empty state that reads like "nothing is
wrong".

The governing rule from `00_SHARED_PROJECT_CONTEXT.md` § 10: *if evidence is
insufficient, give a conservative result or ask for more input — never conclude
"safe".* An empty hazard list and an unreachable hazard provider must never look
the same to a user.

## Capability status today

| Capability | Status | What the user must be told |
| --- | --- | --- |
| Geocoding | ✅ available | — |
| Weather forecast | ✅ available | model forecast, not observation |
| Earthquake and multi-hazard events | ✅ available | USGS + GDACS + EONET. Sources overlap; duplicates are **grouped, not merged** — see `duplicate_groups` |
| Road routing | ❌ unavailable | "Route planning is not configured for this deployment" |
| Nearby emergency POI | ❌ unavailable | "Nearby places search is not available" |
| Flight status / search | ❌ unavailable | "Flight information is not available" |
| Public transit realtime | ❌ unavailable | "Transit coverage is not available for this area yet" |

Four of seven user-visible capabilities are unavailable. All four are blocked on
a credential or a Lead decision, not on code — see
[`lead-approval-checklist.md`](lead-approval-checklist.md).

One more rule the earthquake capability makes concrete: **an empty `events` list
means "no hazards were reported", and the API guarantees it never means "we could
not reach the sources".** If every disaster source fails the request fails with an
error envelope, so the UI can never render a reassuring empty map by accident. If
only some fail, the answer comes back with the failed ones named in
`meta.degraded_services` — which the UI must show, because a partial hazard list
looks exactly like a complete one.

## Contract for the unavailable state

Module 04 returns the standard error envelope with
`code: "UNSUPPORTED_COVERAGE"` and a machine-readable reason. It never returns an
empty success payload to mean "unavailable".

```json
{
  "error": {
    "code": "UNSUPPORTED_COVERAGE",
    "message": "Route planning is not available in this deployment",
    "field_errors": [],
    "retryable": false,
    "retry_after_seconds": null
  },
  "meta": { "request_id": "…", "correlation_id": "…", "contract_version": "1.0.0" }
}
```

For a partial result — some providers answered, some did not — the success envelope
carries `meta.degraded_services[]`, and the affected records carry a `QualityFlag`.
**A degraded response is a success envelope; a fully unavailable capability is an
error envelope.** That split is what lets the UI choose between "showing you less"
and "cannot answer".

## What the UI must do

1. **Disable, do not hide.** A disabled control with a reason teaches the user the
   feature exists and why it is off. A hidden control reads as "this app cannot do
   that", and we lose the chance to explain.
2. **Never show a flight or transit example.** The module plan bans Amadeus test
   data as a real result. The UI must not fill the gap with a placeholder card
   either — a realistic-looking fake is worse than an empty state, because a
   traveller may act on it.
3. **Surface staleness on the record, not in a global banner.** A 3-hour-old
   forecast next to a 40-second-old earthquake needs two different timestamps, not
   one page-level "last updated".
4. **Show source and time on anything safety-relevant.** Every record carries
   `source.source_url` and `source.observed_at`; both are meant to be rendered.
5. **`observed_at: null` is meaningful.** It means the provider never supplied an
   observation time — render "time unknown", not the fetch time. Weather forecast
   always has `observed_at: null` because it is model output.

## Coverage limits inside "available"

Even the green rows have real edges:

| Capability | Limit the UI should expect |
| --- | --- |
| Geocoding | thin for informal settlements and recently renamed places; same-name collisions are common (`feature_code` may help — open question Q1) |
| Weather | grid-snapped — the returned coordinate is the model cell, not the requested point; `quality.coverage` carries the offset |
| Earthquake | USGS summary feeds are windowed (hour/day/week/month) and have **no bbox filter**; a very recent quake may not be in the chosen window yet |
| Multi-hazard | GDACS alert level is Green/Orange/Red, an alert scale — it is not the `Severity` enum and must not be relabelled as one |
| EONET | curated and slower to publish than USGS/GDACS; treat as corroboration, never as the sole basis for an alert |

## Licence constraint that reaches the UI

Open-Meteo's free tier is **non-commercial**, and both it and openrouteservice
require visible attribution. The strings are in `providers.yaml` under
`attribution.text`. Any screen showing weather, geocoded places or routes must
render the attribution for the providers that contributed to it.

## Open questions for คน 1 / คน 2

| # | Question | Needs |
| --- | --- | --- |
| U1 | Does the public API pass `UNSUPPORTED_COVERAGE` through unchanged, or collapse it into a per-capability availability map on the trip response? | คน 2 |
| U2 | Is there a design for the disabled-capability state in `assets/ui-screens/`, or does one need drawing? | คน 1 |
| U3 | Where does provider attribution render — per card, or once per screen? | คน 1 |
