"""Granting and withdrawing consent.

One endpoint, because granting and withdrawing are the same act recorded with a different answer.
Every call appends a record carrying the version of the text the person was shown — a consent
record without that version proves nothing, which is the whole reason this is a table rather than a
column of booleans.

Withdrawal is never harder than granting: the same endpoint, the same shape, no extra confirmation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.responses import data_response
from app.auth.dependencies import DbSession, require_scopes
from app.auth.principal import Principal
from app.errors.codes import FieldErrorCode
from app.errors.exceptions import FieldError, ValidationFailed
from app.repositories import audit, consents
from app.schemas.envelope import DataResponse
from app.schemas.user import ConsentRecordModel, ConsentRequest

router = APIRouter(prefix="/api/v1", tags=["identity"])

TRAVEL_SCOPE = "travel"
TravelPrincipal = Annotated[Principal, Depends(require_scopes(TRAVEL_SCOPE))]


@router.post(
    "/consents",
    summary="Grant or withdraw a consent",
    status_code=status.HTTP_201_CREATED,
    response_model=DataResponse[ConsentRecordModel],
    responses={
        400: {"description": "A field failed validation."},
        401: {"description": "No token, or a token that failed verification."},
        403: {"description": "The token is valid but does not carry the `travel` scope."},
    },
)
async def record_consent(
    request: Request,
    body: ConsentRequest,
    session: DbSession,
    principal: TravelPrincipal,
) -> DataResponse[ConsentRecordModel]:
    """Record a decision, superseding whatever stood before it for that type.

    The expiry the caller asks for is a ceiling request, not an instruction: location grants are
    clamped to the configured maximum, because a location grant that outlives the errand it was
    given for is indistinguishable from tracking.
    """
    settings = request.app.state.settings
    now = datetime.now(UTC)

    if body.expires_at is not None and body.expires_at <= now:
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="expires_at",
                    code=FieldErrorCode.OUT_OF_RANGE,
                    message="An expiry in the past would record a consent that never applied.",
                )
            ]
        )

    expires_at = consents.cap_expiry(
        body.type,
        body.expires_at,
        now=now,
        location_once_ttl_seconds=settings.consent_location_once_ttl_seconds,
        location_live_max_ttl_seconds=settings.consent_location_live_max_ttl_seconds,
    )

    consent = await consents.record(
        session,
        owner_id=principal.user_id,
        consent_type=body.type,
        granted=body.granted,
        policy_version=body.policy_version,
        expires_at=expires_at,
    )

    # The decision itself is the audit record, so the type, the answer and the policy version all
    # belong here. None of them is content the person typed.
    await audit.write(
        session,
        user_id=principal.user_id,
        action=audit.ACTION_CONSENT_RECORDED,
        resource_type="consent",
        resource_id=consent.id,
        details={
            "consent_type": body.type,
            "granted": body.granted,
            "policy_version": body.policy_version,
            "expiry_capped": (
                body.expires_at is not None
                and expires_at is not None
                and expires_at < body.expires_at
            ),
        },
    )

    return data_response(
        request,
        ConsentRecordModel(
            # `body.type` rather than `consent.type`: the column is a plain string, so reading it
            # back widens the type and loses the contract's five permitted values. This is the
            # value that was just written, already validated against that list on the way in.
            consent_id=consent.id,
            type=body.type,
            granted=consent.granted,
            policy_version=consent.policy_version,
            granted_at=consent.granted_at,
            revoked_at=consent.revoked_at,
            expires_at=consent.expires_at,
        ),
    )
