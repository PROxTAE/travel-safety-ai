# SafetyTravel Assistant — Discord + GitHub team bot

ทีม 8 คน 8 workstream หัวหน้าคนเดียวดูแล repo, Discord, Docker และรีวิว PR
ระบบนี้รับงานซ้ำ ๆ แทนหัวหน้า: ตั้งห้อง แจกใบงาน แจ้งเตือน บังคับกติกา และช่วยรีวิว

> "บอท" ไม่ใช่โปรแกรมตัวเดียว มี 4 ส่วนแยกกัน ส่วนที่อ่านโค้ด/เทส/ตัดสินคือ AI (Claude Code) ที่ทำเมื่อหัวหน้าสั่ง
> บอท Discord เป็นแค่ตัวตน (identity) ที่ใช้สร้างห้องและโพสต์ข้อความ

| ส่วน | คืออะไร | ทำงานเมื่อไร |
|---|---|---|
| 1. ตั้งห้อง | `setup_discord.py` + `config.yaml` | หัวหน้ารันเองตอนตั้ง/แก้โครงสร้าง |
| 2. แจ้งเตือน | `.github/workflows/discord-*.yml` + webhook | อัตโนมัติทุกเหตุการณ์ PR / CI / contract / conflict |
| 3. กติกาบน GitHub | branch protection + `CODEOWNERS` + PR template | อัตโนมัติ บังคับตลอด |
| 4. ผู้ช่วยรีวิว | AI ตาม `REVIEW_PLAYBOOK.md` + `notify.py` | เมื่อหัวหน้าสั่ง |

## โครงสร้างทีม (จาก `config.yaml`)

| คน | Discord role = ห้อง | module ในชื่อ branch | โฟลเดอร์ | แผน |
|---|---|---|---|---|
| lead | `lead` | 00 (infra/chore) | `infra/ ops/ .github/ compose*.yaml` | 00_*, 09 |
| คนที่ 1 | `01-web` | 01 | `apps/web/` | 01 |
| คนที่ 2 | `02-api` | 02 | `services/api/ packages/contracts/` | 02 |
| คนที่ 3 | `03-agent` | 03 | `services/agent/` | 03 |
| คนที่ 4 | `04-external-data` | 04 | `services/external-data/` | 04 |
| คนที่ 5 | `05-data-integration` | 05 | `services/data-integration/` | 05 |
| คนที่ 6 | `06-risk-knowledge` | 06 | `services/risk-knowledge/ infra/qdrant/` | 06 |
| คนที่ 7 | `07-decision-engine` | 07 | `services/decision-engine/` | 07 |
| คนที่ 8 | `08-recommendation` | 08 | `services/recommendation/` | 08 |

Branch `feat/04-weather-adapter` → module `04` → ping `@04-external-data` และลิงก์ห้อง `#04-external-data`

แก้ mapping / เพิ่มคน / เปลี่ยน scope → แก้ `config.yaml` แล้วรัน `setup_discord.py` และ `gen_github.py` ใหม่

## เริ่มใช้งาน (หัวหน้าทำครั้งเดียว)

```bash
cd ops/discord
pip install -r requirements.txt
cp .env.example .env          # ใส่ DISCORD_BOT_TOKEN และ GUILD_ID
```

1. **ลาก role ของบอทขึ้นบนสุด** — Server Settings → Roles → ลาก `SafetyTravel Assistant` ไว้เหนือ `lead`
   (ไม่งั้นแก้สี/hoist ของ role ไม่ได้ ถึงบอทจะเป็น Administrator ก็ตาม สคริปต์จะเตือนแล้วข้าม)
