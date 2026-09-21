"""Place search, proxied to the external-data service.

This endpoint exists so the browser never talks to a geocoding provider and never holds a provider
key. It forwards a query, applies the caller's locale, and returns what module 04 resolved — with
the provider that resolved it attached, so a later trip records where its coordinates came from.

Two behaviours are deliberate and easy to get wrong:

* **An empty list means the provider found nothing.** A provider that is down produces 503. Those
  are different facts, and collapsing them into "no results" would leave someone believing their
  destination does not exist.
* **`confirmed_by_user` is never true here.** Confirmation is something a person does on a map.
  This service will not assert it on their behalf, and a trip cannot be saved without it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.responses import list_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.clients.external_data import get_external_data_client
from app.errors.codes import FieldErrorCode
from app.errors.exceptions import FieldError, ValidationFailed
from app.observability.logging import get_logger
from app.repositories import user_profiles
from app.schemas.envelope import ListResponse
from app.schemas.location import LocationRef

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])


@router.get(
    "/search",
    summary="Search places with a real geocoding provider",
    response_model=ListResponse[LocationRef],
    responses={
        400: {"description": "A query parameter failed validation."},
        401: {"description": "No token, or a token that failed verification."},
        503: {"description": "No geocoding provider is configured or reachable."},
        504: {"description": "The geocoding provider did not answer in time."},
    },
)
async def search_locations(
    request: Request,
    response: Response,
    session: DbSession,
    principal: TravelPrincipal,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    locale: Annotated[str | None, Query(max_length=35)] = None,
    country_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> ListResponse[LocationRef]:
    """Resolve free text to candidate places.

    The language defaults to the caller's stored profile locale, so someone who set their account
    to Thai gets Thai place names without the client having to remember to ask for them.

    If the caller disconnects, the `await` below is cancelled and the outbound request is cancelled
    with it — the provider quota is not spent finishing an answer nobody will read.
    """
    if country_code is not None:
        normalised = country_code.upper()
        if not normalised.isalpha():
            raise ValidationFailed(
                field_errors=[
                    FieldError(
                        path="country_code",
                        code=FieldErrorCode.INVALID_FORMAT,
                        message="Use an ISO-3166-1 alpha-2 code, for example TH.",
                    )
                ]
            )
        country_code = normalised

    language = _language_for(locale) if locale else None
    if language is None:
        profile = await user_profiles.get_owned(session, owner_id=principal.user_id)
        language = _language_for(profile.locale if profile else "en-US") or "en"

    client = get_external_data_client(request)
    results = await client.geocode_search(
        query=q,
        limit=limit,
        language=language,
        country_code=country_code,
    )

    locations = [_to_location(result) for result in results]
    locations = [location for location in locations if location is not None]

    # Private, because the query is something a person typed and the response is shaped by their
    # profile locale. A shared cache would serve one user's search to another.
    cache_seconds = request.app.state.settings.location_search_cache_seconds
    response.headers["Cache-Control"] = (
        f"private, max-age={cache_seconds}" if cache_seconds else "no-store"
    )
    response.headers["Vary"] = "Authorization, Accept-Language"

    return list_response(request, locations)  # type: ignore[arg-type]


def _language_for(locale: str) -> str | None:
    """The language subtag of a BCP-47 tag: `th-TH` becomes `th`.

    Module 04's provider takes a language, not a locale. Returns None for something that is not a
    tag at all, so the caller falls back rather than forwarding nonsense to the provider.
    """
    primary = locale.split("-", 1)[0].strip().lower()
    if not (2 <= len(primary) <= 3) or not primary.isalpha():
        return None
    return primary


def _to_location(result: object) -> LocationRef | None:
    """Reshape one module-04 result into the public `LocationRef`.

    Module 04 returns a `GeocodeResult`: the location plus the quality and provenance it was
    fetched with. The public contract for this endpoint carries the location alone — provenance
    belongs to the assessment that uses it, and the browser has no use for a content hash.

    A record that does not fit the contract is dropped rather than passed through, and the drop is
    logged. One malformed entry should not fail a search that returned nine good ones, but it must
    not reach the client half-validated either.
    """
    if not isinstance(result, dict):
        return None

    payload = result.get("location", result)
    try:
        return LocationRef.model_validate(
            {
                "place_id": payload.get("place_id"),
                "display_name": payload.get("display_name"),
                "coordinates": payload.get("coordinates"),
                "country_code": payload.get("country_code"),
                "admin1": payload.get("admin1"),
                "timezone": payload.get("timezone"),
                "provider": payload.get("provider"),
                # Never taken from the provider's answer. A place becomes confirmed when a person
                # accepts the pin, and no upstream service can assert that for them.
                "confirmed_by_user": False,
            }
        )
    except (AttributeError, ValueError) as exc:
        logger.warning(
            "geocode_result_discarded",
            event_type="dependency",
            dependency="external-data",
            reason=type(exc).__name__,
        )
        return None
