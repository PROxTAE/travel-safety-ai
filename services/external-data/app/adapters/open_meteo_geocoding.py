"""Open-Meteo Geocoding adapter.

Mapping verified against `tests/fixtures/real-sanitized/open_meteo_geocoding/`.
The trap this adapter exists to absorb: the provider returns `latitude` and
`longitude` as separate floats, while every canonical coordinate in this project
is GeoJSON `[longitude, latitude]`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality
from app.domain.enums import DataStatus, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.records import GeocodeResult, GeoPoint, LocationRef
from app.transport.http import ProviderResponse

MAX_RESULTS = 20


@dataclass(slots=True)
class GeocodeQuery:
    name: str
    count: int = 5
    language: str = "en"
    country_code: str | None = None


class OpenMeteoPlace(BaseModel):
    # extra="ignore": the provider adds fields over time, and refusing an
    # otherwise valid response because of a new optional key would take the
    # capability down for no safety gain. Missing *required* fields still fail.
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    latitude: float
    longitude: float
    country_code: str | None = None
    country: str | None = None
    admin1: str | None = None
    timezone: str | None = None
    feature_code: str | None = None


class OpenMeteoGeocodingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Omitted entirely when nothing matches - not returned as an empty list.
    results: list[OpenMeteoPlace] = []


class OpenMeteoGeocodingAdapter(ProviderAdapter[GeocodeQuery, GeocodeResult]):
    def coverage(self, query: GeocodeQuery) -> CoverageDecision:
        if not query.name.strip():
            return CoverageDecision(False, "empty search term")
        if not 1 <= query.count <= MAX_RESULTS:
            return CoverageDecision(False, f"count must be between 1 and {MAX_RESULTS}")
        return CoverageDecision(True)

    def build_request(self, query: GeocodeQuery) -> ProviderRequest:
        params: dict[str, str | int] = {
            "name": query.name.strip(),
            "count": query.count,
            "language": query.language,
            "format": "json",
        }
        if query.country_code:
            params["countryCode"] = query.country_code.upper()

        return ProviderRequest(
            path_or_url=self.provider.entry.endpoints["search"],
            params=params,
            # Normalised so "Bangkok", " bangkok " and "BANGKOK" share an entry.
            cache_key_fields={
                "name": query.name.strip().casefold(),
                "count": query.count,
                "language": query.language,
                "country_code": (query.country_code or "").upper(),
            },
        )

    def validate(self, response: ProviderResponse) -> OpenMeteoGeocodingResponse:
        try:
            return OpenMeteoGeocodingResponse.model_validate(response.payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=(
                    "geocoding response did not match the expected shape: "
                    f"{exc.error_count()} errors"
                ),
            ) from exc

    def normalize(
        self,
        model: OpenMeteoGeocodingResponse,
        response: ProviderResponse,
        query: GeocodeQuery,
    ) -> list[GeocodeResult]:
        results: list[GeocodeResult] = []

        for place in model.results:
            location = LocationRef(
                place_id=f"{self.provider_id}:{place.id}",
                display_name=_display_name(place),
                coordinates=GeoPoint.from_lat_lon(place.latitude, place.longitude),
                country_code=place.country_code,
                admin1=place.admin1,
                timezone=place.timezone,
                provider=self.provider_id,
                confirmed_by_user=False,
            )

            flags = [QualityFlag.MISSING]
            notes = [
                "provider supplies no observation time: this is a static "
                "place-name index, not an observation"
            ]
            if place.timezone is None:
                flags.append(QualityFlag.INCOMPLETE)
                notes.append("provider returned no IANA timezone for this place")

            results.append(
                GeocodeResult(
                    location=location,
                    quality=DataQuality(
                        status=DataStatus.FRESH,
                        flags=flags,
                        completeness=_completeness(place),
                        notes=notes,
                    ),
                    source=self.provenance(
                        response,
                        provider_record_id=str(place.id),
                        observed_at=None,
                        payload_for_hash=place.model_dump(mode="json"),
                    ),
                )
            )

        return results

    def _dehydrate(self, records: list[GeocodeResult]) -> list[dict[str, object]]:
        return [record.model_dump(mode="json") for record in records]

    def _rehydrate(self, payload: object) -> list[GeocodeResult]:
        assert isinstance(payload, list)
        return [GeocodeResult.model_validate(item) for item in payload]


def _display_name(place: OpenMeteoPlace) -> str:
    """The provider has no preformatted label, so build one and drop the parts
    it did not supply rather than emitting "Bangkok, , ""."""
    parts = [place.name, place.admin1, place.country]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def _completeness(place: OpenMeteoPlace) -> float:
    optional = (place.country_code, place.admin1, place.timezone, place.country)
    return round(sum(1 for value in optional if value) / len(optional), 2)