2. ดูแผนก่อน แล้วค่อยรันจริง
   ```bash
   python setup_discord.py --dry-run
   python setup_discord.py
   ```
   สคริปต์รันซ้ำได้ (idempotent): ของที่มีแล้ว = `EXISTS`, ต่างจาก config = `UPDATE`, ไม่มี = `CREATE` — **ไม่ลบอะไร** เว้นแต่ใส่ `--prune` ซึ่งลบเฉพาะที่ระบุใน `retired:` ของ config
   ผลลัพธ์อยู่ที่ `out/discord-ids.json` (มี webhook URL → git-ignored)
   ```bash
   python notify.py kickoff --pin --everyone     # ประกาศภาพรวมทีม (ใครดูแลอะไร บอทแจ้งที่ไหน) ใน #announcements
   python draw.py --dry-run                      # สุ่มแจก module ให้สมาชิก (ไม่นับบอท) — ดูผลก่อน
   python draw.py --welcome                      # สุ่มจริงแบบอนิเมชันใน #role-draw + แจก role + ทักในห้องของแต่ละคน
   ```
   ```bash
   python post_summary.py --dry-run             # ภาพรวมโปรเจกต์ (summary.yaml) → #project-summary พร้อมภาพ UI ทุกหน้า
   python post_summary.py --replace             # แก้ summary.yaml แล้วโพสต์ใหม่ (ลบชุดเก่าของบอทก่อน)
   ```
   ```bash
   python post_docker_guide.py --dry-run         # คู่มือ Docker 4 ตอน (docker_guide.yaml + workstreams[].docker ใน config) ปักหมุดในห้องทุกคน
   python post_docker_guide.py                   # รันซ้ำ = แก้ข้อความเดิม (marker docker-guide:<key>:<n>)
   ```
   ```bash
   python post_assignment.py --dry-run           # แจกงาน: สรุปแผน (ดึง Mission/Phase/branch จากไฟล์แผนจริง) + แนบไฟล์แผน 8 ไฟล์ + วิธีใช้ AI + prompt พร้อมใช้
   python post_assignment.py                     # ปักหมุด 3 ข้อความ/ห้อง, รันซ้ำ = แก้ของเดิม (assignment.yaml)
   ```
   `draw.py` ใช้ member search แทน list ถ้ายังไม่เปิด Server Members Intent · `--seed N` ให้ผลซ้ำได้ · `--exclude <username>` ตัดคนออก · `--no-assign` แค่โชว์
3. Repo ทีม: https://github.com/PROxTAE/travel-safety-ai (public, `main`) — push โฟลเดอร์นี้ตาม `IMPLEMENTATION_PLANS/00_GIT_DOCKER_DELIVERY_RULES.md` §1
4. ใส่ GitHub username ทุกคนใน `config.yaml` (`github:`) — เช็กก่อนด้วย `gh api users/<ชื่อ>` (ห้ามมี `_`)
   ```bash
   python gen_github.py          # → .github/CODEOWNERS
   ```
5. ตั้ง secrets/variables + branch protection
   ```bash
   bash ops/scripts/github_setup.sh <owner>/<repo>                 # ครั้งแรก: ยังไม่บังคับ CODEOWNERS / status checks
   bash ops/scripts/github_setup.sh <owner>/<repo> --codeowners --checks "lint,typecheck,unit,contract"
   #   ↑ รันอีกรอบหลังทุกคนรับคำเชิญ collaborator แล้ว และ workflow CI มี job ชื่อเหล่านั้นแล้ว
   ```
6. ทดสอบ webhook
   ```bash
   curl -X POST -H "Content-Type: application/json" -d '{"content":"ทดสอบ webhook"}' "<URL จาก out/discord-ids.json>"
   ```

## 2. แจ้งเตือนอัตโนมัติ (GitHub Actions → webhook)

| Workflow | ห้อง | เมื่อไร | ping |
|---|---|---|---|
| `discord-pr.yml` | `#pull-requests` | PR เปิด / พร้อมรีวิว / approve / request changes / merge / ปิด (draft ไม่แจ้ง) | role ของ module จากชื่อ branch |
| `discord-contract.yml` | `#api-contracts` | PR แตะ `packages/contracts/**` หรือ `00_API_AND_DATA_CONTRACTS.md`; merge เข้า main | `@everyone` |
| `discord-ci.yml` | `#ci-status` | workflow `CI` จบ — แจ้งเฉพาะแดง/ยกเลิก หรือเขียวบน main | role ของ module (+ `lead` ถ้า main แดง) |
| `discord-conflicts.yml` | `#merge-conflicts` | หลัง push เข้า main → PR ที่เปิดอยู่อันไหน conflict | role ของ module |

กติกาที่ workflow เตือนให้เอง: ชื่อ branch ไม่ตรง `<type>/<NN>-<desc>` · PR เปิดเข้า branch อื่นที่ไม่ใช่ `main` · module ไม่มีใน mapping

`allowed_mentions` จำกัดให้ ping ได้เฉพาะ role ที่ตั้งใจ — ใครพิมพ์ `@everyone` ในชื่อ PR ก็ไม่หลุด

ค่าใน GitHub (ตั้งให้โดย `ops/scripts/github_setup.sh`):

| ชื่อ | ชนิด | ค่า |
|---|---|---|
| `DISCORD_WEBHOOK_PR` / `_CI` / `_CONTRACT` / `_CONFLICTS` / `_ANNOUNCE` | Secret | webhook URL ของแต่ละห้อง |
| `DISCORD_ROLE_IDS` | Variable | `{"01-web":"<id>",...}` |
| `DISCORD_CHANNEL_IDS` | Variable | `{"01-web":"<id>",...}` |
| `DISCORD_MODULE_MAP` | Variable | `{"00":["lead"],"01":["01-web"],...}` |
| `DISCORD_EMBED_BASE_URL` | Variable (optional) | URL public ของ `assets/safetytravel-discord` เพื่อใส่ภาพ brand ใน embed (repo public เท่านั้น) |

