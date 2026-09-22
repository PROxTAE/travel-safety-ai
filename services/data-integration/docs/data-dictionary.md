# Canonical input data dictionary (draft 0.1.0)

Source of truth for the received shapes: `services/external-data/app/domain/{records,canonical}.py` at the captured commit. The combined endpoint returns `data.weather`, `data.disaster_events`, `data.routes`, `data.places`, `data.duplicate_groups`, `data.capabilities`, `data.provider_health` and `meta.degraded_services`. It does **not** return transport records or a ready-made corridor. A missing capability is different from a successful empty result. No value in this document authorizes filling unknown observations with zero.

Legend: `?` means nullable; `[]` means list; time values are offset-aware ISO 8601. `source` and `quality` are mandatory on every record. GeoJSON coordinates are `[longitude, latitude]` in EPSG:4326. Measurement units are canonical output units, not necessarily upstream units.

| Record | Fields: type and unit | Null and time meaning | Current provider |
| --- | --- | --- | --- |
| WeatherForecastPoint | `id` string; `location` GeoPoint; `valid_at` datetime; `temperature_c`, `apparent_temperature_c` float? °C; `precipitation_mm` float? mm; `precipitation_probability` int? 0–100%; `snowfall_cm` float? cm; `wind_speed_kmh`, `wind_gust_kmh` float? km/h; `visibility_m` float? m; `weather_code` int? WMO code; `severity` Severity; `eta_offset_seconds` int? s; `sample_id` string?; `quality` DataQuality; `source` SourceProvenance | `valid_at` is forecast target time, never observation time. Null measurement means provider did not supply it. Null ETA offset means no ETA match. `severity=UNKNOWN` until mapping is approved. | Open-Meteo |
| DisasterEvent | `event_id` string; `event_type` EventType; `title` string; `description` string?; `severity` Severity; `geometry` GeoPoint; `effective_at` datetime; `ends_at` datetime?; `instruction` string?; `official` bool; `magnitude` float?; `magnitude_unit` string?; `depth_km` float? km; `alert_level` string?; `tsunami` bool?; `cross_reference_ids` string[]; `reporting_networks` string[]; `episode_id` string?; `quality`; `source` | `effective_at` is event/effect start; `ends_at=null` means unknown end, not ongoing forever. Null measurements and alert level mean unavailable. Empty cross references mean no known match. | USGS, GDACS, EONET |
| RouteCandidate | `route_id` string; `provider_route_id` string?; `label` RouteLabel; `mode` TravelMode; `geometry` GeoLineString; `segments` RouteSegment[]; `distance_m` float m; `duration_seconds` float s; `transfers` int; `exposure` null; `risk_level` UNKNOWN; `bbox` float[4]?; `quality`; `source` | Null exposure is intentional: module 04 has not performed hazard intersection. Null provider ID or bbox means unavailable. `risk_level=UNKNOWN` is not LOW. | openrouteservice when credential configured |
| RouteSegment | `segment_id` string; `mode` TravelMode; `from_name`, `to_name` string?; `geometry` GeoLineString?; `distance_m` float m; `duration_seconds` float s; `departure_time`, `arrival_time` datetime?; `transport_status_id` string?; `steps` RouteStep[] | Null times/status mean provider did not provide schedule or real-time status. | openrouteservice |
| RouteStep | `distance_m` float m; `duration_seconds` float s; `instruction`, `street_name` string?; `way_points` int[2]? | Null instruction/street/index range means absent from provider. | openrouteservice |
| EmergencyPlace | `place_id` string; `place_type` PlaceType; `name` string?; `location` GeoPoint; `distance_m` float? straight-line m; `address`, `phone`, `website`, `opening_hours`, `provider_category` string?; `quality`; `source` | Null means OSM lacks a value; phone/hours are not an official directory guarantee. | openrouteservice/OSM when credential configured |
| GeoPoint / GeoLineString | `type` literal; `coordinates` `[lon,lat]` or list of those pairs | Coordinates required and range checked. They carry no timestamp. | All spatial providers |

## Shared metadata on each record

| Field | Type | Semantics and null |
| --- | --- | --- |
| `source.source_id`, `provider`, `authority`, `schema_version` | string, string, SourceAuthority, SemVer | Required source identity and declared trust class. |
| `source.provider_record_id`, `source.source_url`, `source.license`, `source.content_hash` | string? | Null means provider did not expose that metadata. `content_hash` is not a source event time. |
| `source.observed_at` | datetime? | Time an underlying observation was made; forecast records normally have null. Never substitute `fetched_at`. |
| `source.published_at` | datetime? | Provider publication/update time; null if unknown. It does not replace event effective time. |
| `source.fetched_at` | datetime | When module 04 fetched the payload; used to measure cache age, not to assert observation time. |
| `source.expires_at` | datetime? | Cache validity limit; null means unknown, not indefinitely fresh. |
| `quality.status`, `quality.flags` | DataStatus, QualityFlag[] | Required status and explicit evidence gaps. |
| `quality.score`, `quality.coverage`, `quality.completeness` | float? in [0,1] | Null means unscored/unknown; zero is an actual score. Score requires `score_version`. |
| `quality.score_version`, `quality.freshness_seconds` | string?, int? s | Null score version only with null score; null freshness means no reliable age. |
| `quality.conflicts`, `quality.notes` | string[] | Supporting reasons; empty is no recorded reason, not proof of agreement. |

`valid_at` applies to weather forecasts; `effective_at`/`ends_at` apply to disaster events; route segment departure/arrival are travel schedule times. Keep all five provenance times separate in storage and lineage. `TransportStatus` exists in the shared contract but is not emitted by the combined module 04 endpoint; its field mapping remains open.
