# `services/agent/`

**เจ้าของ:** คนที่ 3 · 03-agent

LangGraph orchestration ที่รับ `TravelRequest` ที่ normalized แล้ว วาง execution plan ตาม intent เรียก
tools ที่อนุมัติไปยัง module 04–08 ด้วย budget/timeout/cancellation ที่ชัดเจน และคืนผลที่ trace กลับไปหา
evidence ได้ — agent เองไม่ตัดสิน safety/action

อ่านแผน: [`IMPLEMENTATION_PLANS/03_TRAVEL_AI_AGENT_IMPLEMENTATION.md`](../../IMPLEMENTATION_PLANS/03_TRAVEL_AI_AGENT_IMPLEMENTATION.md)

## สถานะ

Phase 0–3 เสร็จและ verify แล้ว (171 unit tests, `ruff`, `mypy --strict` ผ่านทั้งหมด) Phase 4 เสร็จ
เฉพาะส่วนที่ไม่ต้องพึ่ง contract ที่ยังไม่ publish (evidence retry/escalate loop) Phase 5–7
**ยังไม่เสร็จ และบางส่วนทำต่อจาก `services/agent/` เพียงลำพังไม่ได้** เพราะ module 04/07/08
ยังไม่ publish OpenAPI contract ของตัวเอง — รายละเอียดเต็มที่
[`docs/handoffs/M03-travel-agent.md`](docs/handoffs/M03-travel-agent.md)

## Runtime

Graph ที่ compile แล้วมีครบทั้ง 13 node ตาม `docs/diagrams/agent-state.md` §2 (รวม `emergency_shortcut`
จาก Phase 2) 7 node ที่ต้องเรียก Module 04/07/08 (`fetch_external_data`, `integrate_data`,
`build_evidence`, `degraded_or_escalate`, `make_decision`, `format_recommendation`,
`emergency_shortcut`) ยัง raise `NodeNotImplementedError` โดยตั้งใจ — จบเป็น `FAILED`/`INTERNAL_ERROR`
แทนที่จะเดาผล ไม่มี fake recommendation `validate_evidence` มี logic จริงแล้ว (Phase 4) แต่ยังไม่มีทาง
เข้าถึงได้จริงเพราะ `build_evidence` ยัง block อยู่ ทุก run วันนี้จะจบที่ `FAILED` ที่
`fetch_external_data`/`emergency_shortcut`, `NEEDS_INPUT` (ถ้า origin/destination ยังไม่ confirm),
หรือ `CANCELLED` เท่านั้น

Intent classification (Phase 2) ใช้ deterministic keyword rules ก่อนเสมอ (`app/intent/rules.py`,
รายละเอียดที่ [`docs/intent-and-required-fields.md`](docs/intent-and-required-fields.md)) และมี LLM
structured-output fallback สำหรับข้อความกำกวม (`LLM_ENABLED=true` + `OPENAI_API_KEY`) — ยังไม่เคยรัน
กับ model จริง เพราะไม่มี API key ในสภาพแวดล้อมที่พัฒนา มี client จริงและ contract-tested (respx) ให้
module 05 (`data_integration.create_snapshot@1`) และ module 06
(`risk_knowledge.build_evidence_package@1`) แล้ว (`app/tools/`) — module 04/07/08 ยังไม่มี client
เพราะไม่มี OpenAPI contract ให้ generate

Endpoints:

- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- `POST /internal/v1/runs`
- `GET /internal/v1/runs/{id}`
- `POST /internal/v1/runs/{id}/resume`
- `POST /internal/v1/runs/{id}/cancel`

`POST /internal/v1/runs` รัน graph **แบบ synchronous ในคำขอเดียว** (ยังไม่มี worker/queue) ดู
รายละเอียดและข้อจำกัดของแต่ละ endpoint ที่ docstring ของ [`app/api/internal.py`](app/api/internal.py)

ในโหมด development internal authentication เป็น optional โหมด production ต้องมี
`INTERNAL_SERVICE_TOKEN` ไม่งั้น readiness จะเป็น `not_ready` เสมอ ถ้าไม่ตั้ง `DATABASE_URL`/`REDIS_URL`
service ยังเปิดได้ (checkpoint/progress publishing จะถูกข้าม ไม่ crash) แต่ readiness จะรายงานตามจริง

## Config

ค่า budget/timeout ทั้งหมดอยู่ใน [`app/settings.py`](app/settings.py) (`MAX_AGENT_STEPS`,
`MAX_TOOL_CALLS`, `AGENT_TOTAL_TIMEOUT_SECONDS`, ...) พร้อม default ตามแผน

## รัน

```powershell
docker compose build agent
docker compose -f compose.yaml -f compose.dev.yaml --profile app up agent
```

(ยังไม่มี entry ของ `agent` ใน `compose.yaml`/`compose.dev.yaml` ที่ repo root — ต้องเพิ่มตามตัวอย่าง
ท้ายไฟล์ `compose.yaml` ก่อน)

Test:

```powershell
cd services/agent
uv sync --frozen
uv run pytest -m "not integration"          # unit — ไม่ต้องมี Docker
uv run pytest                                # + integration ถ้ามี Docker (PostgreSQL/Redis จริงผ่าน Testcontainers)
```
