"""Trip CRUD.

Five routes, and three things they all share.

**Ownership is a query, not a check.** Every repository call takes the owner resolved from the
token. A trip belonging to somebody else is reported as 404, identically to one that does not
exist, so trip ids cannot be probed by watching the status change.

**A mutation is guarded by a revision.** PATCH requires `If-Match` carrying the revision the client
last read, and the comparison happens inside the UPDATE rather than before it. Two tabs editing the
same trip are resolved by PostgreSQL: one gets the new revision, the other gets 412 and has to
reload. Without that, the slower tab would silently overwrite a change it never saw.

**A change to the journey invalidates its assessment.** Moving the destination or the departure
time clears `latest_request_id` and `selected_route_id`. Keeping them would let the UI go on
displaying a verdict reached for a different journey, which is the most dangerous stale value this
service can hold: it looks exactly like a current answer.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.responses import data_response, list_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.db.models.travel import Trip
from app.domain import trip as rules
from app.errors.codes import FieldErrorCode
from app.errors.exceptions import (
    FieldError,
    IdempotencyConflict,
    NotFound,
    PreconditionFailed,
    PreconditionRequired,
    UnsupportedCoverage,
    ValidationFailed,
)
from app.observability.logging import get_logger
from app.repositories import audit, idempotency, trips
from app.schemas.envelope import DataResponse, ListResponse, PageMeta
from app.schemas.trip import (
    CreateTripRequest,
    DeletionStatusModel,
    TripModel,
    UpdateTripRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/trips", tags=["trips"])

CREATE_TRIP_OPERATION = "createTrip"


def _to_model(row: Trip) -> TripModel:
    """Turn a stored row into the contract entity.

    `model_validate` rather than field-by-field construction, so a JSONB column that somehow does
    not match `LocationRef` is caught here and becomes a withheld response, rather than being
    passed to the browser as a half-formed location.
    """
    return TripModel.model_validate(
        {
            "trip_id": row.id,
            "revision": row.revision,
            "title": row.title,
            "origin": row.origin,
            "destination": row.destination,
            "departure_time": row.departure_time,
            "return_time": row.return_time,
            "timezone": row.timezone,
            "travel_modes": row.travel_modes,
            "preferences": row.preferences or {},
            "selected_route_id": row.selected_route_id,
            "previous_selected_route_id": row.previous_selected_route_id,
            "latest_request_id": row.latest_request_id,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
        }
    )


def _validate_journey(
    request: Request,
    *,
    origin_confirmed: bool,
    destination_confirmed: bool,
    departure_time: Any,
    return_time: Any,
    timezone: str,
    travel_modes: list[str],
) -> None:
    """Apply every domain rule and report all failures together.

    Collected rather than raised one at a time: a form that reveals its second problem only after
    the first is fixed costs the user a round trip per mistake.

    Coverage is separated from the rest because it is a different answer. A malformed request is
    400; a well-formed request for a journey no real data source covers is 422, and the difference
    tells the client whether editing the form could help.
    """
    settings = request.app.state.settings
    errors: list[FieldError] = []

    errors += rules.validate_timezone(timezone)
    errors += rules.validate_departure_window(
        departure_time,
        return_time,
        now=rules.now_utc(),
        max_backdate_seconds=settings.trip_max_backdate_seconds,
        max_future_days=settings.trip_max_future_days,
    )
    errors += rules.validate_endpoints_confirmed(origin_confirmed, destination_confirmed)

    coverage_errors = rules.validate_travel_modes(
        travel_modes, supported=settings.trip_supported_travel_modes
    )
    unsupported = [
        error for error in coverage_errors if error.code is FieldErrorCode.UNSUPPORTED_VALUE
    ]
    errors += [error for error in coverage_errors if error not in unsupported]

    if errors:
        raise ValidationFailed(field_errors=errors)

    if unsupported:
        raise UnsupportedCoverage(
            "This deployment has no real data source for one of the selected travel modes, so a "
            "trip using it could not be assessed.",
            field_errors=unsupported,
        )


def _etag(response: Response, revision: int) -> None:
    response.headers["ETag"] = rules.etag_for(revision)


# --- create -------------------------------------------------------------------------------------


@router.post(
    "",
    summary="Create a trip",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[TripModel],
    responses={
        400: {"description": "A field failed validation."},
        401: {"description": "No token, or a token that failed verification."},
        409: {"description": "The idempotency key was reused with a different payload."},
        422: {"description": "No provider coverage for a selected travel mode."},
    },
)
async def create_trip(
    request: Request,
    response: Response,
    body: CreateTripRequest,
    session: DbSession,
    principal: TravelPrincipal,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> DataResponse[TripModel]:
    """Save a journey.

    Both endpoints must be locations the traveller confirmed on the map, because the coordinates
    decide which weather, closures and alerts are fetched for this trip. A pin nobody looked at can
    be the wrong city with the right name, and nothing downstream would notice.

    With an `Idempotency-Key`, a retry after a network timeout returns the trip the first attempt
    created instead of creating a second one.
    """
    _validate_journey(
        request,
        origin_confirmed=body.origin.confirmed_by_user,
        destination_confirmed=body.destination.confirmed_by_user,
        departure_time=body.departure_time,
        return_time=body.return_time,
        timezone=body.timezone,
        travel_modes=list(body.travel_modes),
    )

    payload = body.model_dump(mode="json")

    if idempotency_key is not None:
        try:
            existing_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_TRIP_OPERATION,
                payload=payload,
            )
        except idempotency.KeyConflict:
            raise IdempotencyConflict from None

        if existing_id is not None:
            existing = await trips.get_owned(
                session, owner_id=principal.user_id, trip_id=existing_id
            )
            if existing is not None:
                _etag(response, existing.revision)
                response.status_code = status.HTTP_200_OK
                return data_response(request, _to_model(existing))
            # The key names a trip that has since been deleted. Falling through creates a new one
            # rather than answering 404 to a retry of a request that did succeed.

    values = _insert_values(body)

    created: Trip | None
    if idempotency_key is None:
        created = await trips.create(session, owner_id=principal.user_id, values=values)
    else:
        created = await _create_claiming_key(
            session,
            owner_id=principal.user_id,
            values=values,
            key=idempotency_key,
            payload=payload,
        )
        if created is None:
            # Another request holding the same key won the race. Return what it created, which is
            # what the client would have got had its two attempts not overlapped.
            winner_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_TRIP_OPERATION,
                payload=payload,
            )
            winner = (
                await trips.get_owned(session, owner_id=principal.user_id, trip_id=winner_id)
                if winner_id
                else None
            )
            if winner is None:  # pragma: no cover - the winner's row and key commit together
                raise IdempotencyConflict
            _etag(response, winner.revision)
            response.status_code = status.HTTP_200_OK
            return data_response(request, _to_model(winner))

    await audit.write(
        session,
        user_id=principal.user_id,
        action=audit.ACTION_TRIP_CREATED,
        resource_type="trip",
        resource_id=created.id,
        # Mode names and a count. Not the origin, the destination or the title: where somebody is
        # going is the thing this table must not accumulate.
        details={"mode_count": len(created.travel_modes), "status": created.status},
    )

    _etag(response, created.revision)
    response.headers["Location"] = f"/api/v1/trips/{created.id}"
    return data_response(request, _to_model(created))


def _insert_values(body: CreateTripRequest) -> dict[str, Any]:
    return {
        "title": body.title,
        "origin": body.origin.model_dump(mode="json"),
        "destination": body.destination.model_dump(mode="json"),
        "departure_time": body.departure_time,
        "return_time": body.return_time,
        "timezone": body.timezone,
        "travel_modes": list(body.travel_modes),
        "preferences": body.preferences.model_dump(mode="json"),
        "status": "DRAFT",
    }


async def _create_claiming_key(
    session: DbSession,
    *,
    owner_id: uuid.UUID,
    values: dict[str, Any],
    key: str,
    payload: Any,
) -> Trip | None:
    """Create the trip and claim the key together, or neither.

    The savepoint is what makes a concurrent duplicate safe. Two retries that both passed the
    lookup race on the unique constraint; the loser rolls back its own insert as well as its
    claim, so it cannot leave an orphan trip behind, and returns None so the caller can serve the
    winner's.
    """
    try:
        async with session.begin_nested():
            created = await trips.create(session, owner_id=owner_id, values=values)
            await idempotency.record(
                session,
                owner_id=owner_id,
                key=key,
                operation=CREATE_TRIP_OPERATION,
                payload=payload,
                resource_id=created.id,
            )
            return created
    except IntegrityError:
        logger.info(
            "idempotent_create_lost_race",
            event_type="idempotency",
            operation=CREATE_TRIP_OPERATION,
        )
        return None


# --- read ---------------------------------------------------------------------------------------


@router.get(
    "",
    summary="List the caller's trips",
    response_model=ListResponse[TripModel],
    responses={
        400: {"description": "The cursor or a query parameter is invalid."},
        401: {"description": "No token, or a token that failed verification."},
    },
)
async def list_trips(
    request: Request,
    session: DbSession,
    principal: TravelPrincipal,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    trip_status: Annotated[str | None, Query(alias="status")] = None,
) -> ListResponse[TripModel]:
    """The caller's trips, newest departure first.

    Soft-deleted trips are excluded unless `status=DELETED` is asked for explicitly, so a person
    can still see what they removed while it is inside the retention window.
    """
    if trip_status is not None and trip_status not in rules.TRIP_STATUSES:
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="status",
                    code=FieldErrorCode.UNSUPPORTED_VALUE,
                    message=f"Unknown trip status {trip_status!r}.",
                )
            ]
        )

    decoded = None
    if cursor is not None:
        decoded = trips.decode_cursor(cursor)
        if decoded is None:
            raise ValidationFailed(
                field_errors=[
                    FieldError(
                        path="cursor",
                        code=FieldErrorCode.INVALID_FORMAT,
                        message="Use a cursor from a previous page; do not construct one.",
                    )
                ]
            )

    page_size = limit or request.app.state.settings.trip_list_default_limit
    rows, has_more = await trips.list_owned(
        session,
        owner_id=principal.user_id,
        limit=page_size,
        cursor=decoded,
        status=trip_status,
    )

    return list_response(
        request,
        [_to_model(row) for row in rows],
        page=PageMeta(
            cursor=cursor,
            next_cursor=trips.cursor_for(rows) if has_more else None,
            has_more=has_more,
        ),
    )


@router.get(
    "/{trip_id}",
    summary="Get one trip",
    response_model=DataResponse[TripModel],
    responses={
        401: {"description": "No token, or a token that failed verification."},
        404: {"description": "No such trip for this caller."},
    },
)
async def get_trip(
    request: Request,
    response: Response,
    session: DbSession,
    principal: TravelPrincipal,
    trip_id: Annotated[uuid.UUID, Path()],
) -> DataResponse[TripModel]:
    """Read a trip, with the `ETag` a later update must quote back."""
    trip = await trips.get_owned(session, owner_id=principal.user_id, trip_id=trip_id)
    if trip is None:
        raise NotFound

    _etag(response, trip.revision)
    return data_response(request, _to_model(trip))


# --- update -------------------------------------------------------------------------------------


@router.patch(
    "/{trip_id}",
    summary="Update a trip",
    response_model=DataResponse[TripModel],
    responses={
        400: {"description": "A field failed validation."},
        401: {"description": "No token, or a token that failed verification."},
        404: {"description": "No such trip for this caller."},
        412: {"description": "The If-Match revision is stale; re-read and retry."},
        422: {"description": "No provider coverage for a selected travel mode."},
        428: {"description": "If-Match is required and was not supplied."},
    },
)
async def update_trip(
    request: Request,
    response: Response,
    body: UpdateTripRequest,
    session: DbSession,
    principal: TravelPrincipal,
    trip_id: Annotated[uuid.UUID, Path()],
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=64)] = None,
) -> DataResponse[TripModel]:
    """Change a trip, if it is still at the revision the client last read.

    The precondition is mandatory. Without it, two tabs editing the same trip would both succeed
    and the second would erase the first's change with no sign that anything was lost.
    """
    if if_match is None:
        raise PreconditionRequired

    expected = rules.revision_from_if_match(if_match)
    if expected is None:
        # Includes `If-Match: *`, which means "whatever is current" — precisely the unconditional
        # overwrite this header exists to prevent.
        raise PreconditionFailed(
            "If-Match must carry the revision you last read, for example W/\"3\"."
        )

    current = await trips.get_owned(session, owner_id=principal.user_id, trip_id=trip_id)
    if current is None:
        raise NotFound

    changes = body.changes()
    if not changes:
        # Nothing to do, and no revision burned for it. A client that computed an empty diff gets
        # the trip back unchanged rather than an error.
        _etag(response, current.revision)
        return data_response(request, _to_model(current))

    if "status" in changes:
        errors = rules.validate_status_transition(current.status, str(changes["status"]))
        if errors:
            raise ValidationFailed(field_errors=errors)
    elif rules.is_terminal(current.status):
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="<request>",
                    code=FieldErrorCode.INCONSISTENT,
                    message=f"A trip that is {current.status} can no longer be edited.",
                )
            ]
        )

    merged = _merged_journey(current, body)
    _validate_journey(
        request,
        origin_confirmed=merged["origin"]["confirmed_by_user"],
        destination_confirmed=merged["destination"]["confirmed_by_user"],
        departure_time=merged["departure_time"],
        return_time=merged["return_time"],
        timezone=merged["timezone"],
        travel_modes=merged["travel_modes"],
    )

    values = _update_values(body, changes)

    # The journey is not the one the last assessment answered for. Dropping the pointers is the
    # honest move: a client that keeps rendering the old verdict is showing a safety answer for a
    # route the traveller is no longer taking. Passed separately from the caller's own changes,
    # because these two columns are ones a request body may never reach.
    server_values = (
        {"latest_request_id": None, "selected_route_id": None}
        if rules.journey_changed(changes)
        else None
    )

    updated = await trips.bump(
        session,
        owner_id=principal.user_id,
        trip_id=trip_id,
        expected_revision=expected,
        values=values,
        server_values=server_values,
    )
    if updated is None:
        # The row was there a moment ago, so this is the revision having moved underneath us.
        raise PreconditionFailed

    await audit.write(
        session,
        user_id=principal.user_id,
        action=audit.ACTION_TRIP_UPDATED,
        resource_type="trip",
        resource_id=updated.id,
        details={"fields": ",".join(sorted(changes)), "revision": updated.revision},
    )

    _etag(response, updated.revision)
    return data_response(request, _to_model(updated))


def _merged_journey(current: Trip, body: UpdateTripRequest) -> dict[str, Any]:
    """The journey as it would be after this PATCH.

    Validation runs against the result, not against the fields that happen to be present: changing
    only `return_time` can still produce a return before a departure that was never mentioned.
    """
    return {
        "origin": (
            body.origin.model_dump(mode="json") if body.origin is not None else current.origin
        ),
        "destination": (
            body.destination.model_dump(mode="json")
            if body.destination is not None
            else current.destination
        ),
        "departure_time": (
            body.departure_time if body.departure_time is not None else current.departure_time
        ),
        "return_time": (
            body.return_time if "return_time" in body.model_fields_set else current.return_time
        ),
        "timezone": body.timezone if body.timezone is not None else current.timezone,
        "travel_modes": (
            list(body.travel_modes) if body.travel_modes is not None else current.travel_modes
        ),
    }


def _update_values(body: UpdateTripRequest, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate the request into column values, for the fields actually sent."""
    values: dict[str, Any] = {}

    if "title" in changes:
        values["title"] = body.title
    if body.origin is not None:
        values["origin"] = body.origin.model_dump(mode="json")
    if body.destination is not None:
        values["destination"] = body.destination.model_dump(mode="json")
    if body.departure_time is not None:
        values["departure_time"] = body.departure_time
    if "return_time" in changes:
        values["return_time"] = body.return_time
    if body.timezone is not None:
        values["timezone"] = body.timezone
    if body.travel_modes is not None:
        values["travel_modes"] = list(body.travel_modes)
    if body.preferences is not None:
        values["preferences"] = body.preferences.model_dump(mode="json")
    if body.status is not None:
        values["status"] = body.status

    return values


