"""Emergency profile request and response models.

Mirrors `packages/contracts/jsonschema/common/emergency-profile.schema.json`. The limits here are
not decoration: this payload is encrypted as one blob, and an unbounded medical note would mean an
unbounded row and an unbounded decrypt on every read.

Nothing in this module is ever logged. The redaction processor in `app/observability/logging.py`
drops every one of these field names, and a test asserts it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BloodType = Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "UNKNOWN"]


class EmergencyContactPerson(BaseModel):
    """Someone to call. Their details belong to them, not to the account holder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=256)]
    relationship: Annotated[str | None, Field(max_length=64)] = None
    phone: Annotated[str, Field(min_length=3, max_length=32)]
    locale: Annotated[str | None, Field(max_length=35)] = None


class InsuranceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: Annotated[str, Field(max_length=256)]
    policy_reference: Annotated[str | None, Field(max_length=128)] = None
    emergency_phone: Annotated[str | None, Field(max_length=32)] = None


class EmergencyProfileBody(BaseModel):
    """The part a person writes. This is what gets sealed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    blood_type: BloodType | None = None
    allergies: Annotated[list[Annotated[str, Field(max_length=128)]], Field(max_length=32)] = Field(
        default_factory=list
    )
    medical_notes: Annotated[str | None, Field(max_length=2000)] = None
    medications: Annotated[list[Annotated[str, Field(max_length=128)]], Field(max_length=32)] = (
        Field(default_factory=list)
    )
    contacts: Annotated[list[EmergencyContactPerson], Field(max_length=8)] = Field(
        default_factory=list
    )
    insurance: InsuranceRef | None = None

    def to_sealed_payload(self) -> dict[str, Any]:
        """The dict that goes into the envelope.

        `mode="json"` so what is sealed is plain JSON types — a datetime or an enum member would
        seal fine and then fail to come back as itself.
        """
        return self.model_dump(mode="json")


class EmergencyProfileResponse(EmergencyProfileBody):
    """What comes back to the owner, and to nobody else."""

    model_config = ConfigDict(frozen=True)

    updated_at: datetime
    key_version: Annotated[str | None, Field(max_length=32)] = Field(
        default=None,
        description=(
            "Which key version sealed this record. Echoed so a rotation is auditable from the "
            "outside; the key itself never leaves the process."
        ),
    )
