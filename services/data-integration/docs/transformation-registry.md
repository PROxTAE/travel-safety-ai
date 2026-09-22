# Transformation registry (proposal 0.1.0)

Lineage will store `{transform_id, version, input_hash, output_hash, parameters}` per transformed field. These are specifications for Phase 2, not claims that code already implements them. A version changes whenever a rule, accepted input or rounding rule changes. Unknown units, time zones, or topology-changing repairs quarantine the record instead of guessing.

| ID / version | Input → output | Rule and rounding |
| --- | --- | --- |
| `unit.temperature/0.1.0` | °F/°C → °C | `(F−32)×5/9`; calculate without intermediate rounding; serialize to 0.01 °C using decimal half-even. |
| `unit.wind/0.1.0` | mph, m/s, km/h → km/h | Factors 1.609344, 3.6, 1; decimal half-even at 0.01 km/h. |
| `unit.precipitation/0.1.0` | inch/mm → mm | 25.4 mm/inch; decimal half-even at 0.01 mm. |
| `unit.distance/0.1.0` | mile, km, m → m | Factors 1609.344, 1000, 1; decimal half-even at 0.01 m. |
| `unit.duration/0.1.0` | hour, minute, second → second | Factors 3600, 60, 1; decimal half-even at 0.001 s. |
| `time.utc/0.1.0` | offset-aware provider timestamp → UTC timestamp | Preserve instant and original offset/name in lineage. No rounding beyond input precision. Reject naive or ambiguous local time without source zone/fold. Do not map `fetched_at` to `observed_at`. |
| `severity.provider/0.1.0` | provider measurement/code → Severity | See `severity-and-authority.md`; unmapped values become UNKNOWN with flag. No numeric averaging or rounding. |
| `geometry.safe/0.1.0` | GeoJSON geometry → EPSG:4326 valid geometry | Validate lon/lat ranges and type; keep original coordinates when valid. Remove only consecutive duplicate vertices if topology unchanged; otherwise quarantine for review. No coordinate rounding before spatial join; exported precision must be versioned. |

## Hash and checksum convention

For a transform input/output object, encode JSON as UTF-8 with lexicographically sorted keys, compact separators, `ensure_ascii=false`, finite numbers only, and UTC timestamps with an explicit `Z`. Hash the bytes with SHA-256, prefix `sha256:`. The *definition checksum* is SHA-256 over the same canonical encoding of `{id, version, rule, parameters, rounding}`. The serialized transform registry must be frozen before implementation; this draft checksum convention needs a cross-language parity test with module 06 before 1.0.0. Do not include fetch time or generated snapshot ID in a deterministic content hash unless that value is part of the input evidence.
