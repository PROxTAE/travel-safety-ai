# Canonical field mapping — module 04

Phase 0 deliverable 3: what module 04 emits, field by field, so that **คน 5**
(canonical records / units / quality) and **คน 6** (required feature fields) can
sign off before adapters are written.

Authority is `00_API_AND_DATA_CONTRACTS.md` § 3. This document does not invent
schema — it records how each real provider payload lands in that schema, and where
the fit is imperfect. Every mapping below was derived from the captured fixtures in
[`../tests/fixtures/real-sanitized/`](../tests/fixtures/real-sanitized/), not from
documentation alone.

Conventions that apply everywhere:

- timestamps ISO-8601 **UTC** with a `Z` suffix
- coordinates `[longitude, latitude]`, GeoJSON RFC 7946
- units: °C, km/h, mm, cm, m, seconds
- a value the provider does not supply is `null` **plus** a `QualityFlag` — never `0`
- unknown provider enum values map to `UNKNOWN`, never a new string

---

## 1. `LocationRef` ← Open-Meteo Geocoding — ✅ implemented (Phase 2)

Fixture: `open_meteo_geocoding/search_bangkok.json`

| Canonical | Provider | Note |
| --- | --- | --- |
| `place_id` | `results[].id` | prefixed `open_meteo:` to keep it provider-scoped |
| `display_name` | `results[].name` + `admin1` + `country` | joined by the adapter; provider has no preformatted label |
| `coordinates` | `[results[].longitude, results[].latitude]` | provider gives lat/lon as separate floats — order must be flipped |
| `country_code` | `results[].country_code` | already ISO-3166-1 alpha-2 uppercase |
| `admin1` | `results[].admin1` | absent for city-states → `null` |
| `timezone` | `results[].timezone` | IANA, e.g. `Asia/Bangkok` |
| `provider` | literal `open_meteo` | |
| `confirmed_by_user` | **not set by module 04** | ownership sits with คน 1/2; module 04 always emits `false` |

Unmapped provider fields (`elevation`, `feature_code`, `population`, `admin1_id`,
`country_id`) are dropped. `feature_code` is the only one worth keeping — **open
question Q1**.

---

## 2. `WeatherForecastPoint` ← Open-Meteo Forecast — ✅ implemented (Phase 2)

Fixture: `open_meteo_weather/forecast_bangkok.json`, captured with
`timezone=UTC&wind_speed_unit=kmh&precipitation_unit=mm&temperature_unit=celsius`.

| Canonical | Provider (`hourly.*`) | Provider unit | Conversion |
| --- | --- | --- | --- |
| `valid_at` | `time[i]` | `iso8601` | **append `Z`** — see below |
| `temperature_c` | `temperature_2m[i]` | `°C` | none |
| `apparent_temperature_c` | `apparent_temperature[i]` | `°C` | none |
| `precipitation_mm` | `precipitation[i]` | `mm` | none |
| `precipitation_probability` | `precipitation_probability[i]` | `%` | none (0–100 int) |
| `snowfall_cm` | `snowfall[i]` | `cm` | none — provider default is already cm |
| `wind_speed_kmh` | `wind_speed_10m[i]` | `km/h` | none |
| `wind_gust_kmh` | `wind_gusts_10m[i]` | `km/h` | none |
| `visibility_m` | `visibility[i]` | `m` | none |
| `weather_code` | `weather_code[i]` | WMO code | kept as the raw WMO integer |
| `location` | request coordinate, echoed as `latitude`/`longitude` | | provider snaps to its grid — echo, do not assume the request value |
| `severity` | *derived* | | **open question Q2** |
| `quality`, `source` | *adapter-built* | | see § 6 |

Three traps confirmed against the fixture:

1. **`time` has no zone suffix.** With `timezone=UTC` the provider returns
   `"2026-09-19T00:00"` and reports `timezone: "GMT"`, `utc_offset_seconds: 0`.
   The adapter must assert `utc_offset_seconds == 0` and append `Z`. Parsing this
   string as naive local time is the single easiest way to ship a wrong forecast.
2. **`hourly` is column-oriented** — parallel arrays, not a list of objects. Every
   array must be the same length as `time`; a ragged response is
   `PROVIDER_SCHEMA_CHANGED`, not a partial result.
3. **The returned coordinate is the model grid point**, not the requested one.
   The adapter records the haversine distance as a quality note, and flags
   `INFERRED` past 25 km.
