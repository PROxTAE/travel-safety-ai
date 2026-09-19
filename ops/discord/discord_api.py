"""Minimal Discord REST client (no third-party deps).

- Sets User-Agent (Cloudflare returns 403 without it)
- Honours 429 rate limits (retry-after)
- Supports JSON and multipart (file attachments)
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (safetytravel-assistant, 1.0)"


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (does not override existing)."""
    path = path or Path(__file__).with_name(".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


class DiscordError(RuntimeError):
    def __init__(self, status: int, body: str, method: str, path: str):
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


class Discord:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("DISCORD_BOT_TOKEN")
        if not self.token:
            raise SystemExit("DISCORD_BOT_TOKEN is not set (put it in ops/discord/.env)")

    # ---- low level -------------------------------------------------------
    def request(self, method: str, path: str, payload: dict | None = None,
                files: list[tuple[str, Path]] | None = None, reason: str | None = None):
        headers = {"Authorization": "Bot " + self.token, "User-Agent": USER_AGENT}
        if reason:
            headers["X-Audit-Log-Reason"] = reason
        data: bytes | None = None
        if files:
            boundary = "----sta" + uuid.uuid4().hex
            parts: list[bytes] = []
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload or {})}\r\n".encode()
            )
            for i, (name, fpath) in enumerate(files):
                ctype = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
                parts.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; "
                    f"filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n".encode()
                    + fpath.read_bytes() + b"\r\n"
                )
            parts.append(f"--{boundary}--\r\n".encode())
            data = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"

        for attempt in range(6):
            req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read()
                    return json.loads(body) if body else None
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                if e.code == 429:
                    try:
                        wait = float(json.loads(body).get("retry_after", 1))
                    except Exception:
                        wait = float(e.headers.get("Retry-After", "1"))
                    time.sleep(wait + 0.25)
                    continue
                raise DiscordError(e.code, body, method, path) from None
        raise DiscordError(429, "rate limited too many times", method, path)

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, payload=None, **kw):
        return self.request("POST", path, payload, **kw)

    def patch(self, path, payload=None, **kw):
        return self.request("PATCH", path, payload, **kw)

    def put(self, path, payload=None, **kw):
        return self.request("PUT", path, payload, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    # ---- helpers ---------------------------------------------------------
    def me(self):
        return self.get("/users/@me")

    def guilds(self):
        return self.get("/users/@me/guilds")

    def roles(self, guild_id):
        return self.get(f"/guilds/{guild_id}/roles")

    def channels(self, guild_id):
        return self.get(f"/guilds/{guild_id}/channels")

    def guild_webhooks(self, guild_id):
        return self.get(f"/guilds/{guild_id}/webhooks")

    def pins(self, channel_id):
        return self.get(f"/channels/{channel_id}/pins")

    def send_message(self, channel_id, payload: dict, files: list[tuple[str, Path]] | None = None):
        return self.post(f"/channels/{channel_id}/messages", payload, files=files)

    def edit_message(self, channel_id, message_id, payload: dict):
        return self.patch(f"/channels/{channel_id}/messages/{message_id}", payload)

    def edit_message_files(self, channel_id, message_id, payload: dict, files: list[tuple[str, Path]] | None = None):
        """Edit a message and replace its attachments with `files` (empty attachments = drop old ones)."""
        payload = {**payload, "attachments": []}
        return self.patch(f"/channels/{channel_id}/messages/{message_id}", payload, files=files or None)

    def pin_message(self, channel_id, message_id):
        return self.put(f"/channels/{channel_id}/pins/{message_id}")


def data_uri(path: Path) -> str:
    import base64
    ctype = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{ctype};base64," + base64.b64encode(path.read_bytes()).decode()
