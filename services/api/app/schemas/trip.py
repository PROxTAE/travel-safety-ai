"""Trip request and response models.

Mirrors `Trip`, `CreateTripRequest` and `UpdateTripRequest` in the frozen contract;
`tests/test_contract_parity.py` asserts the field names and required sets match.

What pydantic checks here is shape: types, lengths, ranges, unknown fields. What it deliberately
does *not* check is anything needing the clock, the tz database or this deployment's provider
coverage — those live in `app/domain/trip.py`, are applied in the handler, and report every problem
at once instead of one per round trip.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.location import LocationRef

TravelMode = Literal["FLIGHT", "TRAIN", "BUS", "CAR", "WALK", "BICYCLE", "MULTIMODAL"]
TripStatus = Literal["DRAFT", "PLANNED", "ACTIVE", "COMPLETED", "CANCELLED", "DELETED"]
ClientTripStatus = Literal["DRAFT", "PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"]
DeletionStatus = Literal["PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"]

AccessibilityNeed = Literal[
    "STEP_FREE",
    "WHEELCHAIR",
    "LOW_FLOOR_VEHICLE",
    "AVOID_STAIRS",
    "ASSISTANCE_REQUIRED",
    "VISUAL_IMPAIRMENT",
    "HEARING_IMPAIRMENT",
]


def _require_offset(value: datetime | None) -> datetime | None:
    """Refuse a naive timestamp rather than assuming it is UTC.

    `2026-09-20T09:30:00` from a browser in Bangkok and the same string from one in London are
    seven hours apart. Guessing turns that into a forecast for the wrong part of the day.
    """
    if value is not None and value.tzinfo is None:
        raise ValueError("timestamp must carry a timezone offset, e.g. 2026-09-20T09:30:00Z")
    return value


class TravelPreference(BaseModel):
    """How the traveller would like options ranked.

    Preferences rank acceptable options; they never make an unacceptable one acceptable. Nothing
    here can clear a closure or lower a risk level — that is a property of where these values are
    read, and it is stated in the contract so no downstream module treats them as an override.
    """

    model_config = ConfigDict(extra="forbid")

    prefer_safer_route: bool = True
    prefer_lower_cost: bool = False
    prefer_lower_emissions: bool = False
    max_extra_duration_minutes: Annotated[int | None, Field(ge=0, le=1440)] = 90
    avoid_tolls: bool = False
    accessibility: Annotated[list[AccessibilityNeed], Field(max_length=16)] = Field(
        default_factory=list
    )


class TripModel(BaseModel):
    """A trip as it appears in a response."""

    model_config = ConfigDict(frozen=True)

    trip_id: UUID
    revision: Annotated[int, Field(ge=1)]
    title: Annotated[str | None, Field(max_length=256)] = None
    origin: LocationRef
    destination: LocationRef
    departure_time: datetime
    return_time: datetime | None = None
    timezone: str
    travel_modes: Annotated[list[TravelMode], Field(min_length=1, max_length=7)]
    preferences: TravelPreference
    selected_route_id: UUID | None = None
    previous_selected_route_id: UUID | None = None
    latest_request_id: UUID | None = None
    status: TripStatus
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class CreateTripRequest(BaseModel):
    """A new trip.

    `extra="forbid"`, because an unrecognised field on input is a client bug or an attack, and
    ignoring it hides both. A client that sends `revision` or `selected_route_id` is told so
    rather than having it quietly dropped — both are the server's to set.
    """

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(max_length=256)] = None
    origin: LocationRef
    destination: LocationRef
    departure_time: datetime
    return_time: datetime | None = None
    timezone: Annotated[str, Field(min_length=1, max_length=64)]
    travel_modes: Annotated[list[TravelMode], Field(min_length=1, max_length=7)]
    preferences: TravelPreference = Field(default_factory=TravelPreference)

    _offsets = field_validator("departure_time", "return_time")(_require_offset)


class UpdateTripRequest(BaseModel):
    """Changes to an existing trip.

    Only the fields actually sent are applied, so a PATCH that omits `title` does not clear it.
    `revision`, `selected_route_id` and `latest_request_id` are absent on purpose: the first is the
    concurrency token, and the other two are set by apply-route and by starting an assessment,
    after the server has checked what the client is asking for.
    """

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(max_length=256)] = None
    origin: LocationRef | None = None
    destination: LocationRef | None = None
    departure_time: datetime | None = None
    return_time: datetime | None = None
    timezone: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    travel_modes: Annotated[list[TravelMode] | None, Field(min_length=1, max_length=7)] = None
    preferences: TravelPreference | None = None
    status: ClientTripStatus | None = None

    _offsets = field_validator("departure_time", "return_time")(_require_offset)

    def changes(self) -> dict[str, object]:
        """Only what the caller actually sent.

        `exclude_unset`, not `exclude_none`: `return_time: null` is a client clearing a return leg,
        which is a different instruction from not mentioning it.
        """
        return self.model_dump(exclude_unset=True)


class DeletionStatusModel(BaseModel):
    """What a soft delete actually accomplished, and what is still outstanding.

    The trip stops being visible immediately; the purge of everything hanging off it runs out of
    band. Saying `COMPLETED` when only the first half has happened would be the kind of reassurance
    this project exists not to give.
    """

    model_config = ConfigDict(frozen=True)

    resource_id: UUID
    status: DeletionStatus
    requested_at: datetime
    completed_at: datetime | None = None
