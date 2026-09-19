# SafetyTravel Assistant (travel-safety-ai)

เว็บแอปช่วยคนเดินทางตอบคำถามเดียว: **"ทริปนี้ไปได้ไหม ปลอดภัยแค่ไหน ถ้าไม่ปลอดภัยควรทำยังไง"**
ดึงอากาศ / ขนส่ง / ภัยพิบัติ / เส้นทางปิด จากแหล่งจริง แล้วสรุปเป็น 1 ใน 4 คำตอบ
🟢 `NORMAL` · 🟡 `CHANGE_ROUTE` · 🟠 `DELAY` · 🔴 `AVOID` พร้อมเหตุผลและแหล่งที่มา

> ภาพรวมแบบภาษาคน + หน้าจอทุกหน้า + ใครทำอะไร อยู่ในห้อง Discord `📖│project-summary`
> แผนฉบับเต็มอยู่ใน [`IMPLEMENTATION_PLANS/`](IMPLEMENTATION_PLANS/README.md)

## ทีม 8 คน = 8 module

| คน | โฟลเดอร์ | Discord | แผน |
|---|---|---|---|
| 1 | `apps/web/` | `01-web` | [01](IMPLEMENTATION_PLANS/01_WEB_APP_IMPLEMENTATION.md) |
| 2 | `services/api/` + `packages/contracts/` | `02-api` | [02](IMPLEMENTATION_PLANS/02_API_BACKEND_IMPLEMENTATION.md) |
| 3 | `services/agent/` | `03-agent` | [03](IMPLEMENTATION_PLANS/03_TRAVEL_AI_AGENT_IMPLEMENTATION.md) |
| 4 | `services/external-data/` | `04-external-data` | [04](IMPLEMENTATION_PLANS/04_EXTERNAL_DATA_SERVICES_IMPLEMENTATION.md) |
| 5 | `services/data-integration/` | `05-data-integration` | [05](IMPLEMENTATION_PLANS/05_DATA_INTEGRATION_IMPLEMENTATION.md) |
| 6 | `services/risk-knowledge/` | `06-risk-knowledge` | [06](IMPLEMENTATION_PLANS/06_RISK_KNOWLEDGE_SERVICES_IMPLEMENTATION.md) |
| 7 | `services/decision-engine/` | `07-decision-engine` | [07](IMPLEMENTATION_PLANS/07_DECISION_LLM_ENGINE_IMPLEMENTATION.md) |
| 8 | `services/recommendation/` | `08-recommendation` | [08](IMPLEMENTATION_PLANS/08_RECOMMENDATION_FEEDBACK_IMPLEMENTATION.md) |

ใครรอใคร: ![team dependency](docs/diagrams/team-dependency.png)

## โครงสร้าง repo

```text
apps/web/                 หน้าเว็บ (คน 1)
services/<module>/        service ละ 1 โฟลเดอร์ (คน 2–8) — แต่ละอันมี Dockerfile, README, tests ของตัวเอง
packages/contracts/       แบบฟอร์มกลาง openapi/ jsonschema/ generated/ (คน 2 maintain, lead รีวิว)
packages/python-common/   observability/error envelope ที่ Python service ใช้ร่วมกัน
packages/ts-config/       tsconfig/eslint/tailwind preset (คน 1)
infra/                    postgres init, keycloak realm, qdrant, otel, prometheus, grafana
ops/discord/              บอท Discord + config ทีม + คู่มือ (ดู ops/discord/README.md)
ops/scripts/ ops/runbooks/
tests/contract|integration|e2e
docs/adr/ docs/api/ docs/diagrams/ docs/handoffs/ docs/acceptance/
assets/                   ภาพ UI ต้นแบบ (อ่านอย่างเดียว)
IMPLEMENTATION_PLANS/     แผนของทุกคน + กติกา
compose.yaml              โครงจริงของระบบ (profile core พร้อมใช้, app เจ้าของเพิ่มเอง)
compose.dev.yaml          override สำหรับพัฒนา (host port, hot reload)
.env.example              ชื่อค่าตั้งทั้งหมด (ห้าม commit .env)
```

ทุกโฟลเดอร์มี `README.md` บอกเจ้าของและสิ่งที่ควรอยู่ในนั้น

## เริ่มทำงาน (ทุกคน)

```bash
git clone https://github.com/PROxTAE/travel-safety-ai.git
cd travel-safety-ai
cp .env.example .env            # PowerShell: Copy-Item .env.example .env   แล้วเติมค่า required
docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait
docker compose ps               # postgres redis qdrant keycloak ต้อง healthy
```

แล้วแตก branch จาก `main` ตามใบงานในห้อง Discord ของตัวเอง:

```bash
git switch main && git pull --ff-only origin main
git switch -c <type>/<NN>-<short-kebab>      # เช่น feat/04-weather-adapter · type: feat|fix|test|docs|refactor|chore|contract|infra
```

คู่มือ Docker ฉบับละเอียด (ติดตั้ง → รัน → เทส → ส่งงาน) ปักหมุดอยู่ในห้อง Discord ของแต่ละคน

## กติกาที่บังคับ (ย่อจาก [`00_GIT_DOCKER_DELIVERY_RULES.md`](IMPLEMENTATION_PLANS/00_GIT_DOCKER_DELIVERY_RULES.md))

1. **ห้าม push ตรงเข้า `main`** — ทุกงานผ่าน PR + approve ≥ 1 (auth/emergency/policy/schema/migration ต้อง 2 คนรวม lead) · squash merge เท่านั้น
2. Branch `<type>/<NN>-<desc>` เท่านั้น บอทใช้เลข `NN` หา role เจ้าของ · PR ชื่อ `[MNN] ...` ใช้ template ให้ครบ · PR เล็ก < 400 บรรทัด
3. **runtime ห้ามมี mock / hard-coded current data** — provider ล่มต้องตอบ `degraded` / `unavailable` พร้อมเวลาอัปเดต
4. แตะ `packages/contracts/` หรือ `00_API_AND_DATA_CONTRACTS.md` → คุยใน `#api-contracts` ก่อน ต้องมี lead รีวิว
5. ห้าม commit `.env`, secret, PII, `node_modules`, `.venv`, ร่องรอย AI (`CLAUDE.md`, `.cursor/`, `Co-Authored-By`)
6. ส่งงาน: กรอก [`10_WORK_COMPLETION_REPORT_TEMPLATE.md`](IMPLEMENTATION_PLANS/10_WORK_COMPLETION_REPORT_TEMPLATE.md) → `docs/handoffs/MNN-<feature>.md` แนบใน PR

## บอทช่วยอะไร

GitHub Actions ใน `.github/workflows/discord-*.yml` แจ้ง Discord อัตโนมัติ: PR เปิด/approve/merge → `#pull-requests` · CI แดง → `#ci-status` · conflict กับ main → `#merge-conflicts` · แตะ contract → `#api-contracts` @everyone
รายละเอียดและวิธีตั้งค่า: [`ops/discord/README.md`](ops/discord/README.md)
