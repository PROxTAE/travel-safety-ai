#!/usr/bin/env python
"""🎲 Random module draw: assign the 8 workstreams in config.yaml to the 8 human
members of the guild, with a slot-machine style animation in #role-draw, then
give each person the matching role.

    python draw.py --dry-run               # who would get what (no posts, no roles)
    python draw.py                         # animate in #role-draw + assign roles
    python draw.py --seed 42               # reproducible draw
    python draw.py --exclude protae1858    # leave someone out (username)
    python draw.py --no-assign             # animation only
    python draw.py --welcome               # also greet each person in their room

Members: needs the Server Members Intent for the fast path; without it the
script falls back to the member-search endpoint (prefix a-z/0-9), which is
enough for a small server.
"""
from __future__ import annotations

import argparse
import json
import random
import string
import sys
import time
from pathlib import Path

import yaml

from discord_api import Discord, DiscordError, load_dotenv

HERE = Path(__file__).resolve().parent
IDS_FILE = HERE / "out" / "discord-ids.json"
ASSETS = (HERE / "../../assets/safetytravel-discord").resolve()
DRAW_CHANNEL = "role-draw"

MINT, ORANGE, GREEN = 0x25C7AE, 0xFF8A1F, 0x10B981
REEL_DELAYS = [0.6, 0.6, 0.7, 0.8, 0.9, 1.1, 1.3, 1.6]   # decelerating spin


def display(m: dict) -> str:
    return m.get("nick") or m["user"].get("global_name") or m["user"]["username"]


def fetch_humans(api: Discord, gid: str) -> list[dict]:
    try:
        members = api.get(f"/guilds/{gid}/members?limit=1000")
    except DiscordError as e:
        if e.status != 403:
            raise
        print("(Server Members Intent is off -> using member search fallback)")
        seen: dict[str, dict] = {}
        for ch in string.ascii_lowercase + string.digits + "_.":
            for m in api.get(f"/guilds/{gid}/members/search?query={ch}&limit=100"):
                seen[m["user"]["id"]] = m
        members = list(seen.values())
    return [m for m in members if not m["user"].get("bot")]


def attach(embed: dict, slot: str, filename: str, files: list) -> None:
    p = ASSETS / filename
    if p.exists():
        embed[slot] = {"url": f"attachment://{filename}"}
        files.append((filename, p))


