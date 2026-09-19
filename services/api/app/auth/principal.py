"""Who is making the request.

A `Principal` is the only thing a handler is allowed to treat as the caller's identity. It is built
from a verified token plus the local profile row, never from a request body — §"User identity" of
the module plan: *"ไม่รับ user ID จาก body เป็น authority"*. Passing the principal explicitly, rather
than reading a global, makes that rule visible at every call site.

`subject` is kept for audit, but `user_id` is what every query filters on: the internal id survives
an identity-provider migration, and the external subject does not.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller."""

    user_id: uuid.UUID
    subject: str
    scopes: frozenset[str]
    roles: frozenset[str]
    expires_at: datetime
    token_id: str | None = None
    display_name: str | None = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_role(self, role: str) -> bool:
        return role in self.roles

    @property
    def subject_digest(self) -> str:
        """A short, stable, non-reversible handle for logs.

        The raw subject identifies a person across every log line that carries it. This is enough
        to correlate one user's requests during an investigation without writing their identity
        provider id into log storage.
        """
        return hashlib.sha256(self.subject.encode("utf-8")).hexdigest()[:16]

    def __repr__(self) -> str:
        return f"Principal(user_id={self.user_id!r}, subject_digest={self.subject_digest!r})"
