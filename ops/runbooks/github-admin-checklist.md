# GitHub admin checklist — `PROxTAE/travel-safety-ai`

repo ถูกโอนมาเป็นของ lead (PROxTAE) เมื่อ 2026-09-19 · ข้อ 2–6 ทำแล้วด้วย `gh` (ruleset `protect-main`, squash-only, secrets/variables) · เหลือข้อ 1 (เชิญเพื่อน) และเปิด CODEOWNERS ทีหลัง

สิ่งที่ **admin** ทำ เพื่อให้ flow ของทีม (`<type>/NN-desc` → PR เข้า `main`) และบอท Discord ทำงานได้
ทำครั้งเดียว เรียงตามลำดับ · ใครได้สิทธิ์ admin แล้วรัน `bash ops/scripts/github_setup.sh PROxTAE/travel-safety-ai` แทนข้อ 4–6 ได้

## 1. สิทธิ์
- [x] lead (`PROxTAE`) เป็นเจ้าของ repo แล้ว
- [ ] เชิญสมาชิกอีก 7 คนเป็น **Write** (ชื่อ GitHub อยู่ใน `ops/discord/config.yaml` → `github:` หลังจากทุกคนส่งชื่อมา)
- [ ] ทุกคน **กดรับคำเชิญ** (ยังไม่รับ = เปิด PR/ถูก request review ไม่ได้)

## 2. Branch
- [ ] Merge PR `chore/00-repo-bootstrap` เข้า `main` (โครง repo, แผน, compose core, workflows, README ใหม่)
- [ ] **ลบ branch `dev`** และปลด branch protection ของ `dev` (flow ใหม่ไม่ใช้) — workflow `only-from-dev.yml` ถูกลบใน PR bootstrap แล้ว

## 3. Merge settings (Settings → General → Pull Requests)
- [ ] ✅ Allow **squash merging** เท่านั้น (ปิด merge commit และ rebase merge) · default commit message = PR title + body
- [ ] ✅ Automatically delete head branches

## 4. Branch protection `main` — repo นี้ใช้ **Rulesets** (Settings → Rules → Rulesets → `protect-main`) ตั้งแล้วดังนี้
- [ ] Require a pull request before merging · **Required approvals: 1** · Dismiss stale approvals · Require approval of the most recent push
- [ ] Require review from Code Owners — **เปิดหลังทุกคนรับคำเชิญและ `CODEOWNERS` มีชื่อจริงแล้วเท่านั้น**
- [ ] Require status checks to pass · Require branches up to date · เลือก check `ci` (ชื่อ job ใน `.github/workflows/ci.yml`)
- [ ] Require conversation resolution
- [ ] Require linear history
- [ ] ❌ Allow force pushes · ❌ Allow deletions
- [ ] ✅ Do not allow bypassing the above settings (= enforce for admins; lead ก็ push ตรงไม่ได้)

## 5. Actions Secrets (Settings → Secrets and variables → Actions → Secrets)
ค่าจริงอยู่ที่เครื่อง lead ใน `ops/discord/out/discord-ids.json` (ไม่ commit) — lead ส่งให้ทาง DM

| Secret | ค่า |
|---|---|
| `DISCORD_WEBHOOK_PR` | webhooks.pull-requests |
| `DISCORD_WEBHOOK_CI` | webhooks.ci-status |
| `DISCORD_WEBHOOK_CONTRACT` | webhooks.api-contracts |
| `DISCORD_WEBHOOK_CONFLICTS` | webhooks.merge-conflicts |
| `DISCORD_WEBHOOK_ANNOUNCE` | webhooks.announcements |

## 6. Actions Variables (แท็บ Variables)

| Variable | ค่า |
|---|---|
| `DISCORD_GUILD_ID` | `1549627122841165904` |
| `DISCORD_ROLE_IDS` | JSON `role_ids` จาก discord-ids.json |
| `DISCORD_CHANNEL_IDS` | JSON `channel_ids` |
| `DISCORD_MODULE_MAP` | JSON `module_map` เช่น `{"00":["lead"],"01":["01-web"],...}` |
| `DISCORD_EMBED_BASE_URL` | `https://raw.githubusercontent.com/PROxTAE/travel-safety-ai/main/assets/safetytravel-discord` |

## 7. ทดสอบหลังตั้งค่า
- [ ] เปิด PR ทดสอบจาก branch `docs/00-test-bot` → ข้อความต้องขึ้นใน `#pull-requests` และ ping `@lead`
- [ ] push commit ที่ทำให้ `ci` แดง → ข้อความใน `#ci-status`
- [ ] ปิด PR ทดสอบโดยไม่ merge