def reel_text(names: list[str], idx: int) -> str:
    n = len(names)
    prev, cur, nxt = names[(idx - 1) % n], names[idx % n], names[(idx + 1) % n]
    return f"```\n   {prev}\n▶  {cur.upper()}  ◀\n   {nxt}\n```"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--exclude", action="append", default=[], help="username to leave out (repeatable)")
    ap.add_argument("--no-assign", action="store_true", help="animate only, do not touch roles")
    ap.add_argument("--welcome", action="store_true", help="post a welcome ping in each person's room")
    ap.add_argument("--fast", action="store_true", help="fewer/shorter animation frames")
    a = ap.parse_args()

    load_dotenv()
    api = Discord()
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    gid, roles, chans = ids["guild_id"], ids["role_ids"], ids["channel_ids"]
    workstreams = cfg["workstreams"]
    if DRAW_CHANNEL not in chans:
        raise SystemExit(f"#{DRAW_CHANNEL} not found - add it to config.yaml and run setup_discord.py")

    humans = [m for m in fetch_humans(api, gid) if m["user"]["username"] not in a.exclude]
    humans.sort(key=lambda m: display(m).casefold())
    print(f"participants ({len(humans)}): " + ", ".join(display(m) for m in humans))
    if len(humans) != len(workstreams):
        raise SystemExit(f"need exactly {len(workstreams)} participants for {len(workstreams)} modules, got {len(humans)} "
                         f"(use --exclude, or check bots/intent)")

    rng = random.Random(a.seed)
    order = humans[:]
    rng.shuffle(order)
    pairs = list(zip(workstreams, order))
    print("\ndraw result:")
    for ws, m in pairs:
        print(f"  {ws['person']:<8} module {ws['modules'][0]}  {ws['key']:<22} -> {display(m)} ({m['user']['username']})")
    if a.dry_run:
        print("\n(dry-run: nothing posted, no roles changed)")
        return

    draw_ch = chans[DRAW_CHANNEL]
    names = [display(m) for m in humans]

    # ---- 1) intro ---------------------------------------------------------
    files: list = []
    intro = {
        "title": "🎲 สุ่มแจก Module ให้ทีม SafetyTravel Assistant",
        "description": (f"ผู้เข้าร่วม **{len(humans)} คน** · module **{len(workstreams)} อัน** (01–08 ตาม IMPLEMENTATION_PLANS)\n"
                        "สุ่มแบบยุติธรรม ไม่มีใครได้ซ้ำ — ได้ module ไหน บอทจะแจก role และห้องให้ทันที\n\n"
                        "**ผู้เข้าร่วม**\n" + " · ".join(f"<@{m['user']['id']}>" for m in humans)),
        "color": MINT,
        "fields": [{"name": f"Module {ws['modules'][0]}", "value": f"{ws['key']}\n<#{chans[ws['key']]}>", "inline": True}
                   for ws in workstreams],
        "footer": {"text": "SafetyTravel Assistant · ops/discord/draw.py"},
    }
    attach(intro, "image", "embed-announcement.png", files)
    attach(intro, "thumbnail", "mascot-welcome.png", files)
    api.send_message(draw_ch, {"content": "🥁 เริ่มสุ่มแล้ว! ทุกคนดูตรงนี้", "embeds": [intro],
                               "allowed_mentions": {"parse": []}}, files=files)
    time.sleep(2.5)

    # ---- 2) one slot-machine message per module ---------------------------
    delays = REEL_DELAYS[::2] if a.fast else REEL_DELAYS
    for ws, winner in pairs:
        wname = display(winner)
        color = int(ws.get("color", MINT))
        head = f"🎰 Module {ws['modules'][0]} · {ws['key']}"
        remaining = names[:]  # spin over everyone; the reveal is the true winner
        start = rng.randrange(len(remaining))
        embed = {"title": head, "description": "กำลังสุ่ม…\n" + reel_text(remaining, start), "color": 0x5B6B7A}
        msg = api.send_message(draw_ch, {"embeds": [embed]})
        idx = start
        for d in delays:
            time.sleep(d)
            idx += 1
            embed["description"] = "กำลังสุ่ม…\n" + reel_text(remaining, idx)
            api.edit_message(draw_ch, msg["id"], {"embeds": [embed]})
        # land on the winner: place them in the middle of the reel
        time.sleep(1.2)
        wi = remaining.index(wname)
        reveal_files: list = []
        reveal = {
            "title": f"🎉 Module {ws['modules'][0]} · {ws['key']} → {wname}",
            "description": reel_text(remaining, wi) + f"\n**{ws['person']}** คือ <@{winner['user']['id']}> 🎊\n"
                           f"ขอบเขต: {' '.join(ws['scope'].split())[:180]}…",
            "color": color,
            "fields": [
                {"name": "ห้องของคุณ", "value": f"<#{chans[ws['key']]}>", "inline": True},
                {"name": "Role", "value": f"<@&{roles[ws['key']]}>", "inline": True},
                {"name": "แผน", "value": " ".join(f"`{p}`" for p in ws["plans"]), "inline": False},
            ],
            "footer": {"text": f"{ws['person']} · อ่านใบงานที่ปักหมุดในห้องก่อนเริ่ม"},
        }
        attach(reveal, "thumbnail", "mascot-welcome.png", reveal_files)
        # edit_message_files replaces attachments so the thumbnail shows on the reveal
        api.edit_message_files(draw_ch, msg["id"], {"content": f"<@{winner['user']['id']}> 🎉", "embeds": [reveal],
                                                    "allowed_mentions": {"users": [winner["user"]["id"]]}},
                               files=reveal_files)
        print(f"  revealed {ws['key']} -> {wname}")

        if not a.no_assign:
            api.put(f"/guilds/{gid}/members/{winner['user']['id']}/roles/{roles[ws['key']]}",
                    reason=f"draw.py: module {ws['modules'][0]}")
            # drop any other workstream role they might still hold
            for other in workstreams:
                if other["key"] != ws["key"] and roles[other["key"]] in winner.get("roles", []):
                    api.delete(f"/guilds/{gid}/members/{winner['user']['id']}/roles/{roles[other['key']]}",
                               reason="draw.py: re-draw cleanup")
            print(f"  role @{ws['key']} -> {wname}")
        time.sleep(1.5)

    # ---- 3) summary (pinned) ---------------------------------------------
    files = []
    summary = {
        "title": "📋 ผลการสุ่ม — ใครทำ Module ไหน",
        "description": "\n".join(f"**{ws['person']}** · Module {ws['modules'][0]} <#{chans[ws['key']]}> → <@{m['user']['id']}>"
                                 for ws, m in pairs)
                       + "\n\nต่อไป: เข้าห้องของตัวเอง → กด 📌 อ่านใบงาน → สร้าง branch ตามที่ระบุ → เริ่มได้เลย",
        "color": GREEN,
        "footer": {"text": f"seed={a.seed if a.seed is not None else 'random'} · role แจกให้แล้ว" + ("" if not a.no_assign else " (ยังไม่แจก role)")},
    }
    attach(summary, "image", "embed-task-assigned.png", files)
    attach(summary, "thumbnail", "safetytravel-logo-app-icon.png", files)
    final = api.send_message(draw_ch, {"content": "🎊 สุ่มครบทุก module แล้ว", "embeds": [summary],
                                       "allowed_mentions": {"parse": []}}, files=files)
    api.pin_message(draw_ch, final["id"])
    print("summary posted + pinned")

    # ---- 4) optional welcome in each room --------------------------------
    if a.welcome:
        for ws, m in pairs:
            api.send_message(chans[ws["key"]], {
                "content": f"👋 <@{m['user']['id']}> ห้องนี้เป็นของคุณแล้ว ({ws['person']} · Module {ws['modules'][0]}) "
                           f"— ใบงานอยู่ที่ปักหมุด 📌 ด้านบน อ่านแล้วเริ่มจาก `{ws['branches'][0]}` ได้เลย",
                "allowed_mentions": {"users": [m["user"]["id"]]}})
        print("welcome messages posted")


if __name__ == "__main__":
    main()
