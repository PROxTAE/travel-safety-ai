"""What makes a trip valid, and which status may follow which.

Kept free of FastAPI and SQLAlchemy so the rules can be read and tested on their own. Each function
returns the field errors it found rather than raising on the first one: a form that reports one
problem, then another after the user fixes it, is worse than a form that reports both at once.

Two of these rules exist because of what the system does with a trip later:

* **Both endpoints must be confirmed.** The coordinates decide which weather, which road closures
  and which alerts are fetched. A pin the traveller never looked at can be the wrong city with the
  right name, and nothing downstream would notice.
* **A travel mode must have a real data source.** Accepting one we cannot assess would produce an
  answer whose silence about that leg reads as "nothing wrong with it".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.errors.codes import FieldErrorCode
from app.errors.exceptions import FieldError

#: `TravelMode` from `packages/contracts/jsonschema/common/enums.schema.json`. Asserted against the
#: contract in `tests/test_contract_parity.py`.
TRAVEL_MODES: frozenset[str] = frozenset(
    {"FLIGHT", "TRAIN", "BUS", "CAR", "WALK", "BICYCLE", "MULTIMODAL"}
)

#: `TripStatus`, likewise.
TRIP_STATUSES: frozenset[str] = frozenset(
    {"DRAFT", "PLANNED", "ACTIVE", "COMPLETED", "CANCELLED", "DELETED"}
)

#: Statuses a client may set through PATCH. `DELETED` is not one of them: deletion goes through
#: DELETE, which also schedules the purge of the trip's child data. Allowing it here would mark a
#: trip deleted while leaving everything that hangs off it in place.
CLIENT_SETTABLE_STATUSES: frozenset[str] = TRIP_STATUSES - {"DELETED"}

#: Statuses from which nothing further may be set. A finished or abandoned trip stays that way;
#: re-opening one would silently re-use an assessment made for different circumstances.
TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "CANCELLED", "DELETED"})

#: Which status may follow which. Absent from a value's set means the transition is refused.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"DRAFT", "PLANNED", "CANCELLED"}),
    "PLANNED": frozenset({"PLANNED", "DRAFT", "ACTIVE", "COMPLETED", "CANCELLED"}),
    "ACTIVE": frozenset({"ACTIVE", "COMPLETED", "CANCELLED"}),
    "COMPLETED": frozenset({"COMPLETED"}),
    "CANCELLED": frozenset({"CANCELLED"}),
    "DELETED": frozenset({"DELETED"}),
}

#: Fields whose change makes any existing assessment describe a journey that is no longer the one
#: saved. Changing one of these clears `selected_route_id` and `latest_request_id`, so the UI cannot
#: keep showing a verdict reached for a different route, time or destination.
JOURNEY_FIELDS: frozenset[str] = frozenset(
    {"origin", "destination", "departure_time", "return_time", "timezone", "travel_modes"}
)


def validate_timezone(value: str, *, path: str = "timezone") -> list[FieldError]:
    """Check against the tz database rather than against a pattern.

    `Asia/Bangkok` and `Asia/Bangkgok` are both plausible-looking strings. The second would be
    stored happily and then break every local time computed from it.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        return [
            FieldError(
                path=path,
                code=FieldErrorCode.INVALID_FORMAT,
                message=f"{value!r} is not a known IANA time zone",
            )
        ]
    return []


def validate_departure_window(
    departure_time: datetime,
    return_time: datetime | None,
    *,
    now: datetime,
    max_backdate_seconds: int,
    max_future_days: int,
) -> list[FieldError]:
    """Bound the journey in time.

    Backdating is allowed up to a configured window, because a traveller already on the road still
    needs to save the trip they are taking. Past that, a departure in the past is a typo — and an
    assessment of it would be answering a question about weather that has already happened.
    """
    errors: list[FieldError] = []

    earliest = now - timedelta(seconds=max_backdate_seconds)
    if departure_time < earliest:
        errors.append(
            FieldError(
                path="departure_time",
                code=FieldErrorCode.OUT_OF_RANGE,
                message=(
                    "Departure is further in the past than this API accepts. Historical analysis "
                    "is a separate endpoint."
                ),
            )
        )

    latest = now + timedelta(days=max_future_days)
    if departure_time > latest:
        errors.append(
            FieldError(
                path="departure_time",
                code=FieldErrorCode.OUT_OF_RANGE,
                message=f"Departure must be within {max_future_days} days.",
            )
        )

    if return_time is not None and return_time <= departure_time:
        errors.append(
            FieldError(
                path="return_time",
                code=FieldErrorCode.INCONSISTENT,
                message="Return must be after departure.",
            )
        )

    return errors


