from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml


class RollbackError(ValueError):
    pass


def verified_rollback_target(registry_path: Path) -> tuple[Path, str]:
    registry: dict[str, Any] = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    previous = registry.get("rollback", {}).get("previous")
    if not previous:
        raise RollbackError("no previous policy is registered")
    target = registry_path.parent / str(previous["path"])
    if not target.is_file():
        raise RollbackError("registered rollback policy is missing")
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    if checksum != previous["checksum_sha256"]:
        raise RollbackError("registered rollback checksum does not match")
    if previous.get("status") != "APPROVED":
        raise RollbackError("registered rollback policy is not approved")
    return target, checksum
