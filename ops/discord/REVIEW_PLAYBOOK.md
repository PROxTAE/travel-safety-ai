# Review Playbook — "เช็ก PR ใหม่ เทส แล้วแจ้งทุกคน"

ส่วนนี้**ไม่อัตโนมัติ** หัวหน้าสั่ง AI (Claude Code) ในเครื่องด้วยประโยคเดียว แล้ว AI ทำตามขั้นตอนนี้
บอทไม่ได้อ่านโค้ดเอง — บอทเป็นแค่ช่องทางโพสต์ (`notify.py`)

คำสั่งที่หัวหน้าใช้:

```text
อ่าน ops/discord/REVIEW_PLAYBOOK.md แล้วเช็ก PR ที่เปิดอยู่ทั้งหมด เทสจริง เขียนรีวิวบน GitHub และแจ้งเจ้าของทุกคนใน Discord
```

## 0. สิ่งที่ AI ห้ามทำ

- ห้ามกด merge, ห้าม push เข้า branch ของสมาชิก, ห้ามแก้โค้ดในโฟลเดอร์ของคนอื่นแล้ว commit
  (ทดลองแก้ใน worktree ชั่วคราวเพื่อยืนยันวิธีแก้ได้ แต่คนแก้จริงต้องเป็นเจ้าของ เพื่อให้ commit ขึ้นชื่อเขา)
- ห้ามเปลี่ยน branch protection / secrets
- ห้ามใช้ `docker compose down -v` กับ project จริง — ใช้เฉพาะ project ชื่อ `prtest`
- ห้ามโพสต์ token / webhook / API key / PII ลง Discord หรือ GitHub

## 1. ดูสถานะทั้งหมด

```bash
gh pr list --state open --json number,title,headRefName,baseRefName,author,isDraft,updatedAt,reviewDecision,mergeable
git fetch --all --prune
git branch -r --no-merged origin/main          # ใครมี branch แต่ยังไม่เปิด PR
```

แยกเป็น 3 กลุ่ม: PR ใหม่/มี commit ใหม่ตั้งแต่รีวิวครั้งก่อน · PR ที่ยังไม่มีอะไรเปลี่ยน (ข้าม) · branch ที่ยังไม่มี PR (→ status `no-pr`)

## 2. ตรวจกติกาก่อนอ่านโค้ด (ตกข้อใดข้อหนึ่ง = `changes` ทันที)

| ตรวจ | คำสั่ง / เกณฑ์ |
|---|---|
| ชื่อ branch | `^(feat\|fix\|test\|docs\|refactor\|chore\|contract\|infra)/[0-9]{2}-[a-z0-9.-]+$` และ base = `main` |
| ชื่อ PR | `[MXX] ...` และ body ครบทุกหัวข้อของ `PR_TEMPLATE.md` (หัวข้อไม่เกี่ยวเขียน `N/A — reason`) |
| ขนาด | `gh pr diff <n> --stat` < 400 บรรทัดที่ต้อง review (ไม่รวม lock/generated) |
| ขอบเขต | ไฟล์ที่แก้อยู่ในโฟลเดอร์ของ module ตัวเอง (`ops/discord/config.yaml` → `folders`) ถ้าแตะ shared surface ต้องมี lead เป็น reviewer |
| Contract | แตะ `packages/contracts/**` หรือ `00_API_AND_DATA_CONTRACTS.md` → ต้องมี thread ใน #api-contracts และ compat test |
| Commit | Conventional Commits, ไม่มี `wip/update/fix/done` เปล่า ๆ |
| ลายน้ำ AI | `git log origin/main..<branch> --format=%B \| grep -iE 'co-authored-by.*(claude\|copilot\|cursor\|gpt)\|generated with'` และไฟล์ `CLAUDE.md` `.claude/` `.cursor/` `.aider*` ใน diff → ถ้าเจอ ไม่ approve และบอกวิธีลบ (`git rebase -i` แก้ข้อความ / `git rm`) |
| Secret / mock | `gh pr diff <n> \| grep -inE 'api[_-]?key\|secret\|password\|token\|mock\|fake\|hard.?coded\|TODO remove'` แล้วอ่านทีละจุด — runtime ห้ามมี mock/hard-coded current data |
| Handoff | มี `docs/handoffs/Mxx-<feature>.md` ตาม `10_WORK_COMPLETION_REPORT_TEMPLATE.md` |

## 3. อ่านโค้ดเทียบกับ contract และแผน

- `IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md` + `packages/contracts/` — schema, enum, error shape, SSE
- แผนของ module (`IMPLEMENTATION_PLANS/0X_*.md`) — phase ที่ PR นี้อ้างว่าทำ ตรงกับ acceptance ในแผนไหม
- เช็กลิสต์ reviewer ใน `00_GIT_DOCKER_DELIVERY_RULES.md` §6 ครบ 10 ข้อ: timeout/retry/cancellation, degraded state, provenance/freshness, non-root Docker, migration up/down, a11y, safety invariants (official warning ห้ามถูกลดระดับ, LLM ห้ามตัดสิน action)

