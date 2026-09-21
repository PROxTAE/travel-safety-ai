"""Getting the envelope cipher, or refusing clearly.

Built once at startup and hung off the application, so a misconfigured key is a startup error
rather than a surprise on the first request that needs it. When nothing is configured the service
still runs — health, trips and everything else are unaffected — and only the emergency profile
endpoints report themselves unavailable.

There is deliberately no path from "no key" to "store it anyway".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from app.errors.exceptions import DependencyUnavailable
from app.security.envelope import EnvelopeCipher

if TYPE_CHECKING:
    from app.settings import Settings


def build_cipher(settings: Settings) -> EnvelopeCipher | None:
    """Parse the configured keys. Raises on a malformed key, returns None when there are none."""
    return EnvelopeCipher.from_config(
        settings.emergency_encryption_keys,
        settings.emergency_encryption_active_version,
    )


def require_cipher(request: Request) -> EnvelopeCipher:
    """The cipher, or a 503 that says so.

    503 rather than 500: this is a deployment that has not been given a key, not a bug, and the
    message tells the caller the important part — that nothing was written unencrypted.
    """
    cipher: EnvelopeCipher | None = getattr(request.app.state, "cipher", None)
    if cipher is None:
        raise DependencyUnavailable(
            "encryption",
            message="Emergency profile storage is unavailable. Nothing was stored in the clear.",
        )
    return cipher
