#!/usr/bin/env python
"""Post the project overview (summary.yaml) into #project-summary as a series of
branded embeds with the UI screenshots attached.

    python post_summary.py --dry-run     # validate + print what would be posted
    python post_summary.py               # post (refuses if the bot already posted here)
    python post_summary.py --replace     # delete the bot's earlier posts in the channel, then post again

Placeholders inside summary.yaml text: {ch:<channel>} {role:<key>} {repo}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from discord_api import Discord, load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
IDS_FILE = HERE / "out" / "discord-ids.json"

# Written into every post's footer and used by --replace to find them again.
# One constant for both sides: if the display text drifted from the filter,
# --replace would silently match nothing and post a second full set.
FOOTER_MARKER = "SafetyTravel Assistant · ภาพรวมโปรเจกต์"
# Discord bulk-delete refuses messages older than this; older ones go one by one.
BULK_DELETE_MAX_AGE = timedelta(days=14) - timedelta(hours=1)


def own_posts(api: Discord, channel: str, me: str) -> list[dict]:
    """Every post this script made in the channel, however far back (paginated),
    identified by the footer marker so other bot posts (e.g. the diagram) are left alone."""
    found: list[dict] = []
    before = ""
    while True:
        page = api.get(f"/channels/{channel}/messages?limit=100{before}")
        if not page:
            return found
        found += [m for m in page if m["author"]["id"] == me and (
            FOOTER_MARKER in ((m.get("embeds") or [{}])[0].get("footer") or {}).get("text", "")
            or m.get("type") == 6   # "X pinned a message" system notice Discord adds for our own pins
        )]
        before = f"&before={page[-1]['id']}"


def delete_messages(api: Discord, channel: str, messages: list[dict]) -> None:
    """bulk-delete what Discord allows (2-100 messages, < 14 days old); the rest one by one."""
    cutoff = datetime.now(UTC) - BULK_DELETE_MAX_AGE
    recent = [m for m in messages if datetime.fromisoformat(m["timestamp"]) > cutoff]
    old = [m for m in messages if m not in recent]
    for chunk in (recent[i:i + 100] for i in range(0, len(recent), 100)):
        if len(chunk) >= 2:
            api.post(f"/channels/{channel}/messages/bulk-delete", {"messages": [m["id"] for m in chunk]})
        else:
            old += chunk
    for m in old:
        api.delete(f"/channels/{channel}/messages/{m['id']}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true", help="remove the bot's previous posts in the channel first")
    ap.add_argument("--file", default=str(HERE / "summary.yaml"))
    a = ap.parse_args()

    load_dotenv()
    api = Discord()
    doc = yaml.safe_load(Path(a.file).read_text(encoding="utf-8"))
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    chans, roles = ids["channel_ids"], ids["role_ids"]
    repo = cfg["project"].get("repo_slug", "")
    repo_url = f"https://github.com/{repo}"

    def fill(text: str) -> str:
        def ch(m):
            return f"<#{chans[m.group(1)]}>"
        def role(m):
            return f"<@&{roles[m.group(1)]}>"
        text = re.sub(r"\{ch:([\w-]+)\}", ch, text)
        text = re.sub(r"\{role:([\w-]+)\}", role, text)
        return text.replace("{repo}", repo_url)

    channel = chans[doc["channel"]]
    posts = doc["posts"]

    # ---- build all payloads first so a typo fails before anything is posted
    built = []
    for i, p in enumerate(posts, 1):
        embed = {"title": fill(p["title"]), "description": fill(p.get("description", "")).strip(),
                 "color": int(p.get("color", 0x25C7AE))}
        if p.get("fields"):
            embed["fields"] = [{"name": fill(f["name"]), "value": fill(f["value"]).strip(),
                                "inline": bool(f.get("inline", False))} for f in p["fields"]]
        embed["footer"] = {"text": f"{FOOTER_MARKER} {i}/{len(posts)}"}
        files = []
        for slot in ("image", "thumbnail"):
            if p.get(slot):
                path = ROOT / p[slot]
                if not path.exists():
                    raise SystemExit(f"post {i}: {slot} not found: {path}")
                embed[slot] = {"url": f"attachment://{path.name}"}
                files.append((path.name, path))
        total = len(embed["title"]) + len(embed["description"]) + sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
        if len(embed["description"]) > 4096 or total > 6000 or any(len(f["value"]) > 1024 for f in embed.get("fields", [])):
            raise SystemExit(f"post {i} '{p['title']}' too long (description {len(embed['description'])}, total {total})")
        payload = {"content": fill(p.get("content", "")), "embeds": [embed], "allowed_mentions": {"parse": []}}
        built.append((p, payload, files))
        print(f"  {i}. {embed['title']}  [{len(embed['description'])} chars, {len(files)} file(s){', pin' if p.get('pin') else ''}]")

    if a.dry_run:
        print("(dry-run: nothing posted)")
        return

    me = api.me()["id"]
    mine = own_posts(api, channel, me)
    if mine:
        if not a.replace:
            raise SystemExit(f"the bot already has {len(mine)} post(s) in #{doc['channel']} - use --replace to redo")
        delete_messages(api, channel, mine)
        print(f"removed {len(mine)} earlier post(s)")
    elif a.replace:
        print("no earlier posts from this script found - posting a fresh set")

    for p, payload, files in built:
        msg = api.send_message(channel, payload, files=files or None)
        if p.get("pin"):
            api.pin_message(channel, msg["id"])
        print(f"posted: {payload['embeds'][0]['title']}")
        time.sleep(1.0)
    print(f"done -> #{doc['channel']}")


if __name__ == "__main__":
    main()
