# `services/external-data/`

**เจ้าของ:** คนที่ 4 · 04-external-data · host port `8002`

Adapter ไป provider จริง (geocoding / weather / route / disaster / transport) +
provenance, cache, quota

แผน: [`IMPLEMENTATION_PLANS/04_EXTERNAL_DATA_SERVICES_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/04_EXTERNAL_DATA_SERVICES_IMPLEMENTATION.md)

โมดูลนี้ **ไม่** เลือก final recommendation และ **ไม่** ให้คะแนนความเสี่ยง หน้าที่คือ
ดึงข้อมูลจริง แปลงเป็น canonical contract แล้วแนบ provenance/freshness/quality ให้ครบ
การตัดสินใจเป็นของโมดูล 05/06/07

## สถานะ

| Phase | สถานะ |
| --- | --- |
| 0 — Provider governance | ✅ |
| 1 — Service foundation | ✅ |
| 2 — Geocoding + weather | ✅ |
| 3–7 | ⬜ ยังไม่เริ่ม |

## Endpoint

| Method | Path | สถานะ |
| --- | --- | --- |
| GET | `/health/live` · `/health/ready` · `/metrics` | ✅ ไม่ต้อง auth |
| GET | `/internal/v1/providers/health` | ✅ |
| POST | `/internal/v1/geocode/search` | ✅ |
| POST | `/internal/v1/weather/query` | ✅ |
| POST | `/internal/v1/disasters/query` | ⬜ Phase 3 |
| POST | `/internal/v1/routes/query` · `/places/nearby` | ⬜ Phase 4 (ไม่มี key) |
| POST | `/internal/v1/transport/query` | ⬜ Phase 5 |
| POST | `/internal/v1/context/query` | ⬜ Phase 6 |

ทุก endpoint ใต้ `/internal/v1` ต้องมี `Authorization: Bearer $INTERNAL_SERVICE_TOKEN`

## เอกสาร

| ไฟล์ | เนื้อหา |
| --- | --- |
| [`config/providers.yaml`](config/providers.yaml) | provider registry ที่ runtime อ่านจริง |
| [`docs/provider-registry.md`](docs/provider-registry.md) | matrix: coverage, licence, quota, attribution, retention, health URL |
| [`docs/canonical-field-mapping.md`](docs/canonical-field-mapping.md) | mapping ราย field จาก provider → canonical contract + คำถามที่ต้อง sign-off |
| [`docs/coverage-and-degraded-ux.md`](docs/coverage-and-degraded-ux.md) | capability ที่ใช้ไม่ได้ และ UI ต้องบอกผู้ใช้ยังไง |
| [`docs/lead-approval-checklist.md`](docs/lead-approval-checklist.md) | สิ่งที่ Team Lead ต้องอนุมัติ/มอบหมาย |
| [`tests/fixtures/real-sanitized/`](tests/fixtures/real-sanitized/) | response จริงที่ capture มาแล้ว sanitize — ใช้ใน test เท่านั้น |

## Capability ที่ใช้ได้ตอนนี้

| Capability | Provider | สถานะ |
| --- | --- | --- |
| Geocoding | Open-Meteo Geocoding | ✅ `ACTIVE` |
| Weather | Open-Meteo Forecast | ✅ `ACTIVE` |
| Earthquake | USGS | ✅ `ACTIVE` |
| Multi-hazard | GDACS | ✅ `ACTIVE` |
| Natural events | NASA EONET v3 | ✅ `ACTIVE` |
| Road route | openrouteservice | ❌ ไม่มี `ORS_API_KEY` |
| Emergency POI | openrouteservice POIs | ❌ ไม่มี `ORS_API_KEY` |
| Flight | Amadeus production | ❌ ไม่มี credential |
| Transit realtime | agency GTFS-RT | ❌ Lead ยังไม่เลือก region |

capability ที่ไม่พร้อมจะคืน `UNSUPPORTED_COVERAGE` ตรง ๆ **ห้ามคืน empty success
หรือข้อมูลตัวอย่างแทน** — ดู [`docs/coverage-and-degraded-ux.md`](docs/coverage-and-degraded-ux.md)

## Capture fixture ใหม่

```bash
# รันจาก repo root
python services/external-data/scripts/capture_fixtures.py
```

เรียก provider จริงเจ้าละ 1 ครั้ง ตรวจว่าไม่มี credential ปนใน payload แล้วเขียนทับ
fixture พร้อม regenerate `MANIFEST.json` ใช้ `--only <fixture_id>` เพื่อ capture
เจ้าเดียวโดยไม่แตะ timestamp ของเจ้าอื่น

## Test

```bash
uv run pytest              # ไม่รวม canary
uv run pytest -m canary    # ยิง provider จริง — ใช้ตรวจ schema drift
```