4. **A batched request returns a JSON array**, a single-coordinate request
   returns an object — and the array carries no id field, so results map back to
   requests **by position only**. Found while implementing Phase 2, not in the
   documentation; fixture `open_meteo_weather/forecast_batched.json`.

---

## 3. `DisasterEvent` ← USGS / GDACS / EONET

Required canonical fields: `event_id`, `event_type`, `title`, `description`,
`severity`, `geometry`, `effective_at`, `ends_at`, `instruction`, `official`,
`quality`, `source`.

### 3.1 USGS — fixture `usgs/significant_month.json`

| Canonical | Provider | Note |
| --- | --- | --- |
| `event_id` | `features[].id` | prefixed `usgs:`; `properties.ids` holds cross-network aliases used for dedup |
| `event_type` | constant `EARTHQUAKE` | feed is single-hazard |
| `title` | `properties.place` | |
| `description` | composed from `mag`, `place`, depth | provider has no description field |
| `severity` | ← `properties.mag` | **open question Q2** |
| `geometry` | `features[].geometry` | Point `[lon, lat, depth_km]` — **3 ordinates**; strip depth for the canonical Point and keep it as an attribute |
| `effective_at` | `properties.time` | **epoch milliseconds** → ISO-8601 UTC |
| `ends_at` | `null` | earthquakes are instantaneous |
| `instruction` | `null` | USGS feed carries none |
| `official` | `true` | authority `OFFICIAL` |
| `source.source_url` | `properties.url` | |
| `source.observed_at` | `properties.time` | real observation time |
| `source.published_at` | `properties.updated` | epoch ms |

`properties.alert` (PAGER green/yellow/orange/red) is impact, not magnitude, and is
frequently `null`. Do not overwrite `severity` with it — **open question Q3**.

### 3.2 GDACS — fixture `gdacs/eventlist_eq.json`

| Canonical | Provider (`features[].properties.*`) | Note |
| --- | --- | --- |
| `event_id` | `eventid` + `episodeid` | prefixed `gdacs:`; episode matters — one event has many episodes |
| `event_type` | `eventtype` | `EQ→EARTHQUAKE`, `TC→CYCLONE`, `FL→FLOOD`, `VO→VOLCANO`, `WF→WILDFIRE`, `DR→OTHER`; anything else → `OTHER` |
| `title` | `eventname` or `name` | `eventname` is often empty |
| `description` | `description` | use plain text, **never** `htmldescription` |
| `severity` | `severitydata.severity` + `alertlevel` | **open question Q2/Q3** |
| `geometry` | `features[].geometry` | Point |
| `effective_at` | `fromdate` | **no zone suffix** — see below |
| `ends_at` | `todate` | same |
| `official` | `true` | authority `INTERGOVERNMENTAL` |
| `source.source_url` | `url.report` | |

**`fromdate`/`todate` arrive as `"2026-08-28T05:13:35"` with no offset.** The
adapter treats them as UTC and attaches a quality note recording that assumption.
Silently parsing them as local time shifts every GDACS event by the host offset.

`alertlevel` is `Green|Orange|Red` — an alert scale, not the project `Severity`
enum. It must not be cast directly.

### 3.3 NASA EONET — fixture `eonet/events.json`

| Canonical | Provider (`events[].*`) | Note |
| --- | --- | --- |
| `event_id` | `id` | prefixed `eonet:` |
| `event_type` | `categories[0].id` | `wildfires→WILDFIRE`, `severeStorms→STORM`, `volcanoes→VOLCANO`, `floods→FLOOD`, `earthquakes→EARTHQUAKE`; else `OTHER` |
| `title` | `title` | |
| `description` | `description` | often `null` |
| `geometry` | `geometry[]` | **a list** — one entry per observation over time; latest by `date` is the current position, earlier entries are track history |
| `effective_at` | `geometry[0].date` | already `Z`-suffixed |
| `ends_at` | `closed` | `null` means still open |
| `official` | `true` | authority `OFFICIAL` |
| `source.source_url` | `sources[0].url` | may point to a third-party incident system (e.g. IRWIN) |

`geometry[].magnitudeValue` / `magnitudeUnit` are per-category (acres, NM, …) and
are **not** comparable across event types.

### 3.4 Cross-source dedup

Phase 3 concern, recorded here because it constrains the schema: the same
earthquake appears in all three feeds. The plan forbids deleting conflicts.
Dedup keys available today — USGS `properties.ids`, GDACS `glide`, EONET
`sources[].id` — are not sufficient on their own, so the intended handoff is: module
04 emits **all** records with an authority-priority hint, and module 05 resolves.
**Open question Q4.**

