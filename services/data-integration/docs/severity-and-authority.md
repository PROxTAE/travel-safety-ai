# Severity and source authority mapping (draft 0.1.0)

The wire enum is `INFO | MINOR | MODERATE | SEVERE | EXTREME | UNKNOWN`. Module 04 currently emits `UNKNOWN` for weather and disaster severity; it preserves provider measurements separately. The table below is a **proposed** mapping, not an approved safety policy. Until module 04 and the decision owners approve thresholds, production transforms must retain `UNKNOWN` with the original measurement and an `INCOMPLETE` quality flag. Never treat UNKNOWN as INFO.

| Provider and input | Proposed mapping rule, version `severity.provider/0.1.0` | Unmapped/limitations |
| --- | --- | --- |
| USGS `alert_level` (PAGER green/yellow/orange/red) | green→MINOR; yellow→MODERATE; orange→SEVERE; red→EXTREME | PAGER is estimated impact, not earthquake magnitude. Null/unrecognized→UNKNOWN. Magnitude stays separate; do not average it with alert level. |
| GDACS `alert_level` Green/Orange/Red | Green→MINOR; Orange→SEVERE; Red→EXTREME | These are GDACS impact bands, not USGS bands; no GDACS equivalent of MODERATE is inferred. Null/unrecognized→UNKNOWN. |
| EONET category / `event_type` | All categories→UNKNOWN pending category-specific intensity evidence | A category names the hazard type, not its severity. Mapping WILDFIRE or FLOOD straight to SEVERE would fabricate intensity. |
| Open-Meteo `weather_code` | Codes describe phenomenon; severity remains UNKNOWN until intensity, location, time, and route thresholds are jointly approved | Code alone does not encode exposure or a universal safety threshold. Null/unrecognized→UNKNOWN. Keep precipitation, wind, visibility and temperature as typed evidence. |

`severity.provider/0.1.0` cannot be activated solely by publishing this document. Activation requires tests with real sanitized cases, approval of threshold/version and explicit downstream handling of UNKNOWN. An official closure is a separate boolean/event with safety precedence; it must not be inferred from a severity rank.

## Authority ranking for conflict resolution

| Rank | SourceAuthority | Meaning and guardrail |
| ---: | --- | --- |
| 1 | `OFFICIAL` | Competent agency's direct record; verify agency and jurisdiction, not provider label alone. |
| 2 | `INTERGOVERNMENTAL` | Cross-agency source such as GDACS. |
| 3 | `LICENSED_PROVIDER` | Contracted provider or licensed data feed. |
| 4 | `COMMUNITY` | Community/curated evidence with attribution. |
| 5 | `UNKNOWN` | Authority could not be verified. |

This rank is one input alongside validity window, freshness, coverage, completeness and agreement. Preserve losing evidence and field-level lineage. A newer lower-rank record must not silently remove an active official warning; a contradictory safety-critical fact sets `CONFLICTING` for review. The provider-to-authority assignments themselves require module 04 review, especially NASA/USGS/GDACS records syndicated through another endpoint.
