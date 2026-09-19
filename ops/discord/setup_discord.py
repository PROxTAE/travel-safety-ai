#!/usr/bin/env python
"""Idempotent Discord server setup for the SafetyTravel Assistant team.

Reads config.yaml and makes the guild match it:
  roles (lead + one per workstream) -> categories/channels -> pinned briefs -> webhooks

Never deletes anything unless --prune is given (then only `retired:` items). Existing objects are matched by name and only
updated when they differ from config (EXISTS / UPDATE / CREATE is printed
for each item).

Usage:
    python setup_discord.py --dry-run        # print the plan, change nothing
    python setup_discord.py                  # apply
    python setup_discord.py --skip-pins --skip-webhooks
    python setup_discord.py --prune          # also delete roles/channels listed under retired:

Outputs out/discord-ids.json (contains webhook URLs -> git-ignored) and the
`gh secret/variable set` commands for GitHub Actions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from discord_api import Discord, DiscordError, data_uri, load_dotenv

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "discord-ids.json"
ASSETS = (HERE / "../../assets/safetytravel-discord").resolve()

TEXT, CATEGORY = 0, 4
SEND_MESSAGES = 1 << 11
VIEW_CHANNEL = 1 << 10
ROLE_OVERWRITE, MEMBER_OVERWRITE = 0, 1
BRIEF_MARKER = "brief:"


def norm(name: str) -> str:
    """Compare names the way humans do: drop emoji/punctuation, casefold."""
    return re.sub(r"[^0-9a-zA-Z฀-๿]+", "", name).casefold()


class Setup:
    def __init__(self, cfg: dict, api: Discord, guild_id: str, dry: bool):
        self.cfg, self.api, self.gid, self.dry = cfg, api, guild_id, dry
        self.bot = api.me()
        self.roles = api.roles(guild_id)
        self.channels = api.channels(guild_id)
        self.role_ids: dict[str, str] = {}
        self.channel_ids: dict[str, str] = {}
        self.webhooks: dict[str, str] = {}
        self.warnings: list[str] = []
        self.bot_top = max(
            (r["position"] for r in self.roles if r.get("tags", {}).get("bot_id") == self.bot["id"]),
            default=0,
        )

    # ---- logging ---------------------------------------------------------
    def log(self, action: str, kind: str, name: str, extra: str = ""):
        tag = {"CREATE": "+", "UPDATE": "~", "EXISTS": "=", "SKIP": "-", "WARN": "!", "DELETE": "x"}[action]
        print(f"  [{tag}] {action:<6} {kind:<9} {name}{('  ' + extra) if extra else ''}")

    def warn(self, msg: str):
        self.warnings.append(msg)
        self.log("WARN", "", msg)

    # ---- roles -----------------------------------------------------------
    def role_specs(self):
        lead = self.cfg["lead_role"]
        yield lead["name"], {"color": int(lead.get("color", 0)), "hoist": bool(lead.get("hoist", True))}
        for ws in self.cfg["workstreams"]:
            yield ws["key"], {"color": int(ws.get("color", 0)), "hoist": True}

    def ensure_roles(self):
        print("\n== Roles")
        for name, want in self.role_specs():
            want = {**want, "permissions": "0", "mentionable": True}
            found = next((r for r in self.roles if r["name"].casefold() == name.casefold()), None)
            if not found:
                self.log("CREATE", "role", name, f"color=#{want['color']:06X} hoist")
                if not self.dry:
                    found = self.api.post(f"/guilds/{self.gid}/roles", {"name": name, **want},
                                          reason="setup_discord.py")
                    self.roles.append(found)
                else:
                    found = {"id": f"<new:{name}>", "position": 0}
            else:
                diff = {k: v for k, v in want.items() if str(found.get(k)) != str(v)}
                if diff:
                    if found["position"] >= self.bot_top:
                        self.warn(f"role '{name}' is above the bot role -> cannot update {list(diff)}; "
                                  "drag the bot role to the top in Server Settings > Roles")
                    else:
                        self.log("UPDATE", "role", name, str(diff))
                        if not self.dry:
                            self.api.patch(f"/guilds/{self.gid}/roles/{found['id']}", diff,
                                           reason="setup_discord.py")
                else:
                    self.log("EXISTS", "role", name)
            self.role_ids[name] = found["id"]

    # ---- channels --------------------------------------------------------
    def find_channel(self, name: str, ctype: int, parent: str | None = None):
        cands = [c for c in self.channels if c["type"] == ctype]
        exact = [c for c in cands if c["name"].casefold() == name.casefold()]
        if not exact:
            exact = [c for c in cands if norm(c["name"]) == norm(name)]
        if parent and len(exact) > 1:
            exact = [c for c in exact if c.get("parent_id") == parent] or exact
        return exact[0] if exact else None

    def ensure_category(self, name: str) -> str:
        found = self.find_channel(name, CATEGORY)
        if found:
            self.log("EXISTS", "category", found["name"])
            return found["id"]
        self.log("CREATE", "category", name)
        if self.dry:
            return f"<new:{name}>"
        created = self.api.post(f"/guilds/{self.gid}/channels", {"name": name, "type": CATEGORY},
                                reason="setup_discord.py")
        self.channels.append(created)
        return created["id"]

    def overwrites_for(self, post_only: list[str] | None, existing: list[dict]) -> list[dict] | None:
        """Read-only channel: deny SEND_MESSAGES for @everyone, allow for listed roles + bot."""
        if not post_only:
            return None
        allow_ids = [self.role_ids[r] for r in post_only] + [self.bot["id"]]
        keep = [o for o in existing if o["id"] not in allow_ids + [self.gid]]
        want = keep + [{"id": self.gid, "type": ROLE_OVERWRITE, "allow": "0", "deny": str(SEND_MESSAGES)}]
        for rid in allow_ids:
            typ = MEMBER_OVERWRITE if rid == self.bot["id"] else ROLE_OVERWRITE
            want.append({"id": rid, "type": typ, "allow": str(SEND_MESSAGES), "deny": "0"})
        return want

    @staticmethod
    def overwrites_equal(a: list[dict], b: list[dict]) -> bool:
        key = lambda o: (o["id"], int(o.get("type", 0)), int(o.get("allow", 0)), int(o.get("deny", 0)))
        return sorted(map(key, a)) == sorted(map(key, b))

    def display_name(self, spec: dict) -> str:
        """Channel name as shown in Discord: config `emoji` + logical name, e.g. `🌐│01-web`."""
        emoji = spec.get("emoji")
        if not emoji:
            return spec["name"]
        fmt = self.cfg["project"].get("channel_name_format", "{emoji}│{name}")
        return fmt.format(emoji=emoji, name=spec["name"])

    def ensure_text_channel(self, spec: dict, parent_id: str):
        name, topic = spec["name"], spec.get("topic", "")
        shown = self.display_name(spec)
        found = self.find_channel(shown, TEXT, parent_id) or self.find_channel(name, TEXT, parent_id)
        if found:
            patch: dict = {}
            if found["name"] != shown:
                patch["name"] = shown
            if (found.get("topic") or "") != topic:
                patch["topic"] = topic
            if found.get("parent_id") != parent_id:
                patch["parent_id"] = parent_id
            want_ow = self.overwrites_for(spec.get("post_only"), found.get("permission_overwrites", []))
            if want_ow is not None and not self.overwrites_equal(want_ow, found.get("permission_overwrites", [])):
                patch["permission_overwrites"] = want_ow
            if patch:
                self.log("UPDATE", "channel", f"#{name}", ", ".join(patch) + (f"  → {shown}" if "name" in patch else ""))
                if not self.dry:
                    self.api.patch(f"/channels/{found['id']}", patch, reason="setup_discord.py")
                    found["name"] = shown
            else:
                self.log("EXISTS", "channel", f"#{name}")
            self.channel_ids[name] = found["id"]
            return found
        self.log("CREATE", "channel", f"#{shown}", f"post_only={spec.get('post_only')}" if spec.get("post_only") else "")
        if self.dry:
            self.channel_ids[name] = f"<new:{name}>"
            return {"id": self.channel_ids[name], "name": name}
        body = {"name": shown, "type": TEXT, "parent_id": parent_id, "topic": topic}
        ow = self.overwrites_for(spec.get("post_only"), [])
        if ow:
            body["permission_overwrites"] = ow
        created = self.api.post(f"/guilds/{self.gid}/channels", body, reason="setup_discord.py")
        self.channels.append(created)
        self.channel_ids[name] = created["id"]
        return created

    def ensure_channels(self):
        print("\n== Channels")
        self.webhook_channels: list[str] = []
        self.ws_channels: dict[str, dict] = {}
        for cat in self.cfg["categories"]:
            parent = self.ensure_category(cat["name"])
            specs = list(cat.get("channels", []))
            if cat.get("workstream_channels"):
                specs += [{"name": ws["key"], "emoji": ws.get("emoji"),
                           "topic": (f"{ws['person']} · " if ws.get("person") else "") + " ".join(ws["scope"].split())[:1000],
                           "_ws": ws}
                          for ws in self.cfg["workstreams"]]
            for spec in specs:
                ch = self.ensure_text_channel(spec, parent)
                if spec.get("webhook"):
                    self.webhook_channels.append(spec["name"])
                if "_ws" in spec:
                    self.ws_channels[spec["_ws"]["key"]] = ch

    # ---- pinned briefs ---------------------------------------------------
    def brief_fill(self, ws: dict) -> dict:
        proj = self.cfg["project"]
        repo = proj.get("repo_slug", "")
        return {
            "key": ws["key"],
            "person": ws.get("person", ws["key"]),
            "modules": ", ".join(ws["modules"]),
            "modules_first": ws["modules"][0],
            "plans": " → ".join(f"`{p}`" for p in ws["plans"]),
            "folders": "\n".join(f"• `{f}`" for f in ws["folders"]),
            "branches": ", ".join(f"`{b}`" for b in ws["branches"]),
            "branch_first": ws["branches"][0],
            "commit_scopes": "|".join(ws["commit_scopes"]),
            "scope": " ".join(ws["scope"].split()),
            "default_branch": proj["default_branch"],
            "plans_dir": proj["plans_dir"],
            "repo": repo,
            "repo_url": f"https://github.com/{repo}" if repo and "<" not in repo else "",
        }

    def render_brief(self, ws: dict) -> tuple[dict, list[tuple[str, Path]]]:
        """Build the brief embed + the asset files it references (attachment://)."""
        b = self.cfg["brief"]
        fill = self.brief_fill(ws)
        embed: dict = {
            "title": b["title"].format(**fill),
            "description": b["description"].format(**fill).strip(),
            "color": int(ws.get("color", 0)),
            "fields": [{"name": f["name"].format(**fill), "value": f["value"].format(**fill).strip(),
                        "inline": bool(f.get("inline", False))} for f in b.get("fields", [])],
        }
        if b.get("url") and fill["repo_url"]:
            embed["url"] = b["url"].format(**fill)
        files: list[tuple[str, Path]] = []
        for slot in ("image", "thumbnail", "footer_icon"):
            name = b.get(slot)
            if not name:
                continue
            path = ASSETS / name
            if not path.exists():
                self.warn(f"brief {slot} not found: {path}")
                continue
            files.append((name, path))
            if slot == "footer_icon":
                embed.setdefault("footer", {})["icon_url"] = f"attachment://{name}"
            else:
                embed[slot] = {"url": f"attachment://{name}"}
        if b.get("footer"):
            embed.setdefault("footer", {})["text"] = b["footer"].format(**fill)
        total = len(embed["title"]) + len(embed["description"]) + sum(len(f["name"]) + len(f["value"]) for f in embed["fields"])
        for f in embed["fields"]:
            if len(f["value"]) > 1024:
                self.warn(f"brief {ws['key']} field '{f['name']}' is {len(f['value'])} chars (> 1024)")
        if len(embed["description"]) > 4096 or total > 6000:
            self.warn(f"brief {ws['key']} too long (description {len(embed['description'])}, total {total})")
        return embed, files

    def linkify(self, embed: dict) -> None:
        """Turn plain `#channel` / `@role` names into clickable Discord mentions inside embed text."""
        def sub(text: str) -> str:
            for name, cid in sorted(self.channel_ids.items(), key=lambda kv: -len(kv[0])):
                if not str(cid).startswith("<new"):
                    text = re.sub(rf"(?<![\w`<])#{re.escape(name)}\b", f"<#{cid}>", text)
            for name, rid in sorted(self.role_ids.items(), key=lambda kv: -len(kv[0])):
                if not str(rid).startswith("<new"):
                    text = re.sub(rf"(?<![\w`<])@{re.escape(name)}\b", f"<@&{rid}>", text)
            return text
        embed["description"] = sub(embed.get("description", ""))
        for f in embed.get("fields", []):
            f["value"] = sub(f["value"])

    @staticmethod
    def embed_text_equal(a: dict, b: dict) -> bool:
        strip = lambda e: {
            "title": e.get("title"), "description": (e.get("description") or "").strip(), "color": e.get("color"),
            "fields": [(f["name"], f["value"].strip()) for f in e.get("fields", [])],
            "footer": (e.get("footer") or {}).get("text"),
        }
        return strip(a) == strip(b)

    def ensure_briefs(self):
        print("\n== Pinned briefs")
        for ws in self.cfg["workstreams"]:
            ch = self.ws_channels.get(ws["key"])
            if not ch or str(ch["id"]).startswith("<new"):
                self.log("SKIP", "brief", ws["key"], "(channel not created yet in dry-run)")
                continue
            embed, files = self.render_brief(ws)
            self.linkify(embed)
            marker = f"{BRIEF_MARKER}{ws['key']}"
            content = (f"<@&{self.role_ids[ws['key']]}> นี่คือใบงานของห้องนี้ — ปักหมุดไว้ อ่านก่อนเริ่มงาน"
                       f"\n-# {marker}")
            payload = {"content": content, "embeds": [embed], "allowed_mentions": {"parse": []}}
            pins = self.api.pins(ch["id"])
            mine = next((m for m in pins if m["author"]["id"] == self.bot["id"] and marker in (m.get("content") or "")), None)
            if mine:
                cur = (mine.get("embeds") or [{}])[0]
                if self.embed_text_equal(cur, embed):
                    self.log("EXISTS", "brief", f"#{ws['key']}")
                    continue
                self.log("UPDATE", "brief", f"#{ws['key']}")
                if not self.dry:
                    # re-upload assets so attachment:// references stay valid after the edit
                    self.api.edit_message_files(ch["id"], mine["id"], payload, files=files)
                continue
            self.log("CREATE", "brief", f"#{ws['key']}", "(post + pin)")
            if self.dry:
                continue
            msg = self.api.send_message(ch["id"], payload, files=files)
            self.api.pin_message(ch["id"], msg["id"])

    # ---- webhooks --------------------------------------------------------
    def ensure_webhooks(self):
        print("\n== Webhooks")
        wcfg = self.cfg.get("webhook", {})
        wname = wcfg.get("name", "GitHub")
        existing = self.api.guild_webhooks(self.gid)
        avatar = None
        if wcfg.get("avatar"):
            p = (HERE / wcfg["avatar"]).resolve()
            if p.exists():
                avatar = data_uri(p)
            else:
                self.warn(f"webhook avatar not found: {p}")
        for chname in self.webhook_channels:
            cid = self.channel_ids[chname]
            hook = next((w for w in existing if w["type"] == 1 and w["channel_id"] == cid and w["name"] == wname), None)
            if hook:
                self.log("EXISTS", "webhook", f"#{chname}")
            else:
                self.log("CREATE", "webhook", f"#{chname}", f"name='{wname}'")
                if self.dry:
                    continue
                body = {"name": wname}
                if avatar:
                    body["avatar"] = avatar
                try:
                    hook = self.api.post(f"/channels/{cid}/webhooks", body, reason="setup_discord.py")
                except DiscordError as e:
                    if avatar and e.status == 400:
                        self.warn(f"avatar rejected for #{chname}, creating without it: {e.body[:120]}")
                        hook = self.api.post(f"/channels/{cid}/webhooks", {"name": wname}, reason="setup_discord.py")
                    else:
                        raise
            if hook and hook.get("token"):
                self.webhooks[chname] = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"
            elif hook:
                self.warn(f"webhook for #{chname} exists but its token is not readable "
                          "(created by someone else) - delete it in Discord and re-run, or copy the URL manually")

    # ---- output ----------------------------------------------------------
    def module_map(self) -> dict[str, list[str]]:
        m: dict[str, list[str]] = {}
        lead = self.cfg["lead_role"]
        for mod in lead.get("modules", []):
            m.setdefault(str(mod), []).append(lead["name"])
        for ws in self.cfg["workstreams"]:
            for mod in ws["modules"]:
                m.setdefault(str(mod), []).append(ws["key"])
        return dict(sorted(m.items()))

    def write_output(self):
        data = {
            "guild_id": self.gid,
            "bot_id": self.bot["id"],
            "role_ids": self.role_ids,
            "channel_ids": self.channel_ids,
            "module_map": self.module_map(),
            "webhooks": self.webhooks,
        }
        secret_for = {"pull-requests": "DISCORD_WEBHOOK_PR", "ci-status": "DISCORD_WEBHOOK_CI",
                      "api-contracts": "DISCORD_WEBHOOK_CONTRACT", "merge-conflicts": "DISCORD_WEBHOOK_CONFLICTS",
                      "announcements": "DISCORD_WEBHOOK_ANNOUNCE"}
        print("\n== GitHub Actions setup (Settings > Secrets and variables > Actions)")
        repo = self.cfg["project"].get("repo_slug", "<owner>/<repo>")
        role_ids = {k: v for k, v in self.role_ids.items()}
        chan_ids = {k: v for k, v in self.channel_ids.items()}
        print(f"  gh variable set DISCORD_GUILD_ID   -R {repo} -b '{self.gid}'")
        print(f"  gh variable set DISCORD_ROLE_IDS   -R {repo} -b '{json.dumps(role_ids, separators=(',', ':'))}'")
        print(f"  gh variable set DISCORD_CHANNEL_IDS -R {repo} -b '{json.dumps(chan_ids, separators=(',', ':'))}'")
        print(f"  gh variable set DISCORD_MODULE_MAP -R {repo} -b '{json.dumps(self.module_map(), separators=(',', ':'))}'")
        for ch, url in self.webhooks.items():
            if ch in secret_for:
                print(f"  gh secret set {secret_for[ch]:<26} -R {repo} -b '<see out/discord-ids.json: webhooks.{ch}>'")
        if self.dry:
            print("\n(dry-run: nothing written)")
            return
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {OUT.relative_to(HERE.parent.parent)}  (contains webhook URLs - keep it out of git)")

    # ---- prune (opt-in) --------------------------------------------------
    def prune(self):
        """Delete roles/channels listed under `retired:` in config. Only runs with --prune."""
        print("\n== Prune (retired roles/channels)")
        retired = self.cfg.get("retired") or {}
        managed_channels = set(self.channel_ids)
        for name in retired.get("channels", []):
            if name in managed_channels:
                self.warn(f"refusing to delete #{name}: it is also in the active config")
                continue
            ch = self.find_channel(name, TEXT)
            if not ch:
                self.log("SKIP", "channel", f"#{name}", "(already gone)")
                continue
            self.log("DELETE", "channel", f"#{name}", ch["id"])
            if not self.dry:
                self.api.delete(f"/channels/{ch['id']}", reason="setup_discord.py --prune")
                self.channels = [c for c in self.channels if c["id"] != ch["id"]]
        for name in retired.get("roles", []):
            if name in self.role_ids:
                self.warn(f"refusing to delete role '{name}': it is also in the active config")
                continue
            role = next((r for r in self.roles if r["name"].casefold() == name.casefold()), None)
            if not role:
                self.log("SKIP", "role", name, "(already gone)")
                continue
            if role["position"] >= self.bot_top:
                self.warn(f"cannot delete role '{name}': above the bot role")
                continue
            self.log("DELETE", "role", name, role["id"])
            if not self.dry:
                self.api.delete(f"/guilds/{self.gid}/roles/{role['id']}", reason="setup_discord.py --prune")
                self.roles = [r for r in self.roles if r["id"] != role["id"]]

    def run(self, skip_pins: bool, skip_webhooks: bool, do_prune: bool = False):
        print(f"Guild {self.gid} | bot {self.bot['username']} ({self.bot['id']}) | bot top role position {self.bot_top}"
              f"{' | DRY-RUN' if self.dry else ''}")
        self.ensure_roles()
        self.ensure_channels()
        if not skip_pins:
            self.ensure_briefs()
        if not skip_webhooks:
            self.ensure_webhooks()
        if do_prune:
            self.prune()
        self.write_output()
        if self.warnings:
            print(f"\n{len(self.warnings)} warning(s):")
            for w in self.warnings:
                print("  ! " + w)


def pick_guild(api: Discord, explicit: str | None) -> str:
    if explicit:
        return explicit
    guilds = api.guilds()
    if len(guilds) == 1:
        return guilds[0]["id"]
    names = ", ".join(f"{g['name']}={g['id']}" for g in guilds)
    raise SystemExit(f"Bot is in {len(guilds)} guilds; set GUILD_ID or pass --guild. ({names})")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--guild", help="guild id (default: GUILD_ID env, or the only guild the bot is in)")
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    ap.add_argument("--skip-pins", action="store_true")
    ap.add_argument("--skip-webhooks", action="store_true")
    ap.add_argument("--prune", action="store_true", help="also DELETE roles/channels listed under `retired:` in config")
    args = ap.parse_args()

    load_dotenv()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    api = Discord()
    import os
    gid = pick_guild(api, args.guild or os.environ.get("GUILD_ID"))
    Setup(cfg, api, gid, args.dry_run).run(args.skip_pins, args.skip_webhooks, args.prune)


if __name__ == "__main__":
    main()