---

## 4. `RouteCandidate` ← openrouteservice — NOT VERIFIED

No fixture exists: `ORS_API_KEY` is unset, so the provider has never been called.
The mapping below is from documentation only and **must be re-verified against a
real response** before Phase 4 is accepted.

| Canonical | Provider | Confidence |
| --- | --- | --- |
| `provider_route_id` | not supplied — adapter must synthesise | documented |
| `geometry` | `features[].geometry` (LineString) | documented |
| `distance_m` | `features[].properties.summary.distance` | documented |
| `duration_seconds` | `features[].properties.summary.duration` | documented |
| `segments` | `features[].properties.segments[]` | documented |
| `transfers` | constant `0` for road modes | derived |
| `label` | adapter-assigned | derived |
| `exposure`, `risk_level` | **not module 04** | owned by คน 5/6 |

`exposure` and `risk_level` are in the canonical shape but module 04 must never
populate them — the mission statement forbids this module from selecting or scoring
a recommendation.

---

## 5. `TransportStatus` ← GTFS / Amadeus — NOT VERIFIED

No feed region has been approved, and no Amadeus production credential exists.
Both capabilities are unavailable at Phase 0, so no mapping is asserted. The one
rule already fixed by the contract: `status = ON_TIME` requires positive real-time
evidence. Absence of an alert is `UNKNOWN`, never `ON_TIME`.

---

## 6. `SourceProvenance` and `DataQuality` — every record

Module 04 populates these on **every** emitted record. They are the module's main
contribution to safety, so they are not optional.

| `SourceProvenance` | Source |
| --- | --- |
| `provider` | registry id from `providers.yaml` |
| `provider_record_id` | provider's own id |
| `authority` | `OFFICIAL` \| `INTERGOVERNMENTAL` \| `LICENSED_PROVIDER` from the registry |
| `source_url` | deep link to the provider's own record |
| `license` | registry `license.spdx_or_name` |
| `observed_at` | **provider's observation time, or `null`** |
| `published_at` | provider's publish time, or `null` |
| `fetched_at` | adapter wall clock at response receipt |
| `expires_at` | `fetched_at` + registry cache TTL |
| `content_hash` | sha256 of the normalised record |
| `schema_version` | `1.0.0` |

> `observed_at` must be `null` when the provider gives no observation time, with a
> quality flag set. Open-Meteo forecast has no observation time at all — it is model
> output. Copying `fetched_at` into `observed_at` would make model output look like
> a measurement, which is exactly the failure the contract calls out.

`DataQuality.status` follows the freshness table in
`00_SHARED_PROJECT_CONTEXT.md` § 10 — the TTLs in `providers.yaml` were chosen to
match it (severe alert 5 min, disaster 10 min, current weather 15 min, hourly
forecast 60 min, GTFS-RT 90 s, route 6 h).

`score` is **not** implemented in Phase 0/1. It needs a versioned formula agreed
with คน 5 — **open question Q5** — and the contract forbids using a single score to
hide flags.

---

## 7. Open questions — need sign-off

| # | Question | Needs | Blocks |
| --- | --- | --- | --- |
| Q1 | Keep Open-Meteo `feature_code` (PPLC/PPLA…) on `LocationRef` for disambiguating same-name places? | คน 5 | Phase 2 |
| Q2 | Who derives `severity`? Module 04 emits raw provider magnitude/alert level, or maps to the `Severity` enum itself? | คน 5 + คน 6 | Phase 2, 3 |
| Q3 | For USGS/GDACS, does `severity` follow physical magnitude (`mag`, `severitydata.severity`) or impact alert (`alert`, `alertlevel`)? They disagree often. | คน 6 | Phase 3 |
| Q4 | Dedup contract: module 04 emits all duplicates + authority hint and module 05 resolves — confirm? | คน 5 | Phase 3 |
| Q5 | `DataQuality.score` formula and weights, plus its version string | คน 5 | Phase 2 |
| Q6 | Which feature fields does the risk model actually require, so adapters do not drop them? | คน 6 | Phase 2 |

Until each is answered, the adapter keeps the provider's raw value in a typed field
and sets the canonical field to `null` with an `INFERRED` or `INCOMPLETE` flag,
rather than guessing. Per `00_API_AND_DATA_CONTRACTS.md` § intro, none of these may
be settled in chat alone — the answer lands in the JSON Schema with consumer tests.
