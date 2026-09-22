# Intent classification and critical fields — Module 03 (Phase 0 item 4 / Phase 2)

เอกสารนี้ปิดช่องที่ [`agent-state.md`](diagrams/agent-state.md) §8 ทิ้งไว้ตั้งแต่ Phase 0
("รายการ critical missing fields ต่อ intent และกฎ classifier จะอยู่ในเอกสารแยก") `Intent` เป็น
taxonomy ภายใน agent เท่านั้น (ไม่อยู่ใน `00_API_AND_DATA_CONTRACTS.md`) ดังนั้นการนิยาม
required-field matrix นี้เป็นการตัดสินใจของ Module 03 เอง ตามที่แผน Phase 0 มอบหมายไว้

**โค้ด:** `app/intent/rules.py` (deterministic), `app/intent/required_fields.py` (matrix),
`app/intent/llm_classifier.py` (LLM fallback สำหรับข้อความกำกวม)

## 1. ลำดับการตัดสินใจ (deterministic ก่อนเสมอ)

`classify_intent` ตัดสินตามลำดับนี้ — **ข้อบนสุดที่ match ชนะ**, ไม่ผ่าน LLM เลยยกเว้นข้อสุดท้าย:

1. **`EMERGENCY`** — `question` มีคำในรายการ emergency keyword (§3) ไม่ว่าบริบทการสนทนาจะเป็นอย่างไร
   เหตุผล: ความปลอดภัยของผู้ใช้สำคัญกว่าความแม่นยำของ intent อื่น ต้องเร็วและ deterministic
   ห้ามรอ LLM
2. **`FOLLOW_UP`** — สัญญาณเชิงโครงสร้าง (ไม่ใช่ข้อความ): `travel_request.conversation_id` ไม่ใช่
   `null` **และ** `input.approved_context_refs` ไม่ว่าง (module 02 ส่งมาว่ามี context เดิมให้ใช้ต่อ)
3. **`CHECK_SAFETY`** — `question` มีคำในรายการ safety keyword (§3) และยังไม่เข้าเงื่อนไขข้อ 1–2
4. **`PLAN_TRIP`** — `question` เป็น `null` (ไม่มีคำถามเลย แปลว่าเป็นการสร้างทริปใหม่ตรงๆ)
5. **`ASK_INFORMATION`** (deterministic fallback) หรือ **LLM classifier** (ถ้า `LLM_ENABLED=true`) —
   `question` มีข้อความแต่ไม่ตรงกฎไหนเลยข้างต้น ถือว่ากำกวม ถ้าไม่เปิด LLM ให้ default เป็น
   `ASK_INFORMATION` (ตัวเลือกที่ critical-field เข้มงวดน้อยที่สุด ไม่เดาไปทาง `CHECK_SAFETY`/
   `EMERGENCY` โดยไม่มีสัญญาณ)

ข้อ 1–4 เป็น "simple known intent" ตาม Stack section ของแผน ("ใช้ deterministic classifier ก่อน")
มีแค่ข้อ 5 เท่านั้นที่เรียก LLM และเรียกเฉพาะตอนกำกวมจริง

## 2. Critical fields ต่อ intent

`check_required_fields` เช็คตามตารางนี้ ทุก intent ต้อง `origin.confirmed_by_user` และ
`destination.confirmed_by_user` เป็น `true` ก่อนเสมอ (กฎเดียวที่ Phase 1 บังคับใช้แล้ว, มาจาก
`00_API_AND_DATA_CONTRACTS.md` §3.1) ตารางนี้เพิ่มกฎเฉพาะ intent

