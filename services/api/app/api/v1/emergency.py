"""Emergency directory and nearby facilities endpoints.

Serves reviewed official emergency numbers and nearby facilities with active location consent check.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_, select

from app.api.responses import data_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.clients.external_data import ExternalDataClient, get_external_data_client
from app.db.models.identity import Consent
from app.domain import trip as rules
from app.domain.emergency_directory import get_emergency_contacts_for_location
from app.errors.exceptions import Forbidden
from app.observability.logging import get_logger
from app.schemas.emergency import (
    EmergencyPoiModel,
    EmergencyPoiType,
    OfficialContactModel,
)
from app.schemas.envelope import DataResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/emergency", tags=["emergency"])


@router.get(
    "/contacts",
    summary="Verified emergency numbers for a location",
    response_model=DataResponse[list[OfficialContactModel]],
    responses={
        200: {"description": "Verified official contacts list."},
        400: {"description": "Validation error (invalid coordinates)."},
        401: {"description": "Unauthorized."},
        503: {"description": "Dependency unavailable."},
    },
)
async def get_emergency_contacts(
    request: Request,
    principal: TravelPrincipal,
    latitude: Annotated[float, Query(ge=-90.0, le=90.0)],
    longitude: Annotated[float, Query(ge=-180.0, le=180.0)],
    locale: Annotated[str | None, Query()] = None,
) -> DataResponse[list[OfficialContactModel]]:
    """Return reviewed emergency numbers for a location."""
    contacts = get_emergency_contacts_for_location(
        lat=latitude,
        lon=longitude,
        locale=locale or "en-US",
    )

    return data_response(request, contacts)


@router.get(
    "/nearby",
    summary="Nearby hospitals, police stations or embassies",
    response_model=DataResponse[list[EmergencyPoiModel]],
    responses={
        200: {"description": "Facilities found, nearest first."},
        400: {"description": "Validation error."},
        401: {"description": "Unauthorized."},
        403: {"description": "No active location consent."},
        503: {"description": "Places provider unavailable."},
    },
)
async def get_emergency_nearby(
    request: Request,
    principal: TravelPrincipal,
    session: DbSession,
    client: Annotated[ExternalDataClient, Depends(get_external_data_client)],
    latitude: Annotated[float, Query(ge=-90.0, le=90.0)],
    longitude: Annotated[float, Query(ge=-180.0, le=180.0)],
    poi_type: Annotated[EmergencyPoiType, Query(alias="type")],
    radius_m: Annotated[int, Query(ge=100, le=50000)] = 5000,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DataResponse[list[EmergencyPoiModel]]:
    """Search nearby facilities using module 04, enforcing active location consent."""
    # Check active location consent for user
    now = rules.now_utc()
    stmt = (
        select(Consent)
        .where(
            Consent.user_id == principal.user_id,
            Consent.type.in_(["LOCATION_ONCE", "LOCATION_LIVE"]),
            Consent.granted.is_(True),
            Consent.revoked_at.is_(None),
            or_(Consent.expires_at.is_(None), Consent.expires_at > now),
        )
        .limit(1)
    )
    res = await session.execute(stmt)
    consent = res.scalar_one_or_none()
    if consent is None:
        raise Forbidden(
            "An active LOCATION_ONCE or LOCATION_LIVE consent is required to look "
            "up nearby emergency facilities."
        )

    places_raw = await client.places_nearby(
        latitude=latitude,
        longitude=longitude,
        place_types=[poi_type],
        radius_m=radius_m,
        limit=limit,
    )

    pois: list[EmergencyPoiModel] = []
    for item in places_raw:
        loc = item.get("location", {"type": "Point", "coordinates": [longitude, latitude]})
        pois.append(
            EmergencyPoiModel(
                poi_id=item.get("poi_id") or item.get("place_id", ""),
                poi_type=item.get("poi_type") or item.get("place_type", poi_type),
                name=item.get("name"),
                location=loc,
                address=item.get("address"),
                phone=item.get("phone"),
                distance_m=item.get("distance_m"),
                open_now=item.get("open_now"),
                quality=item.get("quality", {}),
                source=item.get("source", {}),
            )
        )

    return data_response(request, pois)
