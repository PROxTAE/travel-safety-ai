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
| 3 — Disaster sources | ✅ USGS + GDACS + EONET + dedup + health probe |
| 4 — Routing | ⛔ ติด `ORS_API_KEY` |
| 5 — Transit/flight | ⛔ ติด credential + Lead เลือก region |
| 6–7 | ⬜ ยังไม่เริ่ม |

## Endpoint

| Method | Path | สถานะ |
| --- | --- | --- |
| GET | `/health/live` · `/health/ready` · `/metrics` | ✅ ไม่ต้อง auth |
| GET | `/internal/v1/providers/health` | ✅ |
| POST | `/internal/v1/geocode/search` | ✅ |
| POST | `/internal/v1/weather/query` | ✅ |
| POST | `/internal/v1/disasters/query` | ✅ (USGS + GDACS + EONET) |
| POST | `/internal/v1/routes/query` · `/places/nearby` | ⬜ Phase 4 (ไม่มี key) |
| POST | `/internal/v1/transport/query` | ⬜ Phase 5 |
| POST | `/internal/v1/context/query` | ⬜ Phase 6 |

ทุก endpoint ใต้ `/internal/v1` ต้องมี `Authorization: Bearer $INTERNAL_SERVICE_TOKEN`

## Health probe

ทุก `PROVIDER_HEALTH_PROBE_SECONDS` วินาที (ค่าเริ่มต้น 300, ใส่ `0` เพื่อปิด) service จะ
ยิง `health.url` ของ provider ที่ `ACTIVE` ทุกเจ้าแล้วบันทึกผลลง `provider.health`

ถ้าไม่มี probe นี้ `provider.health` จะมีข้อมูลก็ต่อเมื่อมี request จริงไปถึง provider —
provider ที่ถูกเสิร์ฟจาก cache ล้วนจะค้างที่ `UNKNOWN` ตลอด และเจ้าที่ล่มระหว่าง request
จะถือค่าเดิมที่ยังดีอยู่ไว้จนกว่าจะมีคนเรียก

provider ที่ถูกบล็อก (ไม่มี credential / Lead ยังไม่อนุมัติ) **ไม่ถูก probe** — สถานะของมัน
รู้จาก config อยู่แล้ว และการยิงไป provider ที่ยังไม่ได้รับอนุมัติคือสิ่งที่ registry gate มีไว้กัน

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
| Earthquake | USGS | ✅ `ACTIVE` + adapter |
| Multi-hazard | GDACS | ✅ `ACTIVE` + adapter |
| Natural events | NASA EONET v3 | ✅ `ACTIVE` + adapter |
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
