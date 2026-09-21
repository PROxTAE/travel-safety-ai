# Sample records from module 04

**เจ้าของ:** คน 4 (external-data) · **สำหรับ:** คน 5, คน 6 และใครก็ตามที่ต้องอ่านของที่ M04 ผลิต

ไฟล์ในโฟลเดอร์นี้คือ **record จริง** ที่ `services/external-data` ผลิตออกมา สร้างจาก response ของ provider จริงที่ capture ไว้ ยิงผ่าน adapter จริง

มีไว้ให้เริ่มเขียนโค้ดได้เลยโดย **ไม่ต้องรัน Docker ไม่ต้องมี API key ไม่ต้องรอ M04 merge อะไร**

```python
import json, pathlib
events = json.loads(
    pathlib.Path("docs/handoffs/m04-records/disaster-events.json").read_text(encoding="utf-8")
)["records"]
```

| ไฟล์ | อะไรอยู่ข้างใน |
| --- | --- |
| `disaster-events.json` | 6 เหตุการณ์ · จาก USGS, GDACS, EONET อย่างละ 2 |
| `geocode-results.json` | 3 `LocationRef` พร้อม provenance |
| `weather-forecast-points.json` | 3 จุดพยากรณ์ |
| `route-candidates.json` | 1 เส้นทาง (ตัด geometry ให้สั้นลงเพื่อให้อ่านง่าย) |
| `emergency-places.json` | 2 แห่ง — มีชื่อ 1, ไม่มีชื่อ 1 |
| `transport-statuses.json` | 2 เที่ยว — จับคู่ตารางได้ 1, ไม่ได้ 1 |

ทุกไฟล์มี `_note` อธิบายว่าทำไมถึงเลือก record ชุดนั้นมา

## นี่ไม่ใช่ contract

**`packages/contracts/jsonschema/common/` คือ contract** ไฟล์พวกนี้คือตัวอย่างว่าของจริงหน้าตาเป็นยังไง

ถ้าสองอย่างขัดกัน contract ถูก และโปรดบอกผมด้วยเพราะแปลว่ามีอะไรหลุด — มันเคยหลุดมาแล้ว 2 รอบ (issue #26)

`fetched_at` / `expires_at` ในไฟล์เป็นเวลาที่ generate เพราะงั้นจะดูเก่าเสมอ อย่าเอาไปเทียบความสด

## 5 อย่างที่จะทำให้เข้าใจผิดถ้าไม่รู้ก่อน

### 1. `UNKNOWN` ไม่ได้แปลว่าข้อมูลหาย

`severity` เป็น `UNKNOWN` ทุก record และ `risk_level` เป็น `UNKNOWN` ทุกเส้นทาง — **โดยตั้งใจ**

M04 เป็นคนหาข้อมูล ไม่ใช่คนตัดสินความเสี่ยง การแปลง magnitude 6.5 เป็น "รุนแรง" คือการตัดสิน ซึ่งเป็นงานของ M06/M07 ตัวเลขดิบอยู่ครบใน `magnitude` `magnitude_unit` `alert_level` `depth_km`

CI ของ M04 มี grep กันไว้ว่าเราจะไม่แอบเติมค่าพวกนี้เอง

### 2. `null` ไม่เท่ากับ `0`

พยากรณ์อากาศทุก field เป็น nullable `precipitation_mm: null` แปลว่า **ไม่รู้** ส่วน `0` แปลว่า **ฝนไม่ตก** สองอันนี้ต่างกันมากเวลาเอาไปตัดสินว่าควรเลื่อนเดินทางไหม

ทุกครั้งที่เป็น `null` จะมี flag ใน `quality.flags` บอกด้วย

### 3. `exposure: null` แปลว่า "ยังไม่ประเมิน" เท่านั้น

route จาก M04 ยังไม่ผ่านการตัดกับ hazard — `exposure` เป็น `null` และ contract บังคับว่า route ที่ `exposure` เป็น null ต้องมี `risk_level: UNKNOWN` ด้วย

เพราะงั้น **เป็นไปไม่ได้**ที่จะมี route ที่ยังไม่ประเมินแต่อ้างว่าเสี่ยงต่ำ ถ้าเจอแปลว่ามีบั๊ก

@06 — ส่ง hazard polygon เข้า `avoid_polygons` ของ `/internal/v1/routes/query` ได้เลย รับ GeoJSON `Polygon` / `MultiPolygon` ตรง ๆ

### 4. เหตุการณ์เดียวกันโผล่ได้หลายแหล่ง และเราไม่รวมให้

แผ่นดินไหวลูกเดียวปรากฏทั้งใน USGS และ GDACS พร้อมพิกัดและขนาดที่ต่างกันเล็กน้อย

`/internal/v1/disasters/query` คืน `duplicate_groups` มาให้ว่าอันไหนน่าจะเป็นลูกเดียวกัน แต่ **record ทุกตัวยังอยู่ครบ** — M04 ไม่ลบอะไรทิ้ง เพราะการเลือกว่าจะเชื่อแหล่งไหนเป็นงาน M05 และ M05 ตัดสินใจเรื่อง record ที่ไม่เคยได้รับไม่ได้

### 5. list ว่าง ≠ ไม่มีอะไร

`events: []` แปลว่า **ไม่มีเหตุการณ์ในเงื่อนไขที่ถาม** ถ้าติดต่อ provider ไม่ได้จะได้ error พร้อม code ไม่ใช่ list ว่าง

`places: []` แปลว่าไม่มีอะไรถูก tag ใน OpenStreetMap ในรัศมีนั้น — **ไม่ได้แปลว่าไม่มีโรงพยาบาลแถวนั้น** ห้าม render เป็น "ไม่มีความช่วยเหลือใกล้เคียง"

ถ้า capability ใช้ไม่ได้จริง ๆ จะได้ `422 UNSUPPORTED_COVERAGE` ต้อง handle แยกจาก list ว่าง

## อ่านต่อ

- **issue #20** — endpoint ทุกตัว, auth, error envelope, request shape
- `docs/handoffs/M04-external-data.md` — completion report เต็ม พร้อมข้อจำกัดที่รู้อยู่ทั้งหมด
- `packages/contracts/jsonschema/common/` — contract ตัวจริง

ถามได้ตลอดครับ ถ้า shape ไหนใช้ยากบอกได้ ตอนนี้แก้ง่ายกว่าตอนต่อระบบจริงมาก