ไม่ตั้ง `DISCORD_ROLE_IDS` ข้อความยังส่งได้ แต่ไม่ ping ใคร

## 3. กติกาบน GitHub

`ops/scripts/github_setup.sh` ตั้งให้ตาม `00_GIT_DOCKER_DELIVERY_RULES.md`:
`main` ต้อง PR + approve 1 (งาน auth/emergency/policy/schema/migration ต้อง 2 คนรวม lead — reviewer ต้องดูเอง) · dismiss stale reviews ·
require last-push approval · conversation resolution · linear history · ห้าม force-push/ลบ · `enforce_admins` (หัวหน้าก็ push ตรงไม่ได้) ·
squash-merge เท่านั้น · ลบ branch อัตโนมัติหลัง merge · `CODEOWNERS` ขอ review จากเจ้าของโฟลเดอร์ให้เอง

`.github/pull_request_template.md` = `IMPLEMENTATION_PLANS/PR_TEMPLATE.md` และ `ISSUE_TEMPLATE/bug.md`

## 4. ผู้ช่วยรีวิว

ดู `REVIEW_PLAYBOOK.md` — หัวหน้าสั่ง AI ประโยคเดียว AI ดึง PR → ตรวจกติกา/ลายน้ำ AI → อ่านเทียบ contract → เทสจริงใน worktree + `docker compose -p prtest` → เขียน review บน GitHub → โพสต์ผลเข้าห้องของเจ้าของด้วย `notify.py` (ภาพ embed ตาม `assets/safetytravel-discord/asset-map.json`)

```bash
python notify.py list                                   # id ห้อง/role และ event ที่มีภาพ
python notify.py review --module 04 --status pass --pr 12 --url ... --summary "..."
python notify.py review --module 06 --status changes --pr 15 --summary "..." --fix "..."
python notify.py kickoff --pin                          # ภาพรวมทีมใน #announcements
python notify.py announce --title "Demo ศุกร์นี้" --text "rebase main ก่อน 18:00" --everyone
python notify.py send --channel help --role 02-api --event deadline_reminder --text "..."
```

## กับดักที่เจอมาแล้ว

1. **role ของบอทต้องอยู่บนสุด** ไม่งั้น 403 ตอนแก้ role (Administrator ไม่ช่วย)
2. **อิโมจิหน้าชื่อห้อง** ใส่ผ่าน `emoji:` ใน config เท่านั้น (แสดงเป็น `🌐│01-web` ตาม `channel_name_format`) — ชื่อ logical `01-web` ยังใช้ใน workflow/notify/ids; อย่าไป rename ห้องเองใน Discord ให้ต่างจาก config ไม่งั้นสคริปต์หาไม่เจอแล้วสร้างซ้ำ
3. เรียก Discord API ต้องมี `User-Agent` ไม่งั้น Cloudflare 403 (`discord_api.py` ใส่ให้แล้ว)
4. อยากให้บอทอ่านรายชื่อสมาชิก → เปิด **Server Members Intent** ใน Developer Portal (ตอนนี้ไม่จำเป็น)
5. Token บอท / webhook URL = ความลับ อยู่ใน `.env` และ `out/` เท่านั้น (git-ignored) **ถ้าเคยส่งผ่านแชต/ไฟล์ให้ใคร ให้ Reset Token ทันที**
6. เปิด `--codeowners` **หลัง**ทุกคนรับคำเชิญ collaborator แล้วเท่านั้น ไม่งั้น PR ของคนที่ยังไม่รับจะ merge ไม่ได้
7. `--checks` ใส่ชื่อ job ให้ตรงกับ workflow CI ที่มีจริง ไม่งั้นไม่มี PR ไหน merge ได้
8. GitHub username มี `_` ไม่ได้ เช็ก `gh api users/<ชื่อ>` ก่อนใส่ config — ชื่อผิด GitHub ข้ามเงียบ ๆ
9. ภาพใน webhook embed ต้องเป็น URL public → repo private จะไม่มีภาพ (ข้อความยังส่งปกติ); ส่วน `notify.py` แนบไฟล์ตรงจึงมีภาพเสมอ
10. เพื่อนใช้ Windows ไม่มี `make` → ใน README/ใบงานให้ใส่คำสั่ง `docker compose` แบบเต็มด้วย
11. ให้สมาชิกแตก branch เอง และขึ้นต้นทุกชุดคำสั่งด้วย `git switch main && git pull --ff-only` — ความผิดพลาดที่เจอบ่อยสุดคือแตก branch จาก branch เก่า
12. `notify.py` / `setup_discord.py` มี `if __name__ == "__main__":` แล้ว — อย่า import แล้วเรียกฟังก์ชันโพสต์ซ้ำ
