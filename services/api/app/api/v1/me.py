"""The caller's own profile.

Phase 2 implements the read only, because it is the endpoint that proves the whole authentication
chain end to end: a real Keycloak token resolves to a local user, and that user sees their own row
and nobody else's.

What is not here yet, and why the response still tells the truth about it:

* `consents` is an empty list because consent records are phase 3 and no consent can be granted
  yet. The list is accurate, not a placeholder.
* `has_emergency_profile` is `false` for the same reason — no profile can exist.
* `PATCH /api/v1/me` is phase 3.

There is no `user_id` path parameter and there never will be. The row is selected by the id in the
principal, so "read someone else's profile" is not an operation this endpoint can express.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.responses import data_response
from app.auth.dependencies import DbSession, require_scopes
from app.auth.principal import Principal
from app.errors.exceptions import NotFound
from app.repositories import user_profiles
from app.schemas.envelope import DataResponse
from app.schemas.user import UserProfileModel

router = APIRouter(prefix="/api/v1", tags=["identity"])

#: The scope a browser session must carry to touch anything under `/api/v1`.
TRAVEL_SCOPE = "travel"

TravelPrincipal = Annotated[Principal, Depends(require_scopes(TRAVEL_SCOPE))]


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
    request: Request,
    session: DbSession,
    principal: TravelPrincipal,
) -> DataResponse[UserProfileModel]:
    """Read the profile belonging to the caller.

    The row is created on first sign-in by the authentication dependency, so a 404 here means the
    account was deleted between authenticating and reading. Rare, but it must not be reported as
    an empty profile.
    """
    profile = await user_profiles.get_owned(session, owner_id=principal.user_id)
    if profile is None:
        raise NotFound

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
            consents=[],
            has_emergency_profile=False,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            deleted_at=profile.deleted_at,
        ),
    )
