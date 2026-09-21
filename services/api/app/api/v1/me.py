"""The caller's own profile, consent state and emergency profile.

Every route here reads the owner from the verified principal. None of them takes a user id, so
"read someone else's record" is not an operation this module can express — which is a stronger
guarantee than remembering to compare two ids in each handler.

The emergency profile is the sensitive one. It is sealed before it reaches the database, opened
only for its owner, never logged, and refused outright when no encryption key is configured rather
than stored in the clear.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.responses import data_response
from app.auth.dependencies import DbSession, require_scopes
from app.auth.principal import Principal
from app.errors.codes import FieldErrorCode
from app.errors.exceptions import FieldError as FieldErrorDetail
from app.errors.exceptions import Forbidden, NotFound, ValidationFailed
from app.observability.logging import get_logger
from app.repositories import audit, consents, emergency_profiles, user_profiles
from app.schemas.emergency import EmergencyProfileBody, EmergencyProfileResponse
from app.schemas.envelope import DataResponse
from app.schemas.user import ConsentRecordModel, UpdateProfileRequest, UserProfileModel
from app.security.envelope import DecryptionFailed
from app.security.rate_limit import rate_limit
from app.services.encryption import require_cipher

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["identity"],
    dependencies=[Depends(rate_limit("me"))],
)


#: The scope a browser session must carry to touch anything under `/api/v1`.
TRAVEL_SCOPE = "travel"

TravelPrincipal = Annotated[Principal, Depends(require_scopes(TRAVEL_SCOPE))]

#: Storing medical details needs its own consent, separate from being signed in.
EMERGENCY_PROFILE_CONSENT = "EMERGENCY_PROFILE"


def _to_consent_models(rows: list[object]) -> list[ConsentRecordModel]:
    return [
        ConsentRecordModel(
            consent_id=row.id,  # type: ignore[attr-defined]
            type=row.type,  # type: ignore[attr-defined]
            granted=row.granted,  # type: ignore[attr-defined]
            policy_version=row.policy_version,  # type: ignore[attr-defined]
            granted_at=row.granted_at,  # type: ignore[attr-defined]
            revoked_at=row.revoked_at,  # type: ignore[attr-defined]
            expires_at=row.expires_at,  # type: ignore[attr-defined]
        )
        for row in rows
    ]


async def _profile_response(
    request: Request, session: DbSession, principal: Principal
) -> DataResponse[UserProfileModel]:
    profile = await user_profiles.get_owned(session, owner_id=principal.user_id)
    if profile is None:
        raise NotFound

    standing = await consents.list_standing(session, owner_id=principal.user_id)
    # Existence only. Reporting whether a profile is there must not require the key, so the common
    # request never decrypts anything.
    has_emergency = (
        await emergency_profiles.get_row(session, owner_id=principal.user_id)
    ) is not None

    return data_response(
        request,
        UserProfileModel(
            user_id=profile.id,
            # Not stored. The name belongs to the identity provider, and keeping a second copy
            # would mean holding personal data this service has no reason to hold. It is taken
            # from the verified token and returned only to its owner.
            display_name=principal.display_name,
            locale=profile.locale,
            timezone=profile.timezone,
            home_country_code=profile.home_country_code,
            consents=_to_consent_models(list(standing)),
            has_emergency_profile=has_emergency,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            deleted_at=profile.deleted_at,
        ),
    )


@router.get(
    "/me",
    summary="Get the caller's profile and consent summary",
    response_model=DataResponse[UserProfileModel],
    responses={
        401: {"description": "No token, or a token that failed verification."},
        403: {"description": "The token is valid but does not carry the `travel` scope."},
        404: {"description": "The account was deleted."},
    },
)
async def get_me(
    request: Request, session: DbSession, principal: TravelPrincipal
) -> DataResponse[UserProfileModel]:
    """Read the profile belonging to the caller.

    The row is created on first sign-in by the authentication dependency, so a 404 here means the
    account was deleted between authenticating and reading.
    """
    return await _profile_response(request, session, principal)


@router.patch(
    "/me",
    summary="Update locale, timezone or home country",
    response_model=DataResponse[UserProfileModel],
    responses={
        400: {"description": "A field failed validation."},
        401: {"description": "No token, or a token that failed verification."},
        403: {"description": "The token is valid but does not carry the `travel` scope."},
        404: {"description": "The account was deleted."},
    },
)
async def update_me(
    request: Request,
    body: UpdateProfileRequest,
    session: DbSession,
    principal: TravelPrincipal,
) -> DataResponse[UserProfileModel]:
    """Change presentation preferences.

    Only the fields actually sent are applied: a PATCH that omits `timezone` must not reset it.
    An empty body is accepted and changes nothing, which is what a client that computed no diff
    will send.
    """
    profile = await user_profiles.get_owned(session, owner_id=principal.user_id)
    if profile is None:
        raise NotFound

    changes = body.changes()
    for field, value in changes.items():
        setattr(profile, field, value)
    await session.flush()

    if changes:
        # Field names, never values: a home country is a small but real disclosure, and the audit
        # trail does not need it to answer "who changed what, and when".
        await audit.write(
            session,
            user_id=principal.user_id,
            action=audit.ACTION_PROFILE_UPDATED,
            resource_type="user_profile",
            resource_id=profile.id,
            details={"fields": ",".join(sorted(changes))},
        )

    return await _profile_response(request, session, principal)


@router.get(
    "/me/emergency-profile",
    summary="Read the caller's emergency profile",
    response_model=DataResponse[EmergencyProfileResponse],
    responses={
        401: {"description": "No token, or a token that failed verification."},
        403: {"description": "The `EMERGENCY_PROFILE` consent is not in force."},
        404: {"description": "No emergency profile has been stored."},
        503: {"description": "Encryption is not configured, so the profile cannot be opened."},
    },
)
async def get_emergency_profile(
    request: Request, session: DbSession, principal: TravelPrincipal
) -> DataResponse[EmergencyProfileResponse]:
    """Open the caller's emergency profile.

    Requires the consent that authorised storing it in the first place. If that consent has been
    withdrawn the row is retained for the retention window but is not returned: withdrawing consent
    has to mean something before the purge job runs.
    """
    cipher = require_cipher(request)
    await _require_emergency_consent(session, principal)

    try:
        found = await emergency_profiles.read(session, owner_id=principal.user_id, cipher=cipher)
    except DecryptionFailed:
        # A row exists but will not open: wrong key version, or a tampered row. Reported as a
        # dependency problem rather than "not found", because the data is there and the operator
        # needs to know the key configuration is wrong.
        logger.error(
            "emergency_profile_undecryptable",
            event_type="privacy",
            user_id=str(principal.user_id),
        )
        raise _encryption_unavailable() from None

    if found is None:
        raise NotFound

    payload, row = found
    await audit.write(
        session,
        user_id=principal.user_id,
        action=audit.ACTION_EMERGENCY_PROFILE_READ,
        resource_type="emergency_profile",
        resource_id=row.id,
        details={"key_version": row.key_version},
    )

    return data_response(
        request,
        EmergencyProfileResponse(**payload, updated_at=row.updated_at, key_version=row.key_version),
    )


@router.put(
    "/me/emergency-profile",
    summary="Create or replace the caller's emergency profile",
    response_model=DataResponse[EmergencyProfileResponse],
    responses={
        400: {"description": "A field failed validation."},
        401: {"description": "No token, or a token that failed verification."},
        403: {"description": "The `EMERGENCY_PROFILE` consent is not in force."},
        503: {"description": "Encryption is not configured, so the profile cannot be stored."},
    },
)
async def put_emergency_profile(
    request: Request,
    body: EmergencyProfileBody,
    session: DbSession,
    principal: TravelPrincipal,
) -> DataResponse[EmergencyProfileResponse]:
    """Replace the whole profile.

    Sealed before it reaches the database, under a key that does not live there. Replace rather
    than merge, and one row per user, so an earlier version of someone's medical details is never
    left behind.
    """
    cipher = require_cipher(request)
    await _require_emergency_consent(session, principal)

    row = await emergency_profiles.upsert(
        session,
        owner_id=principal.user_id,
        payload=body.to_sealed_payload(),
        cipher=cipher,
    )

    # Counts, not contents. That a person recorded three allergies is enough to reconstruct what
    # happened; which three is the thing this table must never hold.
    await audit.write(
        session,
        user_id=principal.user_id,
        action=audit.ACTION_EMERGENCY_PROFILE_WRITTEN,
        resource_type="emergency_profile",
        resource_id=row.id,
        details={
            "key_version": row.key_version,
            "allergy_count": len(body.allergies),
            "medication_count": len(body.medications),
            "contact_count": len(body.contacts),
            "has_medical_notes": body.medical_notes is not None,
            "has_insurance": body.insurance is not None,
        },
    )

    return data_response(
        request,
        EmergencyProfileResponse(
            **body.to_sealed_payload(), updated_at=row.updated_at, key_version=row.key_version
        ),
    )


@router.delete(
    "/me/emergency-profile",
    summary="Delete the caller's emergency profile",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Deleted, or there was nothing to delete."},
        401: {"description": "No token, or a token that failed verification."},
        403: {"description": "The token is valid but does not carry the `travel` scope."},
    },
)
async def delete_emergency_profile(session: DbSession, principal: TravelPrincipal) -> Response:
    """Remove the profile outright.

    A hard delete, unlike everything else in this service: there is nothing here worth keeping for
    audit that the audit log does not already record, and the row is somebody's medical details.

    No consent check. Withdrawing data must never be harder than providing it, so this works even
    when the consent that authorised storage has already been withdrawn. 204 either way, so a
    client retrying after a timeout gets the same answer as the first attempt.
    """
    existed = await emergency_profiles.purge(session, owner_id=principal.user_id)
    if existed:
        await audit.write(
            session,
            user_id=principal.user_id,
            action=audit.ACTION_EMERGENCY_PROFILE_DELETED,
            resource_type="emergency_profile",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _require_emergency_consent(session: DbSession, principal: Principal) -> None:
    """Refuse unless the person has agreed to this specific use.

    Being signed in is not agreement to store medical data. The consent is separate, versioned and
    withdrawable, and this is the check that makes withdrawing it take effect immediately rather
    than whenever the purge job next runs.
    """
    consent = await consents.get_effective(
        session, owner_id=principal.user_id, consent_type=EMERGENCY_PROFILE_CONSENT
    )
    if consent is None:
        raise Forbidden(
            "Grant the emergency profile consent before storing or reading these details."
        )


def _encryption_unavailable() -> Exception:
    from app.errors.exceptions import DependencyUnavailable

    return DependencyUnavailable(
        "encryption",
        message="Emergency profile storage is unavailable. Nothing was stored in the clear.",
    )


__all__ = ["FieldErrorCode", "FieldErrorDetail", "ValidationFailed", "router"]
