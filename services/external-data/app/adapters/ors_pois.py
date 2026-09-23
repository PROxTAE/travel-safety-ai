"""openrouteservice POIs adapter - the emergency directory.

Mapping verified against `tests/fixtures/real-sanitized/openrouteservice/`,
captured live on 2026-09-20. The category ids below were read from the
provider's own `{"request": "list"}` response rather than guessed, because
guessing is exactly how this goes wrong: the first attempt used the
`category_group_ids` for a group that turned out to be restaurants, and a
"nearest hospital" search came back with a pub 250 m away.

What this adapter is careful about:

1. **The data is weak and the shared context says so.** OSM tags for police,
   hospitals and especially embassies are "frequently stale or missing", and
   this must never stand in for an official phone directory. So `name` is
   nullable, everything carries quality flags, and a record with no name is
   flagged rather than dropped - a hospital that exists but is untagged is
   still worth showing on a map.
2. **`distance` is straight-line metres**, not travel distance. A hospital
   400 m away across a motorway is not four hundred metres away. The field is
   named `distance_m` and documented, never presented as travel time.
3. **An empty result is not an outage.** OSM coverage is thin in much of the
   world; zero POIs means "nothing tagged here", which is a coverage fact the
   caller needs, not an error to retry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality
from app.domain.enums import DataStatus, PlaceType, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.queries import NearbyPlacesQuery
from app.domain.records import EmergencyPlace, GeoPoint
from app.transport.http import ProviderResponse

# Read from the provider's own category list endpoint on 2026-09-20.
CATEGORY_BY_PLACE_TYPE: dict[PlaceType, int] = {
    PlaceType.CLINIC: 202,
    PlaceType.DOCTOR: 204,
    PlaceType.HOSPITAL: 206,
    PlaceType.PHARMACY: 208,
    PlaceType.EMBASSY: 361,
    PlaceType.FIRE_STATION: 367,
    PlaceType.POLICE: 369,
    PlaceType.TOWNHALL: 374,
}
PLACE_TYPE_BY_CATEGORY: dict[int, PlaceType] = {
    category: place_type for place_type, category in CATEGORY_BY_PLACE_TYPE.items()
}

# What the module plan actually asks for. Used when the caller names no types.
DEFAULT_PLACE_TYPES: tuple[PlaceType, ...] = (
    PlaceType.HOSPITAL,
    PlaceType.POLICE,
    PlaceType.EMBASSY,
)

# The provider's buffer parameter is metres and it rejects very large values;
# The live endpoint rejects buffer values above 2,000 metres.
MAX_RADIUS_M = 2_000

# OSM edits land continuously but the extract behind the POI service is rebuilt
# on its own schedule, and the response carries no build date - only the time it
# answered. So there is no freshness number to report, and claiming one would be
# inventing it. The record says PARTIAL and says why.
_NO_BUILD_DATE_NOTE = (
    "the POI service reports no extract build date, so how old the underlying "
    "OpenStreetMap data is cannot be measured here"
)


class OrsPoiCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category_name: str | None = None
    category_group: str | None = None


class OrsPoiProperties(BaseModel):
    model_config = ConfigDict(extra="ignore")

    osm_id: int | None = None
    osm_type: int | None = None
    distance: float | None = None
    category_ids: dict[str, OrsPoiCategory] = Field(default_factory=dict)
    osm_tags: dict[str, Any] = Field(default_factory=dict)


class OrsPoiGeometry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["Point"]
    coordinates: list[float]


class OrsPoiFeature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["Feature"]
    geometry: OrsPoiGeometry
    properties: OrsPoiProperties


class OrsPoiInformation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attribution: str | None = None
    version: str | None = None
    timestamp: int | None = None


class OrsPoiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["FeatureCollection"]
    features: list[OrsPoiFeature]
    information: OrsPoiInformation = Field(default_factory=OrsPoiInformation)


class OrsPoisAdapter(ProviderAdapter[NearbyPlacesQuery, EmergencyPlace]):
    """Police / hospital / embassy lookup around a coordinate."""

    # ------------------------------------------------------------- coverage
    def coverage(self, query: NearbyPlacesQuery) -> CoverageDecision:
        if query.radius_m <= 0:
            return CoverageDecision(False, "radius must be greater than zero")
        if query.radius_m > MAX_RADIUS_M:
            return CoverageDecision(
                False,
                f"the provider does not search beyond {MAX_RADIUS_M} m, "
                f"{query.radius_m} m requested",
            )
        unknown = [
            place_type
            for place_type in query.place_types
            if place_type not in CATEGORY_BY_PLACE_TYPE
        ]
        if unknown:
            names = ", ".join(str(place_type) for place_type in unknown)
            return CoverageDecision(False, f"this provider has no category for: {names}")
        return CoverageDecision(True)

    # -------------------------------------------------------------- request
    def build_request(self, query: NearbyPlacesQuery) -> ProviderRequest:
        place_types = tuple(query.place_types) or DEFAULT_PLACE_TYPES
        category_ids = sorted(CATEGORY_BY_PLACE_TYPE[place_type] for place_type in place_types)
        body: dict[str, Any] = {
            "request": "pois",
            "geometry": {
                "geojson": {
                    "type": "Point",
                    "coordinates": [query.longitude, query.latitude],
                },
                "buffer": query.radius_m,
            },
            "filters": {"category_ids": category_ids},
            "limit": query.limit,
        }
        return ProviderRequest(
            path_or_url=self.provider.entry.endpoints.get("pois", "/pois"),
            method="POST",
            json_body=body,
            headers=self._auth_headers(),
            cache_key_fields={
                # Rounded to about 10 m. Full precision would make every cache
                # key unique and, per the security invariants, a raw coordinate
                # is personal data that should not become a cache key.
                "lon": round(query.longitude, 4),
                "lat": round(query.latitude, 4),
                "radius_m": query.radius_m,
                "categories": category_ids,
                "limit": query.limit,
            },
        )

    def _auth_headers(self) -> dict[str, str]:
        from app.settings import get_settings

        settings = get_settings()
        for name in self.provider.entry.credential.env_names:
            secret = settings.credential_for(name)
            if secret is not None:
                return {
                    "Authorization": secret.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept": "application/geo+json, application/json",
                }
        raise ProviderError(
            ProviderErrorCode.PROVIDER_AUTH,
            self.provider_id,
            message="emergency directory credential is not configured",
        )

    # ------------------------------------------------------------- validate
    def validate(self, response: ProviderResponse) -> OrsPoiResponse:
        payload = response.payload
        if isinstance(payload, dict) and "error" in payload:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=f"provider error: {payload['error']}",
            )
        try:
            return OrsPoiResponse.model_validate(payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=f"unexpected POI payload: {exc.error_count()} problems",
            ) from exc

    # ------------------------------------------------------------ normalize
    def normalize(
        self,
        model: OrsPoiResponse,
        response: ProviderResponse,
        query: NearbyPlacesQuery,
    ) -> list[EmergencyPlace]:
        fetched_at = datetime.fromtimestamp(response.fetched_at, tz=UTC)
        places: list[EmergencyPlace] = []

        for feature in model.features:
            coordinates = feature.geometry.coordinates
            if len(coordinates) < 2:
                continue
            properties = feature.properties
            place_type, provider_category = _classify(properties)
            tags = properties.osm_tags
            osm_id = properties.osm_id

            places.append(
                EmergencyPlace(
                    poi_id=f"{self.provider_id}:osm:{osm_id}"
                    if osm_id is not None
                    else f"{self.provider_id}:{coordinates[0]:.6f},{coordinates[1]:.6f}",
                    poi_type=place_type,
                    name=_text(tags.get("name")),
                    location=GeoPoint(coordinates=(float(coordinates[0]), float(coordinates[1]))),
                    distance_m=properties.distance,
                    address=_address(tags),
                    phone=_text(tags.get("phone") or tags.get("contact:phone")),
                    website=_text(tags.get("website") or tags.get("contact:website")),
                    opening_hours=_text(tags.get("opening_hours")),
                    provider_category=provider_category,
                    quality=_quality(place_type, properties, fetched_at),
                    source=self.provenance(
                        response,
                        provider_record_id=str(osm_id) if osm_id is not None else None,
                        # A POI record has no observation time: OSM does not
                        # publish when a tag was last confirmed on the ground.
                        observed_at=None,
                        source_url=_osm_url(properties),
                        payload_for_hash=feature.model_dump(mode="json"),
                    ),
                )
            )
        return places

    def _dehydrate(self, records: list[EmergencyPlace]) -> Any:
        return [record.model_dump(mode="json") for record in records]

    def _rehydrate(self, payload: Any) -> list[EmergencyPlace]:
        return [EmergencyPlace.model_validate(item) for item in payload]


def _classify(properties: OrsPoiProperties) -> tuple[PlaceType, str | None]:
    """Provider category -> PlaceType.

    A POI can carry several categories; the first one we recognise wins, and an
    unrecognised one becomes OTHER while the provider's own name is kept so the
    gap can be diagnosed without another call.
    """
    provider_category: str | None = None
    for raw_id, category in properties.category_ids.items():
        if provider_category is None:
            provider_category = category.category_name
        try:
            numeric = int(raw_id)
        except ValueError:
            continue
        place_type = PLACE_TYPE_BY_CATEGORY.get(numeric)
        if place_type is not None:
            return place_type, category.category_name or provider_category
    return PlaceType.OTHER, provider_category


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _address(tags: dict[str, Any]) -> str | None:
    """OSM addresses arrive as separate tags, not one string."""
    parts = [
        _text(tags.get(key))
        for key in (
            "addr:housenumber",
            "addr:street",
            "addr:subdistrict",
            "addr:district",
            "addr:city",
            "addr:postcode",
        )
    ]
    present = [part for part in parts if part]
    return " ".join(present) if present else None


def _osm_url(properties: OrsPoiProperties) -> str | None:
    """Link to the OSM object so a consumer can check or correct the record.

    `osm_type` is 1/2/3 for node/way/relation in this API.
    """
    if properties.osm_id is None:
        return None
    kind = {1: "node", 2: "way", 3: "relation"}.get(properties.osm_type or 0, "node")
    return f"https://www.openstreetmap.org/{kind}/{properties.osm_id}"


def _quality(
    place_type: PlaceType, properties: OrsPoiProperties, fetched_at: datetime
) -> DataQuality:
    flags: list[QualityFlag] = []
    notes: list[str] = [_NO_BUILD_DATE_NOTE]
    tags = properties.osm_tags

    if not _text(tags.get("name")):
        flags.append(QualityFlag.MISSING)
        notes.append("the OpenStreetMap record has no name tag")
    if not (tags.get("phone") or tags.get("contact:phone")):
        flags.append(QualityFlag.INCOMPLETE)
        notes.append(
            "no phone number in OpenStreetMap - this is not an official "
            "emergency directory and must not be presented as one"
        )
    if place_type is PlaceType.OTHER:
        flags.append(QualityFlag.INFERRED)
        notes.append("the provider category does not map to a known place type")
    if place_type is PlaceType.EMBASSY:
        flags.append(QualityFlag.STALE)
        notes.append(
            "embassy records in OpenStreetMap are documented as especially "
            "unreliable; verify against the ministry listing before relying on it"
        )

    # PARTIAL, not FRESH: the data arrived fine, but its age is unknown, and
    # FRESH would assert something nobody measured.
    return DataQuality(
        status=DataStatus.PARTIAL,
        flags=sorted(set(flags)),
        notes=notes,
    )
