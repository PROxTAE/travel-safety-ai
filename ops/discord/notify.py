#!/usr/bin/env python
"""Post branded messages to the team Discord as the SafetyTravel Assistant bot.

Used by the lead (or the AI review assistant, see REVIEW_PLAYBOOK.md) after
reviewing PRs. GitHub Actions do NOT use this file - they use webhooks.

Examples:
    python notify.py list
    python notify.py review --module 04 --status pass    --pr 12 --url https://github.com/o/r/pull/12 \
        --summary "adapter + fixture ครบ เทสผ่าน 31/31 กด merge ได้เลย"
    python notify.py review --module 06 --status changes --pr 15 --url ... \
        --summary "ลืม import asyncio ใน rag/index.py" --fix "เพิ่ม `import asyncio` บรรทัดบนสุด แล้ว push ใหม่"
    python notify.py review --workstream 01-web --status no-pr --summary "มี branch feat/01-web-shell แล้ว ฝากเปิด PR"
    python notify.py announce --title "Demo วันศุกร์" --text "ทุกคน rebase main ก่อน 18:00"
    python notify.py send --channel help --role 02-api --event deadline_reminder --text "..."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from discord_api import Discord, load_dotenv

HERE = Path(__file__).resolve().parent
IDS_FILE = HERE / "out" / "discord-ids.json"
ASSET_DIR = (HERE / "../../assets/safetytravel-discord").resolve()
ASSET_MAP = ASSET_DIR / "asset-map.json"

REVIEW_STATUS = {
    # status: (event for image/colour, emoji, headline)
    "pass":    ("pr_merged",         "✅", "ผ่านรีวิว — กด merge ได้เลย"),
    "changes": ("build_failed",      "❌", "ยังไม่ผ่าน — ต้องแก้ก่อน"),
    "no-pr":   ("deadline_reminder", "⚠️", "มี branch แล้วแต่ยังไม่เปิด PR"),
    "blocked": ("deadline_reminder", "⏳", "รอ dependency / ต้องคุยกันก่อน"),
}


class Team:
    """Name -> id resolution from out/discord-ids.json, falling back to the live guild."""

    def __init__(self, api: Discord):
        self.api = api
        if IDS_FILE.exists():
            d = json.loads(IDS_FILE.read_text(encoding="utf-8"))
        else:
            import os
            gid = os.environ.get("GUILD_ID")
            if not gid:
                gl = api.guilds()
                if len(gl) != 1:
                    raise SystemExit("run setup_discord.py first, or set GUILD_ID")
                gid = gl[0]["id"]
            d = {
                "guild_id": gid,
                "role_ids": {r["name"]: r["id"] for r in api.roles(gid)},
                "channel_ids": {c["name"]: c["id"] for c in api.channels(gid) if c["type"] == 0},
                "module_map": {},
            }
            cfg_file = HERE / "config.yaml"
            if cfg_file.exists():
                import yaml
                for ws in yaml.safe_load(cfg_file.read_text(encoding="utf-8"))["workstreams"]:
                    for m in ws["modules"]:
                        d["module_map"].setdefault(str(m), []).append(ws["key"])
        self.guild_id = d["guild_id"]
        self.roles: dict[str, str] = d["role_ids"]
        self.channels: dict[str, str] = d["channel_ids"]
        self.module_map: dict[str, list[str]] = d.get("module_map", {})
        self.assets = json.loads(ASSET_MAP.read_text(encoding="utf-8")) if ASSET_MAP.exists() else {"events": {}}

    def channel(self, name_or_id: str) -> str:
        if name_or_id.isdigit():
            return name_or_id
        try:
            return self.channels[name_or_id.lstrip("#")]
        except KeyError:
            raise SystemExit(f"unknown channel '{name_or_id}'. known: {', '.join(self.channels)}")

    def role(self, key: str) -> str:
        try:
            return self.roles[key.lstrip("@")]
        except KeyError:
            raise SystemExit(f"unknown role '{key}'. known: {', '.join(self.roles)}")

    def workstreams_for_module(self, module: str) -> list[str]:
        keys = self.module_map.get(module.zfill(2))
        if not keys:
            raise SystemExit(f"module {module} is not in module_map ({list(self.module_map)}); "
                             "use --workstream or re-run setup_discord.py")
        return keys

    def event(self, name: str | None) -> tuple[Path | None, int | None]:
        if not name:
            return None, None
        ev = self.assets["events"].get(name)
        if not ev:
            raise SystemExit(f"unknown event '{name}'. known: {', '.join(self.assets['events'])}")
        img = ASSET_DIR / ev["image"]
        return (img if img.exists() else None), int(ev["color"].lstrip("#"), 16)


def build_payload(team: Team, *, text: str, roles: list[str], title: str | None, event: str | None,
                  fields: list[str], url: str | None, everyone: bool, no_image: bool):
    image, color = team.event(event)
    mention_ids = [team.role(r) for r in roles]
    content = " ".join(f"<@&{rid}>" for rid in mention_ids)
    allowed = {"parse": ["everyone"] if everyone else [], "roles": mention_ids}
    if everyone:
        content = ("@everyone " + content).strip()
    embed: dict = {"description": text}
    if title:
        embed["title"] = title
    if url:
        embed["url"] = url
    if color is not None:
        embed["color"] = color
    if fields:
        embed["fields"] = []
        for f in fields:
            k, _, v = f.partition("=")
            embed["fields"].append({"name": k.strip(), "value": v.strip() or "-", "inline": True})
    files = None
    if image and not no_image:
        embed["image"] = {"url": f"attachment://{image.name}"}
        files = [(image.name, image)]
    return {"content": content, "embeds": [embed], "allowed_mentions": allowed}, files


def cmd_list(team: Team, _):
    print("channels:")
    for k, v in team.channels.items():
        print(f"  #{k:<18} {v}")
    print("roles:")
    for k, v in team.roles.items():
        print(f"  @{k:<18} {v}")
    print("module_map:", json.dumps(team.module_map))
    print("events:", ", ".join(team.assets["events"]))


def cmd_send(team: Team, a):
    payload, files = build_payload(team, text=a.text, roles=a.role or [], title=a.title, event=a.event,
                                   fields=a.field or [], url=a.url, everyone=a.everyone, no_image=a.no_image)
    msg = team.api.send_message(team.channel(a.channel), payload, files=files)
    print(f"sent to #{a.channel}: message {msg['id']}")


def cmd_announce(team: Team, a):
    a.channel, a.event, a.role, a.field, a.url = "announcements", a.event or "announcement", [], [], None
    cmd_send(team, a)


def cmd_review(team: Team, a):
    event, emoji, headline = REVIEW_STATUS[a.status]
    keys = [a.workstream] if a.workstream else team.workstreams_for_module(a.module)
    title = f"{emoji} {headline}"
    if a.pr:
        title += f" · PR #{a.pr}"
    body = a.summary
    if a.fix:
        body += f"\n\n**วิธีแก้ (ลองแล้วได้ผล):**\n{a.fix}"
    if a.status == "pass":
        body += "\n\nเจ้าของ PR: `git switch main && git pull --ff-only` หลัง lead กด squash merge แล้วลบ branch"
    elif a.status == "changes":
        body += "\n\nแก้แล้ว `git push` เข้า branch เดิม บอทจะแจ้งใน #pull-requests เมื่อมี review ใหม่"
    elif a.status == "no-pr":
        body += "\n\nเปิด PR เข้า `main` ด้วย `PR_TEMPLATE.md` ให้ครบ (draft ได้ถ้ายังไม่เสร็จ)"
    fields = []
    if a.module:
        fields.append(f"Module={a.module}")
    if a.branch:
        fields.append(f"Branch=`{a.branch}`")
    if a.tests:
        fields.append(f"Tests={a.tests}")
    for key in keys:
        payload, files = build_payload(team, text=body, roles=[key], title=title, event=event,
                                       fields=fields, url=a.url, everyone=False, no_image=a.no_image)
        msg = team.api.send_message(team.channel(key), payload, files=files)
        print(f"posted review ({a.status}) to #{key} pinging @{key}: message {msg['id']}")
    if a.also_pr_channel:
        payload, files = build_payload(team, text=body, roles=keys, title=title, event=event,
                                       fields=fields, url=a.url, everyone=False, no_image=True)
        team.api.send_message(team.channel("pull-requests"), payload, files=files)
        print("also posted to #pull-requests")


def cmd_kickoff(team: Team, a):
    """Post the team overview (who owns what, where the bot talks) into #announcements."""
    import yaml
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    repo = cfg["project"].get("repo_slug", "")
    repo_url = f"https://github.com/{repo}"
    fields = []
    for ws in cfg["workstreams"]:
        rid, cid = team.roles.get(ws["key"]), team.channels.get(ws["key"])
        plans = ", ".join(p.split("_")[0] for p in ws["plans"])
        fields.append({
            "name": f"{ws.get('person', '')} · Module {', '.join(ws['modules'])}".strip(" ·"),
            "value": f"<@&{rid}> → <#{cid}>\n📁 " + ", ".join(f"`{f}`" for f in ws["folders"][:2])
                     + (" …" if len(ws["folders"]) > 2 else "") + f"\n📖 แผน {plans}",
            "inline": True,
        })
    pr, ci, mc, ac, hp = (team.channels.get(k) for k in ("pull-requests", "ci-status", "merge-conflicts", "api-contracts", "help"))
    desc = (
        f"ทีมเรา 8 workstream ทำงานบน GitHub **{repo}** ({repo_url})\n"
        f"ทุกคนมี**ห้องของตัวเอง**พร้อมใบงานปักหมุด (branch, โฟลเดอร์, แผนที่ต้องอ่าน, กติกา) — เข้าห้องแล้วกด 📌 ด้านบนขวา\n\n"
        f"**บอทจะช่วยอะไร**\n"
        f"• <#{pr}> — แจ้งเมื่อมี PR เปิด / ถูก approve / ขอให้แก้ / merge และ ping เจ้าของ module\n"
        f"• <#{ci}> — แจ้งเมื่อ CI แดง\n"
        f"• <#{mc}> — แจ้งเมื่อ PR ของคุณ conflict กับ main ต้อง rebase\n"
        f"• <#{ac}> — เตือน @everyone เมื่อมีคนแตะ contract กลาง ห้าม approve จนกว่าจะคุยกัน\n"
        f"• หัวหน้าสั่ง AI รีวิว + เทสจริง แล้วผลจะเด้งในห้องของคุณพร้อมวิธีแก้\n\n"
        f"ติดอะไรถามใน <#{hp}> บอกว่า module ไหน branch ไหน error อะไร ลองอะไรไปแล้ว"
    )
    image, color = team.event("announcement")
    logo = ASSET_DIR / "safetytravel-logo-horizontal.png"
    mascot = ASSET_DIR / "mascot-welcome.png"
    embed = {"title": a.title or "🚀 เริ่มงานทีม SafetyTravel Assistant", "url": repo_url, "description": desc,
             "color": color, "fields": fields,
             "footer": {"text": "SafetyTravel Assistant · ops/discord/README.md"}}
    files = []
    if image and not a.no_image:
        embed["image"] = {"url": f"attachment://{image.name}"}; files.append((image.name, image))
    if mascot.exists():
        embed["thumbnail"] = {"url": f"attachment://{mascot.name}"}; files.append((mascot.name, mascot))
    if logo.exists():
        embed["footer"]["icon_url"] = f"attachment://{logo.name}"; files.append((logo.name, logo))
    marker = "-# kickoff"
    payload = {"content": ("@everyone " if a.everyone else "") + marker, "embeds": [embed],
               "allowed_mentions": {"parse": ["everyone"] if a.everyone else []}}
    chan = team.channel("announcements")
    me = team.api.me()["id"]
    # idempotent: a pinned kickoff from the bot gets edited instead of re-posted
    old = next((m for m in team.api.pins(chan) if m["author"]["id"] == me and
                (marker in (m.get("content") or "") or (m.get("embeds") or [{}])[0].get("title") == embed["title"])), None)
    if old and not a.repost:
        team.api.edit_message_files(chan, old["id"], payload, files=files or None)
        print(f"kickoff updated in #announcements: message {old['id']}")
        return
    msg = team.api.send_message(chan, payload, files=files or None)
    if a.pin:
        team.api.pin_message(chan, msg["id"])
    print(f"kickoff posted to #announcements: message {msg['id']}{' (pinned)' if a.pin else ''}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show channel/role ids and known events").set_defaults(fn=cmd_list)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--text", required=True, help="markdown body")
    common.add_argument("--title")
    common.add_argument("--event", help="asset-map event for image/colour (see `list`)")
    common.add_argument("--no-image", action="store_true")

    s = sub.add_parser("send", parents=[common], help="post to any channel")
    s.add_argument("--channel", required=True, help="channel name or id")
    s.add_argument("--role", action="append", help="role key to ping (repeatable)")
    s.add_argument("--field", action="append", help="'Name=Value' embed field (repeatable)")
    s.add_argument("--url", help="link for the embed title")
    s.add_argument("--everyone", action="store_true")
    s.set_defaults(fn=cmd_send)

    s = sub.add_parser("announce", parents=[common], help="post to #announcements")
    s.add_argument("--everyone", action="store_true")
    s.set_defaults(fn=cmd_announce)

    s = sub.add_parser("kickoff", help="post the team overview (who owns what) into #announcements")
    s.add_argument("--title")
    s.add_argument("--everyone", action="store_true")
    s.add_argument("--pin", action="store_true")
    s.add_argument("--repost", action="store_true", help="post a new message instead of editing the pinned one")
    s.add_argument("--no-image", action="store_true")
    s.set_defaults(fn=cmd_kickoff)

    s = sub.add_parser("review", help="post a PR review result into the owner's channel")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--module", help="2-digit module number from the branch name, e.g. 04")
    g.add_argument("--workstream", help="workstream key, e.g. frontend")
    s.add_argument("--status", required=True, choices=list(REVIEW_STATUS))
    s.add_argument("--summary", required=True, help="human summary: ผ่าน/ไม่ผ่าน เพราะอะไร ผลเทสจริง")
    s.add_argument("--fix", help="what to change (already verified to work)")
    s.add_argument("--pr", help="PR number")
    s.add_argument("--url", help="PR url")
    s.add_argument("--branch")
    s.add_argument("--tests", help="e.g. '31 passed, 0 failed'")
    s.add_argument("--also-pr-channel", action="store_true", help="mirror a short copy into #pull-requests")
    s.add_argument("--no-image", action="store_true")
    s.set_defaults(fn=cmd_review)

    a = ap.parse_args()
    load_dotenv()
    team = Team(Discord())
    a.fn(team, a)


if __name__ == "__main__":
    main()
