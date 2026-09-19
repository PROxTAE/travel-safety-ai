#!/usr/bin/env python
"""Pin a per-module Docker guide (docker_guide.yaml) in every workstream channel.

    python post_docker_guide.py --dry-run          # render + length check, nothing posted
    python post_docker_guide.py                    # create or update (idempotent via markers)
    python post_docker_guide.py --only 04-external-data

Each part is one message tagged `-# docker-guide:<key>:<n>`; re-running edits
the existing pinned message instead of posting again.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import yaml

from discord_api import Discord, load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
IDS_FILE = HERE / "out" / "discord-ids.json"

STACK_NOTE = {
    "node": "`pnpm add <ชื่อแพ็กเกจ>` ในโฟลเดอร์ apps/web แล้ว commit `package.json` + `pnpm-lock.yaml`",
    "python": "`uv add <ชื่อแพ็กเกจ>` ในโฟลเดอร์ service แล้ว commit `pyproject.toml` + `uv.lock`",
}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="workstream key")
    ap.add_argument("--file", default=str(HERE / "docker_guide.yaml"))
    a = ap.parse_args()

    load_dotenv()
    api = Discord()
    guide = yaml.safe_load(Path(a.file).read_text(encoding="utf-8"))
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    chans, roles = ids["channel_ids"], ids["role_ids"]
    repo_url = "https://github.com/" + cfg["project"]["repo_slug"]
    me = None if a.dry_run else api.me()["id"]

    def links(text: str) -> str:
        text = re.sub(r"\{ch:([\w-]+)\}", lambda m: f"<#{chans[m.group(1)]}>", text)
        return re.sub(r"\{role:([\w-]+)\}", lambda m: f"<@&{roles[m.group(1)]}>", text)

    for ws in cfg["workstreams"]:
        if a.only and ws["key"] != a.only:
            continue
        d = ws.get("docker")
        if not d:
            print(f"  {ws['key']}: no docker: section in config - skipped")
            continue
        deps = d.get("deps", "").split()
        fill = {
            "key": ws["key"], "person": ws.get("person", ws["key"]), "service": d["service"], "port": d["port"],
            "deps": " ".join(deps), "deps_short": ", ".join(deps[:3]) + (" …" if len(deps) > 3 else ""),
            "deps_list": ", ".join(f"`{x}`" for x in deps) or "ไม่มี",
            "test": d["test"].replace(" && ", "\n"), "open_url": d.get("open_url", ""),
            "folder": ws["folders"][0], "stack_note": STACK_NOTE.get(d.get("stack", "python"), ""),
            "repo": repo_url,
            "extra_block": ("**คำสั่งเพิ่มเติมของ module นี้**\n```bash\n" + d["extra"].rstrip() + "\n```\n") if d.get("extra") else "",
        }
        channel = chans[ws["key"]]
        pins = [] if a.dry_run else api.pins(channel)
        role_id = roles[ws["key"]]
        for n, part in enumerate(guide["parts"], 1):
            marker = f"docker-guide:{ws['key']}:{n}"
            # {ch:}/{role:} links first (format() would choke on the ':'), then the plain placeholders
            title = links(part["title"]).format(**fill)
            desc = links(part["description"]).format(**fill).strip()
            embed = {"title": title, "description": desc, "color": int(part.get("color", 0x2496ED)),
                     "footer": {"text": f"Docker guide {n}/{len(guide['parts'])} · {ws['key']} · แก้ที่ ops/discord/docker_guide.yaml"}}
            files = []
            for slot in ("image", "thumbnail"):
                if part.get(slot):
                    p = ROOT / part[slot]
                    if p.exists():
                        embed[slot] = {"url": f"attachment://{p.name}"}
                        files.append((p.name, p))
            if len(desc) > 4096:
                raise SystemExit(f"{ws['key']} part {n}: description {len(desc)} > 4096")
            content = (f"<@&{role_id}> คู่มือ Docker {n}/{len(guide['parts'])} (ปักหมุด)\n-# {marker}") if n == 1 \
                else f"-# {marker}"
            payload = {"content": content, "embeds": [embed], "allowed_mentions": {"parse": []}}
            if a.dry_run:
                print(f"  {ws['key']} part {n}: {len(desc)} chars, {len(files)} file(s) - {title}")
                continue
            old = next((m for m in pins if m["author"]["id"] == me and marker in (m.get("content") or "")), None)
            if old:
                cur = (old.get("embeds") or [{}])[0]
                if cur.get("title") == title and (cur.get("description") or "").strip() == desc:
                    print(f"  {ws['key']} part {n}: unchanged")
                    continue
                api.edit_message_files(channel, old["id"], payload, files=files or None)
                print(f"  {ws['key']} part {n}: updated")
            else:
                msg = api.send_message(channel, payload, files=files or None)
                api.pin_message(channel, msg["id"])
                print(f"  {ws['key']} part {n}: posted + pinned")
            time.sleep(0.6)


if __name__ == "__main__":
    main()