# --- delete -------------------------------------------------------------------------------------


@router.delete(
    "/{trip_id}",
    summary="Soft-delete a trip",
    response_model=DataResponse[DeletionStatusModel],
    responses={
        401: {"description": "No token, or a token that failed verification."},
        404: {"description": "No such trip for this caller."},
    },
)
async def delete_trip(
    request: Request,
    session: DbSession,
    principal: TravelPrincipal,
    trip_id: Annotated[uuid.UUID, Path()],
) -> DataResponse[DeletionStatusModel]:
    """Remove a trip from the caller's view and schedule the purge of its child data.

    The response reports `IN_PROGRESS`, not `COMPLETED`. The trip stops being visible immediately,
    but assessments and recommendations produced for it live in other services' schemas and are
    removed by the retention worker. Reporting completion before that has happened would be a
    reassurance this service cannot honestly give.
    """
    deleted = await trips.soft_delete(session, owner_id=principal.user_id, trip_id=trip_id)
    if deleted is None:
        raise NotFound

    await audit.write(
        session,
        user_id=principal.user_id,
        action=audit.ACTION_TRIP_DELETED,
        resource_type="trip",
        resource_id=deleted.id,
        details={"revision": deleted.revision},
    )

    return data_response(
        request,
        DeletionStatusModel(
            resource_id=deleted.id,
            status="IN_PROGRESS",
            requested_at=deleted.deleted_at or rules.now_utc(),
            completed_at=None,
        ),
    )
