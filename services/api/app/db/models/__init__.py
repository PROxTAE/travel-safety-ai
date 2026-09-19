"""ORM models, imported here so Alembic autogenerate sees every table.

A model that is not imported by the time `migrations/env.py` reads `Base.metadata` is invisible to
autogenerate, which then cheerfully produces a migration that drops it.
"""

from app.db.models.identity import (
    AuditLogEntry,
    Consent,
    DataSubjectRequest,
    EmergencyProfile,
    UserProfile,
)

__all__ = [
    "AuditLogEntry",
    "Consent",
    "DataSubjectRequest",
    "EmergencyProfile",
    "UserProfile",
]
