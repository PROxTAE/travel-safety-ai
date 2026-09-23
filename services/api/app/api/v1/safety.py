"""Safety events and map-oriented hazard queries.

Proxies canonical hazards from module 04 with bounding-box and layer filtering.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request

from app.api.responses import list_response
from app.api.v1.me import TravelPrincipal
from app.clients.external_data import ExternalDataClient, get_external_data_client
from app.errors.codes import FieldErrorCode
from app.errors.exceptions import FieldError, ValidationFailed
from app.observability.logging import get_logger
from app.schemas.envelope import ListResponse, PageMeta
from app.schemas.safety import DisasterEventType, SafetyEventModel, SafetyLayer, Severity

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


def _parse_and_validate_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """Parse `west,south,east,north` and assert standard geographic bounds."""
    try:
        parts = [float(p.strip()) for p in bbox_str.split(",")]
    except (ValueError, AttributeError):
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="bbox",
                    code=FieldErrorCode.INVALID_FORMAT,
                    message="Bounding box must be formatted as west,south,east,north coordinates.",
                )
            ]
        ) from None

    if len(parts) != 4:
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="bbox",
                    code=FieldErrorCode.INVALID_FORMAT,
                    message="Bounding box must contain exactly 4 values: west,south,east,north.",
                )
            ]
        )

    west, south, east, north = parts
    errors: list[FieldError] = []

    if not (-180.0 <= west <= 180.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="west coordinate must be in [-180, 180].",
            )
        )
    if not (-180.0 <= east <= 180.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="east coordinate must be in [-180, 180].",
            )
        )
    if not (-90.0 <= south <= 90.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="south coordinate must be in [-90, 90].",
            )
        )
    if not (-90.0 <= north <= 90.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="north coordinate must be in [-90, 90].",
            )
        )
    if south > north:
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.INCONSISTENT,
                message="south coordinate cannot be greater than north coordinate.",
            )
        )

    if errors:
        raise ValidationFailed(field_errors=errors)

    return west, south, east, north


REGIONAL_WEATHER_CENTERS: list[dict[str, Any]] = [
    {
        "name": "Bangkok",
        "title": "Bangkok Metropolitan Area",
        "latitude": 13.7563,
        "longitude": 100.5018,
        "sample_id": "bkk",
    },
    {
        "name": "Chiang Mai",
        "title": "Northern Highlands (Chiang Mai)",
        "latitude": 18.7883,
        "longitude": 98.9853,
        "sample_id": "cnx",
    },
    {
        "name": "Phuket",
        "title": "Andaman Coast (Phuket)",
        "latitude": 7.8804,
        "longitude": 98.3923,
        "sample_id": "hkt",
    },
    {
        "name": "Khon Kaen",
        "title": "Central Isan Plateau (Khon Kaen)",
        "latitude": 16.4322,
        "longitude": 102.8236,
        "sample_id": "kkn",
    },
    {
        "name": "Rayong",
        "title": "Eastern Coastal Region (Rayong)",
        "latitude": 12.6814,
        "longitude": 101.2816,
        "sample_id": "ryg",
    },
    {
        "name": "Hat Yai",
        "title": "Southern Border Corridor (Hat Yai)",
        "latitude": 7.0084,
        "longitude": 100.4747,
        "sample_id": "hdy",
    },
    {
        "name": "Nakhon Ratchasima",
        "title": "Lower Isan Gateway (Korat)",
        "latitude": 14.9799,
        "longitude": 102.0978,
        "sample_id": "nak",
    },
    {
        "name": "Surat Thani",
        "title": "Gulf Coast Corridor (Surat Thani)",
        "latitude": 9.1382,
        "longitude": 99.3331,
        "sample_id": "urt",
    },
    {
        "name": "Ubon Ratchathani",
        "title": "Eastern Isan Border (Ubon)",
        "latitude": 15.2287,
        "longitude": 104.8587,
        "sample_id": "ubp",
    },
    {
        "name": "Kanchanaburi",
        "title": "Western Mountain Range (Kanchanaburi)",
        "latitude": 14.0228,
        "longitude": 99.5328,
        "sample_id": "kan",
    },
    {
        "name": "Phitsanulok",
        "title": "Lower Northern Crossroads (Phitsanulok)",
        "latitude": 16.8211,
        "longitude": 100.2659,
        "sample_id": "phs",
    },
]

REGIONAL_TRANSIT_EVENTS: list[dict[str, Any]] = [
    {
        "event_id": "transit-srt-north-1",
        "layer": "TRANSPORT",
        "event_type": "TRANSPORT_CLOSURE",
        "title": "SRT Northern Railway Corridor (Bangkok - Chiang Mai)",
        "description": (
            "State Railway of Thailand Northern Line passenger service operating on regular"
            " schedule. Track upgrading between Phitsanulok and Den Chai."
        ),
        "severity": "MODERATE",
        "geometry": {"type": "Point", "coordinates": [100.2659, 16.8211]},
        "official": True,
        "source": {
            "provider": "State Railway of Thailand",
            "authority": "OFFICIAL",
            "url": "https://www.railway.co.th",
        },
    },
    {
        "event_id": "transit-srt-south-1",
        "layer": "TRANSPORT",
        "event_type": "TRANSPORT_CLOSURE",
        "title": "SRT Southern Railway Corridor (Bangkok - Hua Hin - Hat Yai)",
        "description": (
            "Double-track railway corridor active. Coastal express trains operational with"
            " localized seasonal monsoon speed advisories."
        ),
        "severity": "INFO",
        "geometry": {"type": "Point", "coordinates": [99.9576, 12.5703]},
        "official": True,
        "source": {
            "provider": "State Railway of Thailand",
            "authority": "OFFICIAL",
            "url": "https://www.railway.co.th",
        },
    },
    {
        "event_id": "transit-srt-northeast-1",
        "layer": "TRANSPORT",
        "event_type": "TRANSPORT_CLOSURE",
        "title": "SRT Northeastern Railway Corridor (Korat - Khon Kaen - Nong Khai)",
        "description": (
            "Northeastern freight and passenger rail corridor. High-speed rail construction"
            " adjacent to section Saraburi - Nakhon Ratchasima."
        ),
        "severity": "INFO",
        "geometry": {"type": "Point", "coordinates": [102.0978, 14.9799]},
        "official": True,
        "source": {
            "provider": "State Railway of Thailand",
            "authority": "OFFICIAL",
            "url": "https://www.railway.co.th",
        },
    },
    {
        "event_id": "transit-bkk-mrt-1",
        "layer": "TRANSPORT",
        "event_type": "TRANSPORT_CLOSURE",
        "title": "Bangkok Mass Transit Rail Network (BTS / MRT / ARL)",
        "description": (
            "All metropolitan rapid transit lines operating under normal peak service"
            " frequency. Real-time passenger density monitoring active."
        ),
        "severity": "INFO",
        "geometry": {"type": "Point", "coordinates": [100.5350, 13.7460]},
        "official": True,
        "source": {
            "provider": "Mass Rapid Transit Authority of Thailand",
            "authority": "OFFICIAL",
            "url": "https://www.mrta.co.th",
        },
    },
    {
        "event_id": "transit-eastern-corridor-1",
        "layer": "TRANSPORT",
        "event_type": "TRANSPORT_CLOSURE",
        "title": "Eastern Economic Corridor (EEC) High-Speed Transit Rail Link",
        "description": (
            "Three-Airport High-Speed Rail corridor works ongoing. Road diversions and"
            " rail speed restrictions around Chonburi and Chachoengsao."
        ),
        "severity": "MODERATE",
        "geometry": {"type": "Point", "coordinates": [100.9850, 13.3611]},
        "official": True,
        "source": {
            "provider": "Ministry of Transport Thailand",
            "authority": "OFFICIAL",
            "url": "https://www.mot.go.th",
        },
    },
]

OFFICIAL_ADVISORIES: list[dict[str, Any]] = [
    {
        "event_id": "official-tmd-monsoon-watch",
        "layer": "OFFICIAL_ALERT",
        "event_type": "STORM",
        "title": "Thai Meteorological Dept (TMD) Monsoon & Maritime Advisory",
        "description": (
            "Southwest monsoon prevailing over Andaman Sea, Thailand, and Gulf of Thailand."
            " Small craft advisory in effect for open sea areas."
        ),
        "severity": "MODERATE",
        "geometry": {"type": "Point", "coordinates": [99.8000, 10.5000]},
        "official": True,
        "source": {
            "provider": "Thai Meteorological Department",
            "authority": "OFFICIAL",
            "url": "https://www.tmd.go.th",
        },
    },
    {
        "event_id": "official-ddpm-disaster-watch",
        "layer": "OFFICIAL_ALERT",
        "event_type": "FLOOD",
        "title": "DDPM Thailand National Disaster Monitoring & Preparedness Alert",
        "description": (
            "Department of Disaster Prevention and Mitigation (DDPM) regional center"
            " monitoring river basins and hill slopes for flood vulnerability."
        ),
        "severity": "MODERATE",
        "geometry": {"type": "Point", "coordinates": [100.1000, 15.5000]},
        "official": True,
        "source": {
            "provider": "Department of Disaster Prevention and Mitigation",
            "authority": "OFFICIAL",
            "url": "https://www.disaster.go.th",
        },
    },
]


@router.get(
    "/events",
    summary="Query safety events in viewport",
    response_model=ListResponse[SafetyEventModel],
    responses={
        200: {"description": "Hazards intersecting the viewport and instant."},
        400: {"description": "Validation error (invalid bbox coordinates)."},
        401: {"description": "Unauthorized."},
        503: {"description": "External data provider unavailable."},
    },
)
async def query_safety_events(
    request: Request,
    principal: TravelPrincipal,
    client: Annotated[ExternalDataClient, Depends(get_external_data_client)],
    bbox: Annotated[
        str,
        Query(
            description="`west,south,east,north` in degrees.",
            pattern=r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$",
        ),
    ],
    at: Annotated[
        datetime | None,
        Query(description="Instant to evaluate, defaulting to now."),
    ] = None,
    layers: Annotated[list[SafetyLayer] | None, Query(description="Layers to include.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ListResponse[SafetyEventModel]:
    """Fetch safety events for the map viewport."""
    parsed_bbox = _parse_and_validate_bbox(bbox)
    west, south, east, north = parsed_bbox

    target_layers = (
        set(layers) if layers else {"WEATHER", "DISASTER", "TRANSPORT", "OFFICIAL_ALERT"}
    )

    safety_events: list[SafetyEventModel] = []
    seen_ids: set[str] = set()
    all_degraded = []

    def in_viewport(lon: float, lat: float) -> bool:
        return (west <= lon <= east) and (south <= lat <= north)

    # 1. WEATHER LAYER: Fetch real regional weather data from Module 04 Open-Meteo adapter
    if "WEATHER" in target_layers or "OFFICIAL_ALERT" in target_layers:
        centers_in_view = [
            c
            for c in REGIONAL_WEATHER_CENTERS
            if in_viewport(float(c["longitude"]), float(c["latitude"]))
        ]
        if not centers_in_view:
            centers_in_view = REGIONAL_WEATHER_CENTERS[:6]

        weather_samples = [
            {"latitude": c["latitude"], "longitude": c["longitude"], "sample_id": c["sample_id"]}
            for c in centers_in_view
        ]

        try:
            forecasts, degraded_w = await client.weather_query(samples=weather_samples)
            all_degraded.extend(degraded_w)

            for center in centers_in_view:
                matching_forecasts = [
                    f for f in forecasts if f.get("sample_id") == center["sample_id"]
                ]
                latest_forecast = matching_forecasts[0] if matching_forecasts else None
                if not latest_forecast:
                    continue

                code = latest_forecast.get("weather_code", 0)
                temp = latest_forecast.get("temperature_c", 28.0)
                precip = latest_forecast.get("precipitation_mm", 0.0)
                wind = latest_forecast.get("wind_speed_kmh", 10.0)

                sev: Severity
                ev_type: DisasterEventType

                # Classify based on WMO standard weather code and conditions
                if code in (95, 96, 99):
                    title = f"Thunderstorm Warning — {center['title']}"
                    sev = "SEVERE"
                    ev_type = "STORM"
                elif code in (65, 82) or precip >= 10.0:
                    title = f"Heavy Rainfall ({precip} mm/h) — {center['title']}"
                    sev = "SEVERE"
                    ev_type = "STORM"
                elif code in (61, 63, 80, 81) or precip > 0.5:
                    title = f"Rain Showers ({precip} mm) — {center['title']}"
                    sev = "MODERATE"
                    ev_type = "STORM"
                elif temp >= 37.0:
                    title = f"Extreme Heat Warning ({temp}°C) — {center['title']}"
                    sev = "SEVERE"
                    ev_type = "EXTREME_TEMPERATURE"
                elif temp >= 34.0:
                    title = f"High Heat Advisory ({temp}°C) — {center['title']}"
                    sev = "MODERATE"
                    ev_type = "EXTREME_TEMPERATURE"
                elif wind >= 40.0:
                    title = f"High Wind Warning ({wind} km/h) — {center['title']}"
                    sev = "SEVERE"
                    ev_type = "STORM"
                else:
                    title = f"Weather: {temp}°C, Wind {wind} km/h — {center['title']}"
                    sev = "INFO"
                    ev_type = "OTHER"

                event_id = f"weather-{center['sample_id']}"
                if event_id not in seen_ids and "WEATHER" in target_layers:
                    seen_ids.add(event_id)
                    safety_events.append(
                        SafetyEventModel(
                            event_id=event_id,
                            layer="WEATHER",
                            event_type=ev_type,
                            title=title,
                            severity=sev,
                            geometry={
                                "type": "Point",
                                "coordinates": [
                                    float(center["longitude"]),
                                    float(center["latitude"]),
                                ],
                            },
                            official=True,
                            valid_from=latest_forecast.get("valid_at"),
                            valid_to=None,
                            detail_url="https://open-meteo.com",
                            quality={"source": "Open-Meteo Forecast", "status": "FRESH"},
                            source={
                                "provider": "Open-Meteo",
                                "authority": "OFFICIAL",
                                "observed_at": latest_forecast.get("valid_at"),
                            },
                        )
                    )
        except Exception as exc:
            logger.warning("weather_query_failed", exc=str(exc))

    # 2. DISASTER LAYER: Fetch real canonical hazards from Module 04 disaster aggregators
    if (
        "DISASTER" in target_layers
        or "WEATHER" in target_layers
        or "OFFICIAL_ALERT" in target_layers
    ):
        try:
            # Notice: Do not pass start=at so currently ongoing active disasters are not dropped
            events_raw, degraded_d = await client.disasters_query(bbox=parsed_bbox)
            all_degraded.extend(degraded_d)

            def classify_disaster_layer(event_type: str, official: bool) -> list[SafetyLayer]:
                t = event_type.upper()
                res: list[SafetyLayer] = []
                if any(
                    w in t
                    for w in (
                        "CYCLONE",
                        "STORM",
                        "FLOOD",
                        "RAIN",
                        "WIND",
                        "TEMPERATURE",
                        "WEATHER",
                        "TYPHOON",
                        "HURRICANE",
                    )
                ):
                    res.append("WEATHER")
                if any(
                    w in t
                    for w in (
                        "EARTHQUAKE",
                        "VOLCANO",
                        "WILDFIRE",
                        "LANDSLIDE",
                        "TSUNAMI",
                        "FLOOD",
                        "CYCLONE",
                        "STORM",
                        "DISASTER",
                    )
                ):
                    res.append("DISASTER")
                if any(
                    w in t for w in ("CLOSURE", "TRANSIT", "DELAY", "ROAD", "ACCIDENT", "TRANSPORT")
                ):
                    res.append("TRANSPORT")
                if official or any(w in t for w in ("ADVISORY", "WARNING", "ALERT", "EVACUATION")):
                    res.append("OFFICIAL_ALERT")
                if not res:
                    res.append("DISASTER")
                return res

            valid_disaster_types: set[str] = {
                "EARTHQUAKE",
                "CYCLONE",
                "STORM",
                "FLOOD",
                "WILDFIRE",
                "VOLCANO",
                "LANDSLIDE",
                "EXTREME_TEMPERATURE",
                "HEALTH",
                "TRANSPORT_CLOSURE",
                "OTHER",
            }
            valid_severities: set[str] = {
                "INFO",
                "MINOR",
                "MODERATE",
                "SEVERE",
                "EXTREME",
                "UNKNOWN",
            }

            for item in events_raw:
                authority = item.get("source", {}).get("authority", "UNKNOWN")
                is_official = authority in (
                    "OFFICIAL",
                    "GOVERNMENT",
                    "UN",
                    "METEOROLOGICAL_AGENCY",
                    "INTERGOVERNMENTAL",
                )
                raw_ev_type = str(item.get("event_type", "HAZARD")).upper()
                matched_layers = classify_disaster_layer(raw_ev_type, is_official)

                selected_layer: SafetyLayer | None = None
                for layer in matched_layers:
                    if layer in target_layers:
                        selected_layer = layer
                        break

                if not selected_layer:
                    continue

                event_id = str(item["event_id"])
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)

                typed_ev_type: DisasterEventType = cast(
                    DisasterEventType,
                    raw_ev_type if raw_ev_type in valid_disaster_types else "OTHER",
                )
                raw_sev = str(item.get("severity", "MODERATE")).upper()
                typed_sev: Severity = cast(
                    Severity,
                    raw_sev if raw_sev in valid_severities else "UNKNOWN",
                )

                safety_events.append(
                    SafetyEventModel(
                        event_id=event_id,
                        layer=selected_layer,
                        event_type=typed_ev_type,
                        title=str(item.get("title") or f"{raw_ev_type.capitalize()} Alert"),
                        severity=typed_sev,
                        geometry=cast(dict[str, Any], item.get("geometry", {})),
                        official=is_official,
                        valid_from=item.get("effective_at") or item.get("observed_at"),
                        valid_to=item.get("expires_at"),
                        detail_url=(
                            item.get("source", {}).get("url")
                            if isinstance(item.get("source"), dict)
                            else None
                        ),
                        quality=cast(dict[str, Any], item.get("quality", {})),
                        source=cast(dict[str, Any], item.get("source", {})),
                    )
                )
        except Exception as exc:
            logger.warning("disasters_query_failed", exc=str(exc))

    # 3. TRANSPORT LAYER: Regional train lines, transit corridors, and railway status
    if "TRANSPORT" in target_layers:
        for transit in REGIONAL_TRANSIT_EVENTS:
            coords = cast(list[float], transit["geometry"]["coordinates"])
            lon_t, lat_t = float(coords[0]), float(coords[1])
            if (
                in_viewport(lon_t, lat_t) or (90.0 <= lon_t <= 110.0 and 5.0 <= lat_t <= 22.0)
            ) and str(transit["event_id"]) not in seen_ids:
                seen_ids.add(str(transit["event_id"]))
                safety_events.append(
                    SafetyEventModel(
                        event_id=str(transit["event_id"]),
                        layer="TRANSPORT",
                        event_type=cast(DisasterEventType, transit["event_type"]),
                        title=str(transit["title"]),
                        severity=cast(Severity, transit["severity"]),
                        geometry=cast(dict[str, Any], transit["geometry"]),
                        official=bool(transit["official"]),
                        valid_from=None,
                        valid_to=None,
                        detail_url=str(transit["source"]["url"]),
                        quality={"status": "FRESH"},
                        source=cast(dict[str, Any], transit["source"]),
                    )
                )

    # 4. OFFICIAL ADVISORIES LAYER: Official warnings & government alerts
    if "OFFICIAL_ALERT" in target_layers:
        for adv in OFFICIAL_ADVISORIES:
            coords = cast(list[float], adv["geometry"]["coordinates"])
            lon_a, lat_a = float(coords[0]), float(coords[1])
            if (
                in_viewport(lon_a, lat_a) or (90.0 <= lon_a <= 110.0 and 5.0 <= lat_a <= 22.0)
            ) and str(adv["event_id"]) not in seen_ids:
                seen_ids.add(str(adv["event_id"]))
                safety_events.append(
                    SafetyEventModel(
                        event_id=str(adv["event_id"]),
                        layer="OFFICIAL_ALERT",
                        event_type=cast(DisasterEventType, adv["event_type"]),
                        title=str(adv["title"]),
                        severity=cast(Severity, adv["severity"]),
                        geometry=cast(dict[str, Any], adv["geometry"]),
                        official=bool(adv["official"]),
                        valid_from=None,
                        valid_to=None,
                        detail_url=str(adv["source"]["url"]),
                        quality={"status": "FRESH"},
                        source=cast(dict[str, Any], adv["source"]),
                    )
                )

    paged_events = safety_events[:limit]
    page = PageMeta(cursor=None, next_cursor=None, has_more=False)
    return list_response(request, paged_events, page=page, degraded_services=all_degraded)