## 4. เทสจริงในสภาพแวดล้อมแยก (ไม่แตะโฟลเดอร์และฐานข้อมูลที่ใช้งานอยู่)

```bash
git worktree add --detach ../sta-prtest origin/main
cd ../sta-prtest
git merge --no-edit origin/<branch-1> [origin/<branch-2> ...]   # รวมทุก PR ที่จะรีวิว → เห็น conflict ระหว่างกันด้วย
cp .env.example .env    # เติมค่าจริงจาก .env ของเครื่องหัวหน้า (ห้าม commit)
docker compose -p prtest -f compose.yaml -f compose.dev.yaml up -d --build --wait
docker compose -p prtest run --rm api alembic upgrade head
make lint typecheck test-unit test-contract          # หรือคำสั่งเทียบเท่าใน §11
make test-integration                                # ถ้ามี
```

เคสที่น่าจะพัง (ยิงเองด้วย curl / pytest เพิ่ม):
- input ว่าง, พิกัดนอกช่วง, วันที่ย้อนหลัง, ID ปลอม
- ผู้ใช้ A ขอ trip ของผู้ใช้ B (ownership)
- ปิด service ข้างเคียง (`docker compose -p prtest stop external-data`) → ต้องได้ `degraded`/`unavailable` ไม่ใช่ 500 หรือข้อมูลแต่ง
- provider ตอบช้า/429 → timeout + retry policy ทำงาน
- migration: empty DB → head, main DB → head, downgrade -1
- UI: keyboard-only, mobile viewport, screenshot เทียบ `assets/ui-screens/`

ถ้าเจอบั๊ก ให้ลองแก้ใน worktree จนยืนยันว่าหายจริง แล้วเอา diff นั้นไปเขียนเป็น "วิธีแก้ที่ลองแล้วได้ผล" (ไม่ push)

เก็บกวาด:

```bash
docker compose -p prtest down -v
cd .. && git worktree remove --force sta-prtest
```

## 5. เขียนรีวิวบน GitHub (ภาษาไทย ระบุ ผ่าน/ไม่ผ่าน เพราะอะไร ผลเทสจริง วิธีแก้)

```bash
gh pr review <n> --approve         --body "$(cat review.md)"
gh pr review <n> --request-changes --body "$(cat review.md)"
```

โครง `review.md`:

```markdown
## ผล: ✅ ผ่าน / ❌ ขอให้แก้
**เทสจริง:** `make test-unit` → 31 passed, 0 failed · `docker compose -p prtest up --wait` healthy 9/9 · curl ... → 200 (request_id ...)
**ปัญหา (เรียงตามความสำคัญ)**
1. `services/x/y.py:42` — ... → ผลที่เกิด ... → วิธีแก้ (ลองแล้วได้ผล): ...
**ข้อเสนอแนะ (ไม่บังคับ)** ...
**กติกา:** branch ✓ PR template ✓ ขนาด 312 บรรทัด ✓ ลายน้ำ AI ✗ (commit abc123 มี Co-Authored-By) ...
```

## 6. แจ้งเจ้าของใน Discord (ping role ของ module, ห้องของเขาเอง, ภาษาคน)

```bash
cd ops/discord
python notify.py review --module 04 --status pass    --pr 12 --url <pr-url> --branch feat/04-weather-adapter \
  --tests "31 passed" --summary "adapter + fixture ครบ degraded state ทำงาน กด merge ได้เลย"

python notify.py review --module 06 --status changes --pr 15 --url <pr-url> --branch feat/06-rag-index \
  --summary "ปิด qdrant แล้ว service crash แทนที่จะตอบ degraded (rag/index.py:88)" \
  --fix "ห่อ client.search ด้วย try/except QdrantException → return RetrievalResult(status='degraded', ...) ลองแล้วเทสผ่าน"

python notify.py review --workstream frontend --status no-pr \
  --summary "เห็น branch feat/01-web-shell มี 6 commits แล้ว ฝากเปิด PR (draft ก็ได้) จะได้รีวิวเป็นระยะ"
```

`--module` route ตาม `module_map` (06 → ทั้ง riskmodel และ rag) · `--also-pr-channel` ถ้าอยากให้สรุปสั้นขึ้น #pull-requests ด้วย

## 7. สรุปให้หัวหน้า

ตารางเดียว: PR · module · ผล · ประเด็นสำคัญ 1 บรรทัด · สิ่งที่หัวหน้าต้องตัดสินใจ (เช่น merge ลำดับไหนก่อนเพราะ dependency, contract ที่ต้อง lock)
