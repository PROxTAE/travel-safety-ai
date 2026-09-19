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
