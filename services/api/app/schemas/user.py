"""Identity response models.

These mirror `packages/contracts/jsonschema/common/user-profile.schema.json` and
`consent-record.schema.json`. `tests/test_contract_parity.py` asserts the field names and required
sets match, so the two cannot drift.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ConsentType = Literal[
    "LOCATION_ONCE",
    "LOCATION_LIVE",
    "ALERT_NOTIFICATION",
    "ANALYTICS",
    "EMERGENCY_PROFILE",
]


class ConsentRecordModel(BaseModel):
    """One versioned consent decision.

    Declared now because `UserProfile.consents` is typed on it. No consent can be granted until
    phase 3, so the list is always empty today — accurately, not as a placeholder.
    """

    model_config = ConfigDict(frozen=True)

    consent_id: UUID
    type: ConsentType
    granted: bool
    policy_version: str
    granted_at: datetime
    revoked_at: datetime | None = None
    expires_at: datetime | None = None


class UserProfileModel(BaseModel):
    """The caller's own profile. Returned to its owner and to nobody else."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    display_name: Annotated[str | None, Field(max_length=256)] = None
    locale: str
    timezone: str
    home_country_code: Annotated[str | None, Field(pattern=r"^[A-Z]{2}$")] = None
    consents: list[ConsentRecordModel] = Field(default_factory=list)
    has_emergency_profile: bool = False
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