def validate_travel_modes(
    modes: Sequence[str], *, supported: Iterable[str]
) -> list[FieldError]:
    """Refuse a mode this deployment has no real data source for.

    `UNSUPPORTED_COVERAGE` rather than a quiet acceptance. A flight leg that no provider covers
    would otherwise be assessed as though it were fine, and an answer that says nothing about a leg
    reads as an answer that found nothing wrong with it.
    """
    supported_set = set(supported)
    errors: list[FieldError] = []

    for index, mode in enumerate(modes):
        if mode not in supported_set:
            errors.append(
                FieldError(
                    path=f"travel_modes[{index}]",
                    code=FieldErrorCode.UNSUPPORTED_VALUE,
                    message=(
                        f"{mode} has no data source in this deployment, so a trip using it "
                        "cannot be assessed."
                    ),
                )
            )

    if len(set(modes)) != len(modes):
        errors.append(
            FieldError(
                path="travel_modes",
                code=FieldErrorCode.INCONSISTENT,
                message="Each travel mode may appear only once.",
            )
        )

    return errors


def validate_endpoints_confirmed(
    origin_confirmed: bool, destination_confirmed: bool
) -> list[FieldError]:
    """Both ends must be a pin the traveller actually looked at.

    Geocoding "Springfield" returns a list, and the first entry is a guess. Saving an unconfirmed
    guess means every hazard lookup afterwards is for somewhere the traveller never chose.
    """
    errors: list[FieldError] = []
    if not origin_confirmed:
        errors.append(
            FieldError(
                path="origin.confirmed_by_user",
                code=FieldErrorCode.NOT_CONFIRMED,
                message="Confirm the origin on the map before saving the trip.",
            )
        )
    if not destination_confirmed:
        errors.append(
            FieldError(
                path="destination.confirmed_by_user",
                code=FieldErrorCode.NOT_CONFIRMED,
                message="Confirm the destination on the map before saving the trip.",
            )
        )
    return errors


def validate_status_transition(current: str, requested: str) -> list[FieldError]:
    """Refuse a move the lifecycle does not allow."""
    if requested not in CLIENT_SETTABLE_STATUSES:
        return [
            FieldError(
                path="status",
                code=FieldErrorCode.UNSUPPORTED_VALUE,
                message="Use DELETE to remove a trip.",
            )
        ]

    if requested not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        return [
            FieldError(
                path="status",
                code=FieldErrorCode.INCONSISTENT,
                message=f"A trip that is {current} cannot become {requested}.",
            )
        ]

    return []


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def journey_changed(changed_fields: Iterable[str]) -> bool:
    """Whether a change invalidates whatever assessment the trip already has."""
    return bool(JOURNEY_FIELDS & set(changed_fields))


def etag_for(revision: int) -> str:
    """The weak ETag carrying a trip revision, as the contract spells it: `W/"3"`.

    Weak because it marks a revision of the resource rather than a byte-for-byte body: two reads at
    the same revision can differ in `meta.generated_at` and still mean the same trip.
    """
    return f'W/"{revision}"'


def revision_from_if_match(header_value: str) -> int | None:
    """Read a revision out of an `If-Match` header, or None if it is not one.

    Accepts `W/"3"`, `"3"` and `3`, because clients and proxies each quote it differently and
    rejecting a well-meant header over quoting would be a bad trade. `*` is not accepted: it means
    "any current version", which is exactly the overwrite this precondition exists to stop.
    """
    candidate = header_value.strip()
    if candidate.startswith(("W/", "w/")):
        candidate = candidate[2:].strip()
    candidate = candidate.strip('"')

    if not candidate.isdigit():
        return None
    return int(candidate)


def now_utc() -> datetime:
    """One place to take the clock from, so tests can reason about the boundaries above."""
    return datetime.now(UTC)