| Intent | เพิ่มจากกฎร่วม | เหตุผล |
| --- | --- | --- |
| `PLAN_TRIP` | ไม่มี (กฎร่วมพอ) | มีข้อมูลทริปครบจาก `TravelRequest` อยู่แล้วตาม type |
| `CHECK_SAFETY` | ไม่มี | คำถามเรื่องเส้นทาง/เวลาที่ประกาศไว้แล้วใน request |
| `ASK_INFORMATION` | ไม่มี | คำถามทั่วไปเกี่ยวกับทริปที่ประกาศไว้แล้ว |
| `FOLLOW_UP` | `conversation_id` ต้องไม่ null (ถ้า classify เป็น FOLLOW_UP แต่ไม่มี conversation_id แปลว่า classifier ผิดพลาด ให้ถือเป็น missing field `conversation_id` ไม่ใช่ bug เงียบ) | ป้องกัน state ที่เข้ากันไม่ได้ (FOLLOW_UP ต้องมี thread ให้ตามต่อ) |
| `EMERGENCY` | ไม่มี field เพิ่ม — เส้นทางลัดไปข้อมูลฉุกเฉินใช้ `origin` อย่างเดียวก็พอ | ตามแผน "ส่งทางลัดไปข้อมูลฉุกเฉินแต่ไม่ auto-contact" ไม่ควรบล็อกด้วยการขอข้อมูลเพิ่มตอนฉุกเฉิน |

ยังไม่มีกฎเพิ่มเติมสำหรับ `travel_modes`/`preferences` เพราะ type ของ `TravelRequest`
(`travel_modes: list[TravelMode] = Field(min_length=1)`) บังคับว่ามีอย่างน้อย 1 mode อยู่แล้ว —
ไม่มีทางเป็น "missing field" ที่ต้องเช็คซ้ำ

## 3. Keyword list (deterministic, ไม่ใช่ NLP)

Case-insensitive substring match บน `question` ที่ normalize แล้ว (ดู §4) รายการนี้จงใจสั้นและ
ตรงไปตรงมา — ไม่ใช่ NLU ถ้าคำไม่อยู่ในรายการ ให้ตกไปเป็นกำกวม (ข้อ 5) แทนที่จะเดา

**Emergency** (TH): ฉุกเฉิน, ช่วยด้วย, ช่วยฉันด้วย, อุบัติเหตุ, บาดเจ็บ, เลือดออก, ติดอยู่, ตายแล้ว,
โทรตำรวจ, โทรรถพยาบาล, หายใจไม่ออก, ถูกทำร้าย
**Emergency** (EN): emergency, help me, sos, accident, injured, injury, bleeding, trapped, dying,
can't breathe, cannot breathe, call police, call an ambulance, attacked

**Check safety** (TH): ปลอดภัย, อันตราย, เสี่ยง, น้ำท่วม, พายุ, แผ่นดินไหว, เตือนภัย, ปิดถนน, ภัยพิบัติ
**Check safety** (EN): safe, safety, dangerous, danger, risk, risky, flood, storm, earthquake,
warning, alert, closure, closed road, hazard

## 4. Normalization และการป้องกัน prompt injection

- `question` normalize ก่อนเช็คคำ: lowercase, ตัด control character (`\x00`–`\x1f` ยกเว้น
  whitespace ปกติ), ตัดช่องว่างซ้ำ — ทำใน `app/intent/rules.py::_normalize`
- Keyword matching เป็น substring scan ล้วนๆ ไม่มีการ execute หรือตีความคำสั่งใดๆ จากข้อความ จึง
  ปลอดภัยจาก injection โดยโครงสร้าง
- LLM classifier (ข้อ 5) คือจุดเดียวที่มีความเสี่ยง: system prompt คงที่ ไม่ประกอบจาก input ของ
  ผู้ใช้ ผลลัพธ์บังคับเป็น structured output (enum เดียวจาก 5 ค่า `Intent`) ทำให้โมเดลไม่มีช่องให้
  "ทำ" อะไรนอกจากเลือก label — ดู `app/intent/llm_classifier.py`
- Node นี้รันก่อน `fetch_external_data` เสมอ (ดู `docs/diagrams/agent-state.md` §2) จึงไม่มีทางที่
  provider/RAG text จะหลุดเข้ามาใน prompt ของ classifier ได้ — เป็นคุณสมบัติของลำดับ graph เอง
  ไม่ใช่การเช็ค runtime
