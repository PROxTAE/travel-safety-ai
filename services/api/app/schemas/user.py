"""Identity response models.

These mirror `packages/contracts/jsonschema/common/user-profile.schema.json` and
`consent-record.schema.json`. `tests/test_contract_parity.py` asserts the field names and required
sets match, so the two cannot drift.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConsentType = Literal[
    "LOCATION_ONCE",
    "LOCATION_LIVE",
    "ALERT_NOTIFICATION",
    "ANALYTICS",
    "EMERGENCY_PROFILE",
]


class ConsentRecordModel(BaseModel):
    """One versioned consent decision, as it appears in a response."""

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


class UpdateProfileRequest(BaseModel):
    """What a person may change about their own profile.

    Identity itself is not here: name and e-mail belong to Keycloak, and a second editable copy
    would be a second thing to keep correct and to delete. Consent is not here either — it goes
    through `/api/v1/consents`, where each decision keeps its own policy version.

    `extra="forbid"` so a typo is a 400 rather than a change the caller thinks happened.
    """

    model_config = ConfigDict(extra="forbid")

    locale: Annotated[str | None, Field(max_length=35)] = None
    timezone: Annotated[str | None, Field(max_length=64)] = None
    home_country_code: Annotated[str | None, Field(max_length=2)] = None

    @field_validator("timezone")
    @classmethod
    def _timezone_must_exist(cls, value: str | None) -> str | None:
        """Checked against the tz database, not against a pattern.

        `Asia/Bangkok` and `Asia/Bangkgok` are both plausible-looking strings. The second one would
        be stored happily and then break every departure time computed from it.
        """
        if value is None:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError) as exc:
            raise ValueError(f"{value!r} is not a known IANA time zone") from exc
        return value

    @field_validator("locale")
    @classmethod
    def _locale_looks_like_bcp47(cls, value: str | None) -> str | None:
        if value is None:
            return None
        import re

        if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|[0-9]{3}))?", value):
            raise ValueError(f"{value!r} is not a BCP-47 language tag")
        return value

    @field_validator("home_country_code")
    @classmethod
    def _country_code_is_uppercase_alpha2(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 2 or not value.isalpha():
            raise ValueError("country code must be two letters, ISO-3166-1 alpha-2")
        # Uppercased rather than rejected: the contract says what is stored, and a client sending
        # "th" means Thailand as clearly as "TH" does.
        return value.upper()

    def changes(self) -> dict[str, object]:
        """Only the fields the caller actually sent.

        A PATCH that omits `timezone` must not reset it to None, which is what a plain
        `model_dump()` would do.
        """
        return self.model_dump(exclude_unset=True)


class ConsentRequest(BaseModel):
    """A decision to grant or withdraw one consent."""

    model_config = ConfigDict(extra="forbid")

    type: ConsentType
    granted: bool
    policy_version: Annotated[str, Field(min_length=1, max_length=32)]
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Requested expiry for a scoped grant. The server caps it: a client may ask for less "
            "than the configured ceiling and never for more."
        ),
    )
