#!/usr/bin/env python
"""Hand out the work: per workstream channel, post (and pin) the assignment
summary with the plan files attached, the AI-usage guide and ready-made prompts.

    python post_assignment.py --dry-run
    python post_assignment.py                 # create or update (markers assignment:<key>:<n>)
    python post_assignment.py --only 01-web

Text lives in assignment.yaml. Mission / phases / branches are extracted from
each module's IMPLEMENTATION_PLANS/0N_*.md so the summary always matches the plan.
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
PLANS = ROOT / "IMPLEMENTATION_PLANS"


def section(md: str, heading_regex: str) -> str:
    """Body of the first `## <heading>` matching regex, up to the next `## `."""
    m = re.search(rf"^## {heading_regex}[^\n]*\n(.*?)(?=^## |\Z)", md, re.M | re.S)
    return m.group(1).strip() if m else ""


def extract_plan(path: Path) -> dict:
    md = path.read_text(encoding="utf-8")
    title = re.search(r"^# (.+)$", md, re.M).group(1).strip()
    title = re.sub(r"^คนที่ \d+ — ", "", title).replace(" Implementation Plan", "")
    mission = section(md, "Mission")
    mission_first = mission.split("\n\n")[0].strip()          # first paragraph only
    if len(mission_first) > 900:
        mission_first = mission_first[:880].rsplit(" ", 1)[0] + " …"
    phases = re.findall(r"^### (Phase \d+ — .+)$", md, re.M)
    branches = re.findall(r"^\d+\. `([^`]+)`", section(md, r"Branch/commit/PR breakdown"), re.M)
    return {"title": title, "mission": mission_first, "phases": phases, "branches": branches}


def ai_prompt(module_file: str) -> str:
    md = (PLANS / "AI_EXECUTION_INSTRUCTIONS.md").read_text(encoding="utf-8")
    block = re.search(r"```text\n(.*?)```", md, re.S).group(1).strip()
    return block.replace("<ASSIGNED_MODULE_FILE>.md", module_file).replace("<ASSIGNED_MODULE_FILE>", module_file)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="workstream key")
    ap.add_argument("--file", default=str(HERE / "assignment.yaml"))
    a = ap.parse_args()

    load_dotenv()
    api = Discord()
    doc = yaml.safe_load(Path(a.file).read_text(encoding="utf-8"))
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    ids = json.loads(IDS_FILE.read_text(encoding="utf-8"))
    chans, roles = ids["channel_ids"], ids["role_ids"]
    me = None if a.dry_run else api.me()["id"]

    def links(text: str, key: str) -> str:
        text = text.replace("{role:{key}}", f"{{role:{key}}}")
        text = re.sub(r"\{ch:([\w-]+)\}", lambda m: f"<#{chans[m.group(1)]}>", text)
        return re.sub(r"\{role:([\w-]+)\}", lambda m: f"<@&{roles[m.group(1)]}>", text)

    for ws in cfg["workstreams"]:
        if a.only and ws["key"] != a.only:
            continue
        plan_file = ws["plans"][0]
        plan_path = PLANS / plan_file
        info = extract_plan(plan_path)
        d = ws.get("docker", {})
        modules = ws["modules"][0]
        fill = {
            "key": ws["key"], "person": ws.get("person", ws["key"]), "modules": modules,
            "plan_file": plan_file, "plan_title": info["title"], "mission": info["mission"],
            "phases": "\n".join(f"• {p}" for p in info["phases"]) or "(ดูหัวข้อ Implementation steps ในแผน)",
            "branches": "\n".join(f"{i}. `{b}`" for i, b in enumerate(info["branches"][:9], 1)) or ", ".join(f"`{b}`" for b in ws["branches"]),
            "branch_first": info["branches"][0] if info["branches"] else ws["branches"][0],
            "folder": ws["folders"][0], "service": d.get("service", ws["key"]),
            "test_first": d.get("test", "").split(" && ")[0] or "the module tests",
            "ai_prompt": ai_prompt(plan_file),
            "repo": "https://github.com/" + cfg["project"]["repo_slug"],
        }
        channel = chans[ws["key"]]
        pins = [] if a.dry_run else api.pins(channel)
        attach_paths = [ROOT / p.format(plan_path=f"IMPLEMENTATION_PLANS/{plan_file}") for p in doc["attach"]]
        for p in attach_paths:
            if not p.exists():
                raise SystemExit(f"attachment missing: {p}")

        for n, part in enumerate(doc["parts"], 1):
            marker = f"assignment:{ws['key']}:{n}"
            title = links(part["title"], ws["key"]).format(**fill)
            desc = links(part["description"], ws["key"]).format(**fill).strip()
            embed = {"title": title, "description": desc, "color": int(part.get("color", 0x25C7AE)),
                     "footer": {"text": f"แจกงาน {n}/{len(doc['parts'])} · {ws['key']} · แก้ที่ ops/discord/assignment.yaml"}}
            if part.get("fields"):
                embed["fields"] = [{"name": links(f["name"], ws["key"]).format(**fill),
                                    "value": links(f["value"], ws["key"]).format(**fill).strip(),
                                    "inline": bool(f.get("inline", False))} for f in part["fields"]]
            files = []
            for slot in ("image", "thumbnail"):
                if part.get(slot) and (ROOT / part[slot]).exists():
                    p = ROOT / part[slot]
                    embed[slot] = {"url": f"attachment://{p.name}"}
                    files.append((p.name, p))
            if n == 1:
                files += [(p.name, p) for p in attach_paths]      # plan documents ride on message 1
            total = len(title) + len(desc) + sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
            if len(desc) > 4096 or total > 6000 or any(len(f["value"]) > 1024 for f in embed.get("fields", [])):
                raise SystemExit(f"{ws['key']} part {n}: too long (desc {len(desc)}, total {total})")
            content = links(part.get("content", ""), ws["key"]).format(**fill)
            content = (content + "\n" if content else "") + f"-# {marker}"
            payload = {"content": content, "embeds": [embed],
                       "allowed_mentions": {"roles": [roles[ws["key"]]] if n == 1 else []}}
            if a.dry_run:
                print(f"  {ws['key']} part {n}: {len(desc)} chars, {len(files)} file(s) - {title}")
                continue
            old = next((m for m in pins if m["author"]["id"] == me and marker in (m.get("content") or "")), None)
            if old:
                cur = (old.get("embeds") or [{}])[0]
                if cur.get("title") == title and (cur.get("description") or "").strip() == desc \
                        and [(f["name"], f["value"].strip()) for f in cur.get("fields", [])] == \
                            [(f["name"], f["value"]) for f in embed.get("fields", [])]:
                    print(f"  {ws['key']} part {n}: unchanged")
                    continue
                api.edit_message_files(channel, old["id"], payload, files=files or None)
                print(f"  {ws['key']} part {n}: updated")
            else:
                msg = api.send_message(channel, payload, files=files or None)
                api.pin_message(channel, msg["id"])
                print(f"  {ws['key']} part {n}: posted + pinned ({len(files)} files)")
            time.sleep(0.8)


if __name__ == "__main__":
    main()
