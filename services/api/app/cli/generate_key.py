"""Print a fresh encryption key.

    docker compose run --rm api python -m app.cli.generate_key

Prints one base64 key and nothing else, so it can be pasted straight after a version prefix:

    API_EMERGENCY_ENCRYPTION_KEYS=v1:<the value>

Rotating means appending, never replacing. Rows still reference the version they were sealed
under, and dropping that key makes them unreadable:

    API_EMERGENCY_ENCRYPTION_KEYS=v1:<old>,v2:<new>
    API_EMERGENCY_ENCRYPTION_ACTIVE_VERSION=v2

New records then use `v2`, old ones keep opening under `v1`, and the re-wrap step moves them across
without touching the encrypted payloads. `v1` comes out only once nothing references it.
"""

from __future__ import annotations

import sys

from app.security.envelope import EnvelopeCipher


def main() -> int:
    # stdout, not the logger: the point is to pipe or copy this, and a JSON log line around it
    # would mean the key ends up in whatever collects logs.
    sys.stdout.write(EnvelopeCipher.generate_key() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
