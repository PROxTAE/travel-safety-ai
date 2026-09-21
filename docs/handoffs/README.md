# `docs/handoffs/`

**เจ้าของ:** ทุกคน

รายงานส่งงาน `Mxx-<feature>.md` ตาม
[`10_WORK_COMPLETION_REPORT_TEMPLATE.md`](../../IMPLEMENTATION_PLANS/10_WORK_COMPLETION_REPORT_TEMPLATE.md)
แนบใน PR ก่อนขอ merge

A report is written for the person who picks the work up next, not for whoever approves the PR.
That means the sections people skip are the ones that matter most: what is *not* implemented, what
went wrong and why, and what each downstream owner has to change.

| Report | Module | Covers |
| --- | --- | --- |
| [`M02-public-api-foundation.md`](M02-public-api-foundation.md) | 02 — API and backend | Contract v1, service scaffold, OIDC, identity and privacy (phases 0–3) |
| [`M04-external-data.md`](M04-external-data.md) | 04 — External data | Provider governance, foundation and the Open-Meteo adapters |
