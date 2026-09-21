"""Shared enums from 00_API_AND_DATA_CONTRACTS.md § 2.

Only the subset module 04 produces or consumes. Values are uppercase strings on
the wire. An unrecognised provider value maps to UNKNOWN — never to a new
string invented at runtime.
"""

from __future__ import annotations

from enum import StrEnum


class DataStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICTING = "CONFLICTING"
    PARTIAL = "PARTIAL"


class Severity(StrEnum):
    INFO = "INFO"
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class EventType(StrEnum):
    """Contract § 3.7. A provider value with no equivalent maps to OTHER."""

    EARTHQUAKE = "EARTHQUAKE"
    CYCLONE = "CYCLONE"
    STORM = "STORM"
    FLOOD = "FLOOD"
    WILDFIRE = "WILDFIRE"
    VOLCANO = "VOLCANO"
    LANDSLIDE = "LANDSLIDE"
    EXTREME_TEMPERATURE = "EXTREME_TEMPERATURE"
    HEALTH = "HEALTH"
    TRANSPORT_CLOSURE = "TRANSPORT_CLOSURE"
    OTHER = "OTHER"


class SourceAuthority(StrEnum):
    OFFICIAL = "OFFICIAL"
    INTERGOVERNMENTAL = "INTERGOVERNMENTAL"
    LICENSED_PROVIDER = "LICENSED_PROVIDER"
    COMMUNITY = "COMMUNITY"
    UNKNOWN = "UNKNOWN"


class ProviderKind(StrEnum):
    GEOCODING = "GEOCODING"
    WEATHER = "WEATHER"
    ROUTE = "ROUTE"
    FLIGHT = "FLIGHT"
    TRANSIT = "TRANSIT"
    DISASTER = "DISASTER"
    EMERGENCY_DIRECTORY = "EMERGENCY_DIRECTORY"


class QualityFlag(StrEnum):
    MISSING = "MISSING"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"
    INFERRED = "INFERRED"
    INCOMPLETE = "INCOMPLETE"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"


class ProviderStatus(StrEnum):
    """Registry status. Only ACTIVE may be called."""

    ACTIVE = "ACTIVE"
    PENDING_CREDENTIAL = "PENDING_CREDENTIAL"
    PENDING_LEAD_APPROVAL = "PENDING_LEAD_APPROVAL"
    UNAVAILABLE = "UNAVAILABLE"


class HealthState(StrEnum):
    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    UNKNOWN = "UNKNOWN"


class RiskLevel(StrEnum):
    """Contract § 2. Module 04 only ever emits UNKNOWN.

    Deciding that a route is risky means intersecting it with hazards and
    weather, which is module 05/06 work, and turning that into an action is
    module 07's. A routing provider knows the road network and nothing about
    danger, so anything other than UNKNOWN here would be invented.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class TravelMode(StrEnum):
    FLIGHT = "FLIGHT"
    TRAIN = "TRAIN"
    BUS = "BUS"
    CAR = "CAR"
    WALK = "WALK"
    BICYCLE = "BICYCLE"
    MULTIMODAL = "MULTIMODAL"


class RouteLabel(StrEnum):
    """Contract § 3.8.

    Module 04 labels by what the provider returned - the first route is the one
    ORS considers best for the requested profile, the rest are its alternatives.
    RECOMMENDED and LOWEST_RISK are rankings that depend on risk, so they are
    assigned downstream by `/routes/evaluate`, never here.
    """

    ORIGINAL = "ORIGINAL"
    RECOMMENDED = "RECOMMENDED"
    FASTEST = "FASTEST"
    LOWEST_RISK = "LOWEST_RISK"
    ALTERNATIVE = "ALTERNATIVE"


class PlaceType(StrEnum):
    """Emergency directory categories module 04 resolves.

    Not in the shared contract yet - `/internal/v1/places/nearby` is specified
    as returning "sourced GeoJSON POIs" without naming the categories. These are
    the ones the module plan calls for (police / hospital / embassy) plus the
    neighbours OSM tags them alongside. Raised for the Lead in the PR; until it
    is in § 2, consumers must treat OTHER as "the provider said something we do
    not model".
    """

    HOSPITAL = "HOSPITAL"
    CLINIC = "CLINIC"
    DOCTOR = "DOCTOR"
    PHARMACY = "PHARMACY"
    POLICE = "POLICE"
    FIRE_STATION = "FIRE_STATION"
    EMBASSY = "EMBASSY"
    TOWNHALL = "TOWNHALL"
    OTHER = "OTHER"


class TransportStatusCode(StrEnum):
    """Contract § 3.6.

    § 3.6 is explicit that `ON_TIME` needs real-time evidence and must never be
    concluded from the absence of an alert. A live train whose scheduled trip
    cannot be found is therefore UNKNOWN, not ON_TIME: without the schedule
    there is nothing to be on time against.
    """

    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"
    DISRUPTED = "DISRUPTED"
    UNKNOWN = "UNKNOWN"
