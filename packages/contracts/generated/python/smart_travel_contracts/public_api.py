"""GENERATED FILE - DO NOT EDIT.

Source:     packages/contracts/openapi/public-api.yaml
Regenerate: cd packages/contracts && npm run bundle && ./scripts/generate-python.sh

Editing this file by hand makes the models disagree with the contract, which is the exact
failure this pipeline exists to prevent.
"""


from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, RootModel


class PageMeta(BaseModel):
    """
    Opaque cursor pagination. Cursors are server-generated and must not be parsed by clients.
    """

    cursor: str | None = Field(..., max_length=512)
    next_cursor: str | None = Field(..., max_length=512)
    has_more: bool


class BloodType(Enum):
    A_ = 'A+'
    A__1 = 'A-'
    B_ = 'B+'
    B__1 = 'B-'
    AB_ = 'AB+'
    AB__1 = 'AB-'
    O_ = 'O+'
    O__1 = 'O-'
    UNKNOWN = 'UNKNOWN'
    NoneType_None = None


class Allergy(RootModel[str]):
    root: str = Field(..., max_length=128)


class Medication(RootModel[str]):
    root: str = Field(..., max_length=128)


class AccessibilityEnum(Enum):
    STEP_FREE = 'STEP_FREE'
    WHEELCHAIR = 'WHEELCHAIR'
    LOW_FLOOR_VEHICLE = 'LOW_FLOOR_VEHICLE'
    AVOID_STAIRS = 'AVOID_STAIRS'
    ASSISTANCE_REQUIRED = 'ASSISTANCE_REQUIRED'
    VISUAL_IMPAIRMENT = 'VISUAL_IMPAIRMENT'
    HEARING_IMPAIRMENT = 'HEARING_IMPAIRMENT'


class TravelPreference(BaseModel):
    """
    User routing preferences. Preferences never weaken a safety decision: they rank acceptable options, they do not make an unacceptable option acceptable.
    """

    prefer_safer_route: bool | None = True
    prefer_lower_cost: bool | None = False
    prefer_lower_emissions: bool | None = False
    max_extra_duration_minutes: int | None = Field(90, ge=0, le=1440)
    """
    How much extra travel time the user will accept for a safer route.
    """
    avoid_tolls: bool | None = False
    accessibility: list[AccessibilityEnum] | None = Field([], max_length=16)


class MissingField(RootModel[str]):
    root: str = Field(..., max_length=128)


class ReviewStatus(Enum):
    NEW = 'NEW'
    TRIAGED = 'TRIAGED'
    IN_REVIEW = 'IN_REVIEW'
    RESOLVED = 'RESOLVED'
    DISMISSED = 'DISMISSED'


class PoiType(Enum):
    """
    OTHER is the required escape hatch: a provider category this contract does not model is mapped to OTHER and kept, never discarded and never guessed into a neighbouring type. provider_category, where a producer supplies it, records what the provider actually said.
    """

    HOSPITAL = 'HOSPITAL'
    CLINIC = 'CLINIC'
    DOCTOR = 'DOCTOR'
    PHARMACY = 'PHARMACY'
    POLICE = 'POLICE'
    FIRE_STATION = 'FIRE_STATION'
    EMBASSY = 'EMBASSY'
    CONSULATE = 'CONSULATE'
    TOWNHALL = 'TOWNHALL'
    SHELTER = 'SHELTER'
    OTHER = 'OTHER'


class Note(RootModel[str]):
    root: str = Field(..., max_length=512)


class Status(Enum):
    alive = 'alive'


class HealthLiveResponse(BaseModel):
    status: Status
    service: str
    version: str


class Status1(Enum):
    ready = 'ready'
    not_ready = 'not_ready'


class Status2(Enum):
    up = 'up'
    down = 'down'
    degraded = 'degraded'
    skipped = 'skipped'


class Check(BaseModel):
    name: str
    """
    Dependency key, for example postgres, redis, oidc, agent.
    """
    required: bool
    """
    Whether a failure here makes the service unready.
    """
    status: Status2
    duration_ms: float
    detail: str | None = None
    """
    Short, user-safe reason. Never a connection string or credential.
    """


class Timestamp(RootModel[datetime]):
    root: datetime = Field(..., title='Timestamp')
    """
    ISO-8601 instant with an explicit offset, e.g. 2026-09-17T08:30:00Z.
    """


class Uuid(RootModel[UUID]):
    root: UUID = Field(..., title='Uuid')
    """
    UUID, serialised in lowercase canonical form. Expressed as `format: uuid` alone rather than as a pattern as well: generators map the format onto a real UUID type whose canonical serialisation is already lowercase, whereas a pattern beside it forces the value back to a bare string.
    """


class Locale(RootModel[str]):
    root: str = Field(
        ...,
        max_length=35,
        pattern='^[a-zA-Z]{2,3}(-[a-zA-Z]{4})?(-([a-zA-Z]{2}|[0-9]{3}))?$',
        title='Locale',
    )
    """
    BCP-47 language tag, e.g. th-TH or en-GB.
    """


class Timezone(RootModel[str]):
    root: str = Field(
        ...,
        max_length=64,
        min_length=1,
        pattern='^[A-Za-z0-9+_-]+(/[A-Za-z0-9+_.-]+)*$',
        title='Timezone',
    )
    """
    IANA time zone identifier, e.g. Asia/Bangkok. Validated against the tz database at the boundary, not by pattern alone.
    """


class CountryCode(RootModel[str]):
    root: str = Field(..., pattern='^[A-Z]{2}$', title='CountryCode')
    """
    ISO-3166-1 alpha-2, uppercase.
    """


class ConsentType(Enum):
    LOCATION_ONCE = 'LOCATION_ONCE'
    LOCATION_LIVE = 'LOCATION_LIVE'
    ALERT_NOTIFICATION = 'ALERT_NOTIFICATION'
    ANALYTICS = 'ANALYTICS'
    EMERGENCY_PROFILE = 'EMERGENCY_PROFILE'


class SemVer(RootModel[str]):
    root: str = Field(
        ...,
        pattern='^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$',
        title='SemVer',
    )


class NullableTimestamp(RootModel[datetime | None]):
    root: datetime | None = Field(..., title='NullableTimestamp')


class DegradationReason(Enum):
    TIMEOUT = 'TIMEOUT'
    UNAVAILABLE = 'UNAVAILABLE'
    RATE_LIMITED = 'RATE_LIMITED'
    STALE_DATA = 'STALE_DATA'
    PARTIAL_COVERAGE = 'PARTIAL_COVERAGE'
    NOT_CONFIGURED = 'NOT_CONFIGURED'
    SCHEMA_MISMATCH = 'SCHEMA_MISMATCH'


class DegradedService(BaseModel):
    service: str = Field(..., max_length=64)
    reason: DegradationReason
    since: NullableTimestamp | None = None
    retrying: bool | None = False


class ErrorCode(Enum):
    """
    Stable error codes. Adding a member is a minor contract change; removing or renaming one is breaking.
    """

    VALIDATION_ERROR = 'VALIDATION_ERROR'
    AUTHENTICATION_REQUIRED = 'AUTHENTICATION_REQUIRED'
    FORBIDDEN = 'FORBIDDEN'
    NOT_FOUND = 'NOT_FOUND'
    CONFLICT = 'CONFLICT'
    IDEMPOTENCY_CONFLICT = 'IDEMPOTENCY_CONFLICT'
    RATE_LIMITED = 'RATE_LIMITED'
    DEPENDENCY_TIMEOUT = 'DEPENDENCY_TIMEOUT'
    DEPENDENCY_UNAVAILABLE = 'DEPENDENCY_UNAVAILABLE'
    INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
    UNSUPPORTED_COVERAGE = 'UNSUPPORTED_COVERAGE'
    POLICY_VALIDATION_FAILED = 'POLICY_VALIDATION_FAILED'
    INTERNAL_ERROR = 'INTERNAL_ERROR'


class Code(Enum):
    REQUIRED = 'REQUIRED'
    INVALID_FORMAT = 'INVALID_FORMAT'
    OUT_OF_RANGE = 'OUT_OF_RANGE'
    TOO_LONG = 'TOO_LONG'
    TOO_SHORT = 'TOO_SHORT'
    UNKNOWN_FIELD = 'UNKNOWN_FIELD'
    UNSUPPORTED_VALUE = 'UNSUPPORTED_VALUE'
    NOT_CONFIRMED = 'NOT_CONFIRMED'
    INCONSISTENT = 'INCONSISTENT'


class FieldError(BaseModel):
    path: str = Field(..., max_length=256)
    """
    Dotted or indexed path into the rejected request, for example destination.coordinates.
    """
    code: Code
    message: str | None = Field(None, max_length=512)
    """
    Optional user-safe detail. Never echoes a rejected value that is itself sensitive.
    """


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str = Field(..., max_length=1024)
    """
    Human-readable and safe to display. Never carries a stack trace, SQL, provider credential or internal host name.
    """
    field_errors: list[FieldError] | None = []
    retryable: bool
    retry_after_seconds: int | None = Field(None, ge=0, le=86400)


class EmergencyContactPerson(BaseModel):
    name: str = Field(..., max_length=256, min_length=1)
    relationship: str | None = Field(None, max_length=64)
    phone: str = Field(..., max_length=32, min_length=3)
    """
    E.164 where possible. Redacted from logs.
    """
    locale: Locale | None = None


class InsuranceRef(BaseModel):
    provider_name: str = Field(..., max_length=256)
    policy_reference: str | None = Field(None, max_length=128)
    emergency_phone: str | None = Field(None, max_length=32)


class Position(RootModel[list]):
    """
    [longitude, latitude] in WGS84. RFC 7946 also permits an elevation element; this contract does not carry one, because nothing in the system consumes altitude and an optional third element would make every generated type ambiguous.
    """

    root: list = Field(..., max_length=2, min_length=2, title='Position')
    """
    [longitude, latitude] in WGS84. RFC 7946 also permits an elevation element; this contract does not carry one, because nothing in the system consumes altitude and an optional third element would make every generated type ambiguous.
    """


class Point(BaseModel):
    type: Literal['Point']
    coordinates: Position


class TripStatus(Enum):
    DRAFT = 'DRAFT'
    PLANNED = 'PLANNED'
    ACTIVE = 'ACTIVE'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'
    DELETED = 'DELETED'


class TravelMode(Enum):
    FLIGHT = 'FLIGHT'
    TRAIN = 'TRAIN'
    BUS = 'BUS'
    CAR = 'CAR'
    WALK = 'WALK'
    BICYCLE = 'BICYCLE'
    MULTIMODAL = 'MULTIMODAL'


class RecordId(RootModel[str]):
    root: str = Field(
        ...,
        max_length=256,
        min_length=1,
        pattern='^[A-Za-z0-9][A-Za-z0-9._:,+@/=-]*$',
        title='RecordId',
    )
    """
    Identifier of a record as the producer mints it. Stable and reproducible: fetching the same fact twice must yield the same RecordId, because that is what lets module 05 deduplicate across sources and what lets an operator trace one fact back through a log. A provider adapter therefore derives it from the provider key and the provider's own record id (for example `usgs:us7000abcd`), never from a random UUID, which would differ on every fetch and defeat both. A service that mints a record with no upstream identity may use a UUID here; the format is deliberately wide enough for both.
    """


class DeletionStatus(Enum):
    """
    Reported by soft-delete endpoints; purge happens asynchronously across owned schemas.
    """

    PENDING = 'PENDING'
    IN_PROGRESS = 'IN_PROGRESS'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'


class Coordinate(RootModel[list[Position]]):
    root: list[Position] = Field(..., min_length=4)


class Polygon(BaseModel):
    type: Literal['Polygon']
    coordinates: list[Coordinate] = Field(..., min_length=1)


class RunStatus(Enum):
    QUEUED = 'QUEUED'
    RUNNING = 'RUNNING'
    NEEDS_INPUT = 'NEEDS_INPUT'
    COMPLETED = 'COMPLETED'
    PARTIAL = 'PARTIAL'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'


class RunStage(Enum):
    """
    Controlled progress stages surfaced over SSE (00_API_AND_DATA_CONTRACTS.md section 6).
    """

    VALIDATING = 'VALIDATING'
    FETCHING_EXTERNAL_DATA = 'FETCHING_EXTERNAL_DATA'
    INTEGRATING_DATA = 'INTEGRATING_DATA'
    ASSESSING_RISK = 'ASSESSING_RISK'
    RETRIEVING_GUIDANCE = 'RETRIEVING_GUIDANCE'
    EVALUATING_ROUTES = 'EVALUATING_ROUTES'
    MAKING_DECISION = 'MAKING_DECISION'
    EXPLAINING = 'EXPLAINING'
    FORMATTING_RESPONSE = 'FORMATTING_RESPONSE'


class MessageKey(RootModel[str]):
    root: str = Field(
        ...,
        max_length=128,
        pattern='^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$',
        title='MessageKey',
    )
    """
    i18n key the web app resolves. Servers never send pre-translated progress copy.
    """


class DisasterEventType(Enum):
    EARTHQUAKE = 'EARTHQUAKE'
    CYCLONE = 'CYCLONE'
    STORM = 'STORM'
    FLOOD = 'FLOOD'
    WILDFIRE = 'WILDFIRE'
    VOLCANO = 'VOLCANO'
    LANDSLIDE = 'LANDSLIDE'
    EXTREME_TEMPERATURE = 'EXTREME_TEMPERATURE'
    HEALTH = 'HEALTH'
    TRANSPORT_CLOSURE = 'TRANSPORT_CLOSURE'
    OTHER = 'OTHER'


class HttpsUrl(RootModel[AnyUrl]):
    root: AnyUrl = Field(..., title='HttpsUrl')


class SourceAuthority(Enum):
    OFFICIAL = 'OFFICIAL'
    INTERGOVERNMENTAL = 'INTERGOVERNMENTAL'
    LICENSED_PROVIDER = 'LICENSED_PROVIDER'
    COMMUNITY = 'COMMUNITY'
    UNKNOWN = 'UNKNOWN'


class Citation(BaseModel):
    """
    Every factual claim in the summary must be covered by one of these. Citations are produced from retrieved evidence and provenance records, never written by the language model.
    """

    source_id: RecordId
    title: str = Field(..., max_length=512)
    source_url: HttpsUrl
    authority: SourceAuthority | None = None
    observed_at: NullableTimestamp | None = None
    evidence_id: Uuid | None = None


class ActionCode(Enum):
    """
    The only four actions the product may recommend. Locked by the decision engine before any LLM call.
    """

    NORMAL = 'NORMAL'
    CHANGE_ROUTE = 'CHANGE_ROUTE'
    DELAY = 'DELAY'
    AVOID = 'AVOID'


class RiskLevel(Enum):
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'
    UNKNOWN = 'UNKNOWN'


class UnitInterval(RootModel[float]):
    root: float = Field(..., ge=0.0, le=1.0, title='UnitInterval')
    """
    Normalised score in [0, 1].
    """


class ImmediateAction(BaseModel):
    text: str = Field(..., max_length=512)
    priority: int | None = Field(5, ge=1, le=10)
    evidence_id: Uuid | None = None


class RiskReasonCode(Enum):
    SEVERE_WEATHER_CORRIDOR = 'SEVERE_WEATHER_CORRIDOR'
    HEAVY_PRECIPITATION = 'HEAVY_PRECIPITATION'
    HIGH_WIND = 'HIGH_WIND'
    LOW_VISIBILITY = 'LOW_VISIBILITY'
    SNOW_OR_ICE = 'SNOW_OR_ICE'
    EXTREME_TEMPERATURE = 'EXTREME_TEMPERATURE'
    ACTIVE_DISASTER_ON_CORRIDOR = 'ACTIVE_DISASTER_ON_CORRIDOR'
    RECENT_EARTHQUAKE = 'RECENT_EARTHQUAKE'
    FLOOD_RISK = 'FLOOD_RISK'
    WILDFIRE_SMOKE = 'WILDFIRE_SMOKE'
    OFFICIAL_CLOSURE = 'OFFICIAL_CLOSURE'
    OFFICIAL_WARNING_ACTIVE = 'OFFICIAL_WARNING_ACTIVE'
    TRANSPORT_DISRUPTION = 'TRANSPORT_DISRUPTION'
    TRANSPORT_CANCELLED = 'TRANSPORT_CANCELLED'
    NIGHT_TRAVEL = 'NIGHT_TRAVEL'
    LONG_EXPOSURE_WINDOW = 'LONG_EXPOSURE_WINDOW'
    SPARSE_DATA_COVERAGE = 'SPARSE_DATA_COVERAGE'
    STALE_EVIDENCE = 'STALE_EVIDENCE'
    CONFLICTING_EVIDENCE = 'CONFLICTING_EVIDENCE'


class Severity(Enum):
    INFO = 'INFO'
    MINOR = 'MINOR'
    MODERATE = 'MODERATE'
    SEVERE = 'SEVERE'
    EXTREME = 'EXTREME'
    UNKNOWN = 'UNKNOWN'


class DecisionReason(BaseModel):
    code: RiskReasonCode
    text: str = Field(..., max_length=1000)
    severity: Severity | None = None
    source_ids: list[RecordId] | None = []


class LineString(BaseModel):
    type: Literal['LineString']
    coordinates: list[Position] = Field(..., min_length=2)


class RouteLabel(Enum):
    ORIGINAL = 'ORIGINAL'
    RECOMMENDED = 'RECOMMENDED'
    FASTEST = 'FASTEST'
    LOWEST_RISK = 'LOWEST_RISK'
    ALTERNATIVE = 'ALTERNATIVE'


class RouteSegment(BaseModel):
    segment_id: RecordId
    """
    Reproducible within its route, for the same reason as route_id.
    """
    mode: TravelMode
    from_name: str | None = Field(None, max_length=256)
    to_name: str | None = Field(None, max_length=256)
    geometry: LineString | None = None
    distance_m: float = Field(..., ge=0.0)
    duration_seconds: float = Field(..., ge=0.0)
    departure_time: NullableTimestamp | None = None
    arrival_time: NullableTimestamp | None = None
    transport_status_id: Uuid | None = None


class RouteExposure(BaseModel):
    """
    What this route is exposed to along its corridor within the travel window.
    """

    score: UnitInterval
    hazard_event_ids: list[Uuid] | None = []
    weather_window_ids: list[Uuid] | None = []
    closed: bool
    """
    True when an official closure covers part of this route.
    """
    closure_source_ids: list[RecordId] | None = []


class DataStatus(Enum):
    FRESH = 'FRESH'
    STALE = 'STALE'
    UNAVAILABLE = 'UNAVAILABLE'
    CONFLICTING = 'CONFLICTING'
    PARTIAL = 'PARTIAL'


class QualityFlag(Enum):
    MISSING = 'MISSING'
    STALE = 'STALE'
    CONFLICTING = 'CONFLICTING'
    INFERRED = 'INFERRED'
    INCOMPLETE = 'INCOMPLETE'
    OUTSIDE_COVERAGE = 'OUTSIDE_COVERAGE'


class Resolution(Enum):
    HIGHEST_AUTHORITY = 'HIGHEST_AUTHORITY'
    MOST_RECENT = 'MOST_RECENT'
    MOST_CONSERVATIVE = 'MOST_CONSERVATIVE'
    UNRESOLVED = 'UNRESOLVED'
    NoneType_None = None


class QualityConflict(BaseModel):
    field_path: str = Field(..., max_length=256)
    source_ids: list[RecordId] = Field(..., min_length=2)
    resolution: Resolution | None = None


class ContentHash(RootModel[str]):
    root: str = Field(
        ..., pattern='^(sha256:[0-9a-f]{64}|sha512:[0-9a-f]{128})$', title='ContentHash'
    )
    """
    Digest of the payload a record was derived from, prefixed with the algorithm that produced it. The prefix is the point: a bare hex string is ambiguous the moment a second algorithm is introduced, and an unprefixed value silently compares unequal to a prefixed one rather than failing. Used for deduplication and for detecting provider schema drift.
    """


class Coordinate1Item(RootModel[list[Position]]):
    root: list[Position] = Field(..., min_length=4)


class Coordinate1(RootModel[list[Coordinate1Item]]):
    root: list[Coordinate1Item] = Field(..., min_length=1)


class MultiPolygon(BaseModel):
    type: Literal['MultiPolygon']
    coordinates: list[Coordinate1]


class Geometry(RootModel[Point | LineString | Polygon | MultiPolygon]):
    root: Point | LineString | Polygon | MultiPolygon = Field(
        ..., title='GeoJsonGeometry'
    )
    """
    Any geometry a hazard, corridor or route may carry.
    """


class EmergencyInstruction(BaseModel):
    """
    Protective guidance quoted from an approved document, with its citation. Never generated free-hand.
    """

    text: str = Field(..., max_length=2000)
    evidence_id: Uuid
    hazard_type: DisasterEventType | None = None
    citation: Citation | None = None


class EmergencyServiceType(Enum):
    GENERAL_EMERGENCY = 'GENERAL_EMERGENCY'
    POLICE = 'POLICE'
    AMBULANCE = 'AMBULANCE'
    FIRE = 'FIRE'
    TOURIST_POLICE = 'TOURIST_POLICE'
    COAST_GUARD = 'COAST_GUARD'
    POISON_CONTROL = 'POISON_CONTROL'
    EMBASSY = 'EMBASSY'
    HOSPITAL = 'HOSPITAL'
    DISASTER_HOTLINE = 'DISASTER_HOTLINE'


class Freshness(BaseModel):
    observed_at: NullableTimestamp | None = None
    """
    Oldest observation time behind this answer, or null when no source publishes one.
    """
    fetched_at: Timestamp
    expires_at: NullableTimestamp | None = None


class Code1(Enum):
    NO_RELIABLE_KNOWLEDGE_EVIDENCE = 'NO_RELIABLE_KNOWLEDGE_EVIDENCE'
    PARTIAL_PROVIDER_COVERAGE = 'PARTIAL_PROVIDER_COVERAGE'
    STALE_EVIDENCE_USED = 'STALE_EVIDENCE_USED'
    NO_ROUTE_ALTERNATIVE_AVAILABLE = 'NO_ROUTE_ALTERNATIVE_AVAILABLE'
    MODE_NOT_SUPPORTED_IN_REGION = 'MODE_NOT_SUPPORTED_IN_REGION'
    FORECAST_HORIZON_EXCEEDED = 'FORECAST_HORIZON_EXCEEDED'
    MODEL_UNAVAILABLE_CONSERVATIVE_RESULT = 'MODEL_UNAVAILABLE_CONSERVATIVE_RESULT'
    EXPLANATION_FALLBACK_TEMPLATE = 'EXPLANATION_FALLBACK_TEMPLATE'
    CONFLICTING_SOURCES = 'CONFLICTING_SOURCES'


class Limitation(BaseModel):
    code: Code1
    text: str | None = Field(None, max_length=512)


class ResponseVersions(BaseModel):
    contract: SemVer
    policy: str | None = Field(None, max_length=64)
    prompt: str | None = Field(None, max_length=64)
    llm_model: str | None = Field(None, max_length=128)
    risk_model: str | None = Field(None, max_length=128)
    knowledge_collection: str | None = Field(None, max_length=64)


class SafetyLayer(Enum):
    """
    Layers requestable from the public safety map endpoint.
    """

    WEATHER = 'WEATHER'
    DISASTER = 'DISASTER'
    TRANSPORT = 'TRANSPORT'
    OFFICIAL_ALERT = 'OFFICIAL_ALERT'


class FeedbackCategory(Enum):
    HELPFUL = 'HELPFUL'
    INCORRECT = 'INCORRECT'
    STALE = 'STALE'
    UNSAFE = 'UNSAFE'
    ROUTE_ISSUE = 'ROUTE_ISSUE'
    SOURCE_ISSUE = 'SOURCE_ISSUE'
    OTHER = 'OTHER'


class DeliveryChannel(Enum):
    IN_APP = 'IN_APP'
    EMAIL = 'EMAIL'
    SMS = 'SMS'
    PUSH = 'PUSH'


class SubscriptionStatus(Enum):
    ACTIVE = 'ACTIVE'
    PAUSED = 'PAUSED'
    CANCELLED = 'CANCELLED'
    EXPIRED = 'EXPIRED'


class RunAccepted(BaseModel):
    request_id: Uuid
    status: RunStatus
    submitted_at: Timestamp


class RunProgress(BaseModel):
    request_id: Uuid
    stage: RunStage
    percent: int | None = Field(None, ge=0, le=100)
    """
    Null whenever remaining work cannot be estimated honestly.
    """
    message_key: MessageKey
    occurred_at: Timestamp | None = None


class RunNeedsInput(BaseModel):
    request_id: Uuid
    missing_fields: list[MissingField] = Field(..., min_length=1)
    prompt_key: MessageKey


class RunDegraded(BaseModel):
    request_id: Uuid
    service: str = Field(..., max_length=64)
    reason: DegradationReason
    retrying: bool


class RunCompleted(BaseModel):
    request_id: Uuid
    recommendation_id: Uuid
    result_url: str = Field(..., max_length=512)
    status: RunStatus


class RunFailed(BaseModel):
    request_id: Uuid
    error: ErrorBody


class Heartbeat(BaseModel):
    """
    Keeps intermediaries from closing an idle stream. Never rendered.
    """

    server_time: Timestamp


class ResponseMeta(BaseModel):
    request_id: Uuid
    correlation_id: Uuid | None = None
    contract_version: SemVer
    generated_at: Timestamp
    degraded_services: list[DegradedService] | None = []
    """
    Dependencies that answered late, partially or not at all while producing this response.
    """


class ErrorResponse(BaseModel):
    error: ErrorBody
    meta: ResponseMeta


class ConsentRecord(BaseModel):
    """
    One versioned consent decision. Consent is append-only: revoking writes revoked_at rather than deleting the row, so that what the user agreed to and when stays auditable.
    """

    consent_id: Uuid
    type: ConsentType
    granted: bool
    policy_version: SemVer
    """
    Version of the consent text the user was shown.
    """
    granted_at: Timestamp
    revoked_at: NullableTimestamp | None = None
    expires_at: NullableTimestamp | None = None
    """
    Set for scoped grants such as LOCATION_ONCE and for live-location sessions.
    """


class EmergencyProfile(BaseModel):
    """
    Medical and next-of-kin details the traveller chooses to store for an emergency. Stored encrypted at the application layer under a key that does not live in the same database; returned only to its owner, never logged, never traced, never sent to an LLM.
    """

    blood_type: BloodType | None = None
    allergies: list[Allergy] | None = Field([], max_length=32)
    medical_notes: str | None = Field(None, max_length=2000)
    """
    Free text. Redacted from every log, metric and trace.
    """
    medications: list[Medication] | None = Field([], max_length=32)
    contacts: list[EmergencyContactPerson] | None = Field([], max_length=8)
    insurance: InsuranceRef | None = None
    updated_at: Timestamp
    key_version: str | None = Field(None, max_length=32)
    """
    Encryption key version the stored payload was sealed with. Echoed so that key rotation is auditable; the key itself is never exposed.
    """


class LocationRef(BaseModel):
    """
    A place resolved by a real geocoding provider. An assessment may only be started when both origin and destination have confirmed_by_user = true. Exact coordinates are personal data: keep them only as long as the trip and consent require, and never write them to logs or traces.
    """

    place_id: str | None = Field(None, max_length=256)
    """
    Provider-scoped place identifier. Null when the user dropped a pin instead of choosing a suggestion.
    """
    display_name: str = Field(..., max_length=512, min_length=1)
    coordinates: Point
    country_code: CountryCode | None = None
    admin1: str | None = Field(None, max_length=256)
    """
    First-level administrative area as the provider names it.
    """
    timezone: Timezone | None = None
    provider: str = Field(..., pattern='^[a-z][a-z0-9_]{1,63}$')
    """
    Geocoding provider key, or user_pin when the coordinates came from the map rather than a provider.
    """
    confirmed_by_user: bool
    """
    True once the user has seen the pin on the map and accepted it.
    """


class Trip(BaseModel):
    """
    A traveller's saved journey. revision backs optimistic concurrency: every mutation increments it and PATCH requires a matching If-Match header, so two tabs cannot silently overwrite each other.
    """

    trip_id: Uuid
    revision: int = Field(..., ge=1)
    """
    Monotonic revision counter, also served as the ETag.
    """
    title: str | None = Field(None, max_length=256)
    origin: LocationRef
    destination: LocationRef
    departure_time: Timestamp
    return_time: NullableTimestamp | None = None
    timezone: Timezone
    travel_modes: list[TravelMode] = Field(..., max_length=7, min_length=1)
    preferences: TravelPreference | None = None
    selected_route_id: RecordId | None = None
    """
    Route the traveller applied. Set only by apply-route, never by the client directly. A RecordId rather than a Uuid because it holds a RouteCandidate.route_id, and those are producer-minted and reproducible (`openrouteservice:3ca4459b8d41b503`) so that the same route asked for twice is recognisably the same route.
    """
    previous_selected_route_id: RecordId | None = None
    """
    The route this trip had applied before the current one, kept so a reassessment can say what changed. Same type as selected_route_id for the same reason.
    """
    latest_request_id: Uuid | None = None
    """
    Most recent assessment started for this trip revision.
    """
    status: TripStatus
    created_at: Timestamp
    updated_at: Timestamp
    deleted_at: NullableTimestamp | None = None
    """
    Set by soft delete. Purge of the underlying rows happens asynchronously under the retention policy.
    """


class RunRef(BaseModel):
    """
    Returned by every endpoint that starts asynchronous work. The caller follows the run over SSE and falls back to polling; the assessment itself never blocks the HTTP request that started it.
    """

    request_id: Uuid
    trip_id: Uuid | None = None
    conversation_id: Uuid | None = None
    status: RunStatus
    events_url: str = Field(..., max_length=512)
    """
    Relative URL of the SSE stream for this run.
    """
    poll_url: str = Field(..., max_length=512)
    """
    Relative URL of the polling endpoint for this run.
    """
    submitted_at: Timestamp


class RunState(BaseModel):
    """
    Pollable state of an assessment run. It reports progress and where the result will appear; it never exposes the agent's reasoning, prompts or raw provider payloads.
    """

    request_id: Uuid
    trip_id: Uuid | None = None
    conversation_id: Uuid | None = None
    status: RunStatus
    stage: RunStage | None = None
    percent: int | None = Field(None, ge=0, le=100)
    """
    Null whenever the remaining work cannot be estimated honestly.
    """
    message_key: MessageKey | None = None
    missing_fields: list[MissingField] | None = []
    """
    Populated when status is NEEDS_INPUT. The system asks rather than guessing.
    """
    recommendation_id: Uuid | None = None
    result_url: str | None = Field(None, max_length=512)
    error: ErrorBody | None = None
    degraded_services: list[DegradedService] | None = []
    submitted_at: Timestamp
    updated_at: Timestamp
    completed_at: NullableTimestamp | None = None


class Conversation(BaseModel):
    """
    A thread of assistant turns about a trip. Continuing a conversation reuses its id but never reuses stale evidence: a follow-up that asks about current conditions triggers a fresh assessment when the previous one is past its freshness window.
    """

    conversation_id: Uuid
    trip_id: Uuid | None = None
    title: str | None = Field(None, max_length=256)
    """
    Short label derived from the first question, for the recent-chats list.
    """
    last_message_preview: str | None = Field(None, max_length=512)
    last_recommendation_id: Uuid | None = None
    message_count: int = Field(..., ge=0)
    created_at: Timestamp
    updated_at: Timestamp


class FeedbackEvent(BaseModel):
    """
    Explicit feedback on a recommendation, kept separate from behavioural telemetry. UNSAFE feedback opens a safety review record; nothing here retrains a model automatically.
    """

    feedback_id: Uuid
    recommendation_id: Uuid
    category: FeedbackCategory
    text_redacted: str | None = Field(None, max_length=2000)
    """
    Free text after redaction of phone numbers, e-mail addresses and precise coordinates.
    """
    review_status: ReviewStatus
    safety_review_id: Uuid | None = None
    """
    Set when the category is UNSAFE and a safety review record was created.
    """
    created_at: Timestamp


class AlertSubscription(BaseModel):
    """
    An opt-in to be told when a trip's situation materially changes. Every subscription points at the consent that authorises it; revoking that consent cancels the subscription. A cooldown suppresses repeat notifications, but a higher severity always breaks through.
    """

    subscription_id: Uuid
    trip_id: Uuid
    channel: DeliveryChannel
    consent_id: Uuid
    status: SubscriptionStatus
    min_severity: Severity | None = None
    """
    Lowest severity that may notify this subscriber.
    """
    cooldown_until: NullableTimestamp | None = None
    expires_at: NullableTimestamp | None = None
    created_at: Timestamp
    cancelled_at: NullableTimestamp | None = None


class OfficialContact(BaseModel):
    """
    A verified emergency number for a specific country or subdivision. Numbers come from a reviewed directory with an effective and verified date, never from a language model and never from a neighbouring country as a fallback. A contact past its review date is withheld and the caller shows an unavailable state.
    """

    contact_id: Uuid
    country_code: CountryCode
    subdivision: str | None = Field(None, max_length=16)
    """
    ISO-3166-2 subdivision code when the number is regional rather than national.
    """
    service_type: EmergencyServiceType
    label: str = Field(..., max_length=256)
    """
    Display name in the requested locale, for example Tourist Police.
    """
    phone: str = Field(..., max_length=32, min_length=2)
    """
    Dialable string as published by the authority, including short codes.
    """
    languages: list[Locale] | None = []
    source_url: HttpsUrl
    authority: SourceAuthority
    effective_at: Timestamp
    verified_at: Timestamp
    review_due_at: NullableTimestamp | None = None


class DataQuality(BaseModel):
    """
    Quality envelope attached to every canonical record. The score never replaces the flags: a consumer that reads score alone and ignores flags is non-conforming. score is nullable, and a null score is not a quality problem — it means no agreed formula has been applied yet. A producer must leave it null rather than invent a number, because a fabricated score is indistinguishable from a measured one once it is downstream.
    """

    status: DataStatus
    score: UnitInterval | None = None
    """
    Weighted quality score. Null until a producer applies an agreed formula; never a placeholder.
    """
    flags: list[QualityFlag]
    coverage: UnitInterval | None = None
    """
    Share of the requested area and time window the source actually covers.
    """
    completeness: UnitInterval | None = None
    """
    Share of required fields the provider supplied.
    """
    freshness_seconds: int | None = Field(None, ge=0)
    """
    Age of the underlying observation at generation time. Null when the source publishes no observation time.
    """
    conflicts: list[QualityConflict] | None = []
    """
    Conflicting values seen for the same fact across sources.
    """
    notes: list[Note] | None = []
    score_version: SemVer | None = None
    """
    Version of the scoring formula and weights that produced `score` — not a revision counter for the value itself. Required whenever `score` is non-null, and null alongside a null score: a number that cannot be attributed to a formula cannot be compared across time.
    """


class SourceProvenance(BaseModel):
    """
    Every fact that can influence a decision must resolve back to one of these. When a provider publishes no observation time, observed_at is null and the record carries a quality flag; fetched_at is never presented as an observation time.
    """

    source_id: RecordId
    """
    Stable identifier for this source record. Reproducible on purpose: fetching the same fact twice must produce the same value, because deduplication in module 05 and tracing one fact through a log both depend on it. A random UUID per fetch would defeat both.
    """
    provider: str = Field(..., pattern='^[a-z][a-z0-9_]{1,63}$')
    """
    Stable provider key from the provider catalogue, for example open_meteo, usgs, gdacs, openrouteservice.
    """
    provider_record_id: str | None = Field(None, max_length=256)
    """
    Provider-scoped identifier for the record, for example a USGS event id.
    """
    authority: SourceAuthority
    source_url: HttpsUrl | None = None
    """
    Canonical URL for the record, or the request URL the adapter used. Null only when the provider publishes neither — a bulk feed with no per-record address, for example.
    """
    license: str | None = Field(None, max_length=256)
    """
    Licence or terms identifier the provider publishes under.
    """
    attribution: str | None = Field(None, max_length=512)
    """
    Attribution text that must be displayed wherever this source is shown.
    """
    observed_at: NullableTimestamp | None = None
    published_at: NullableTimestamp | None = None
    fetched_at: Timestamp
    expires_at: NullableTimestamp | None = None
    content_hash: ContentHash | None = None
    """
    Digest of the upstream payload this record was derived from, so provider schema drift is detectable rather than silent. Null when the adapter had no raw payload to hash, which is the case for a record assembled from several responses.
    """
    schema_version: SemVer


class RouteCandidate(BaseModel):
    """
    One way of making the journey, with the hazard exposure measured along its corridor rather than at the endpoints. A route whose corridor carries an official closure must have exposure.closed = true and can never be labelled RECOMMENDED. A raw route straight from a routing provider carries exposure: null and risk_level: UNKNOWN until modules 05/06 evaluate it; the two are bound together so an unevaluated route cannot be mistaken for a safe one.
    """

    route_id: RecordId
    """
    Reproducible on purpose: asking for the same route twice must yield the same value, so a route served from cache and one fetched fresh are recognisably the same route rather than two. A provider adapter derives it from the provider key and a fingerprint of the question (waypoints, mode, preference). Same reasoning as source_id and event_id.
    """
    provider_route_id: str | None = Field(None, max_length=256)
    """
    Opaque provider handle, kept so the same route can be re-fetched or audited.
    """
    label: RouteLabel
    mode: TravelMode
    geometry: LineString
    segments: list[RouteSegment] | None = []
    distance_m: float = Field(..., ge=0.0)
    duration_seconds: float = Field(..., ge=0.0)
    transfers: int | None = Field(None, ge=0)
    exposure: RouteExposure | None = None
    """
    Null until a route has been evaluated against hazards and weather. A routing provider knows road geometry and travel time and has no view on danger, so module 04 emits null here and modules 05/06 fill it in. Null does NOT mean 'no exposure': an unevaluated route must never be rendered as safe, which is why the schema requires risk_level to be UNKNOWN whenever this is null.
    """
    risk_level: RiskLevel
    quality: DataQuality
    sources: list[SourceProvenance] = Field(..., min_length=1)
    """
    Plural, unlike the singular `source` on records that come from exactly one provider. A route survives stitching: module 05 joins legs from different providers into one itinerary, and each leg's provenance has to survive that join. A single-provider route sends a one-element array.
    """


class DisasterEvent(BaseModel):
    """
    A hazard published by a real feed. An OfficialAlert is the same shape with official = true and an authority of OFFICIAL or INTERGOVERNMENTAL; an active official alert is never dropped because a different provider stopped answering.
    """

    event_id: RecordId
    event_type: DisasterEventType
    title: str = Field(..., max_length=512)
    description: str | None = Field(..., max_length=8000)
    """
    Provider text. Untrusted: sanitised before display and never treated as an instruction to the system.
    """
    severity: Severity
    geometry: Geometry
    effective_at: NullableTimestamp | None = None
    ends_at: NullableTimestamp | None = None
    instruction: str | None = Field(..., max_length=4000)
    """
    Protective action text as published by the issuing authority, verbatim.
    """
    official: bool
    """
    True when the issuing body is a government or intergovernmental authority.
    """
    closes_transport: bool | None = False
    """
    True when the alert itself declares a route, airport or corridor closed.
    """
    magnitude: float | None = None
    """
    Provider's own magnitude number, carried through rather than interpreted. Meaningless on its own: it must be read together with magnitude_unit, because 5.8 Mw and 5.8 mb are different measurements of different things.
    """
    magnitude_unit: str | None = Field(None, max_length=32)
    """
    Scale the magnitude is expressed on, as the provider names it — Mw, mb, Ms, ml for earthquakes, or a provider-specific scale for other hazards. Required whenever magnitude is non-null: a bare number invites a consumer to compare two scales as though they were one, and for a hazard that is a safety error, not a rounding one.
    """
    depth_km: float | None = Field(None, ge=0.0)
    """
    Hypocentre depth in kilometres, where the hazard type has one. A shallow earthquake and a deep one of equal magnitude do very different things at the surface, so the depth is part of the evidence rather than a detail.
    """
    quality: DataQuality
    source: SourceProvenance


class SseRunAccepted(RootModel[RunAccepted]):
    root: RunAccepted


class SseRunProgress(RootModel[RunProgress]):
    root: RunProgress


class SseRunNeedsInput(RootModel[RunNeedsInput]):
    root: RunNeedsInput


class SseRunDegraded(RootModel[RunDegraded]):
    root: RunDegraded


class SseRunCompleted(RootModel[RunCompleted]):
    root: RunCompleted


class SseRunFailed(RootModel[RunFailed]):
    root: RunFailed


class SseHeartbeat(RootModel[Heartbeat]):
    root: Heartbeat


class HealthReadyResponse(BaseModel):
    status: Status1
    checks: list[Check]
    checked_at: Timestamp


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    locale: Locale | None = None
    timezone: Timezone | None = None
    home_country_code: CountryCode | None = None


class EmergencyProfileResponse(BaseModel):
    data: EmergencyProfile
    meta: ResponseMeta


class EmergencyProfileUpsertRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    blood_type: BloodType | None = None
    allergies: list[Allergy] | None = Field(None, max_length=32)
    medical_notes: str | None = Field(None, max_length=2000)
    medications: list[Medication] | None = Field(None, max_length=32)
    contacts: list[EmergencyContactPerson] | None = Field(None, max_length=8)
    insurance: InsuranceRef | None = None


class ConsentRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    type: ConsentType
    granted: bool
    policy_version: SemVer
    expires_at: NullableTimestamp | None = None
    """
    Requested expiry for a scoped grant such as a live-location session. The server caps
    it at the configured maximum.

    """


class ConsentResponse(BaseModel):
    data: ConsentRecord
    meta: ResponseMeta


class LocationSearchResponse(BaseModel):
    data: list[LocationRef]
    meta: ResponseMeta


class CreateTripRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    title: str | None = Field(None, max_length=256)
    origin: LocationRef
    destination: LocationRef
    departure_time: Timestamp
    return_time: NullableTimestamp | None = None
    timezone: Timezone
    travel_modes: list[TravelMode] = Field(..., max_length=7, min_length=1)
    preferences: TravelPreference | None = None


class UpdateTripRequest(BaseModel):
    """
    Only the supplied fields change. Every change increments the trip revision.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    title: str | None = Field(None, max_length=256)
    origin: LocationRef | None = None
    destination: LocationRef | None = None
    departure_time: Timestamp | None = None
    return_time: NullableTimestamp | None = None
    timezone: Timezone | None = None
    travel_modes: list[TravelMode] | None = Field(None, max_length=7, min_length=1)
    preferences: TravelPreference | None = None
    status: TripStatus | None = None


class TripResponse(BaseModel):
    data: Trip
    meta: ResponseMeta


class TripListResponse(BaseModel):
    data: list[Trip]
    meta: ResponseMeta
    page: PageMeta


class Data(BaseModel):
    resource_id: Uuid
    status: DeletionStatus
    requested_at: Timestamp
    completed_at: NullableTimestamp | None = None


class DeletionStatusResponse(BaseModel):
    data: Data
    meta: ResponseMeta


class CreateAssessmentRequest(BaseModel):
    """
    Everything here is optional: the journey itself comes from the stored trip, so a client
    cannot assess one trip while claiming another.

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    question: str | None = Field(None, max_length=2000)
    conversation_id: Uuid | None = None
    """
    Continue an existing thread instead of starting a new one.
    """
    locale: Locale | None = None
    live_location_consent_id: Uuid | None = None
    avoid_areas: list[Polygon] | None = Field(None, max_length=8)
    """
    Areas the traveller asked to avoid, drawn on the safety map. Advisory input to route
    evaluation, not a way to hide an official warning.

    """


class RunRefResponse(BaseModel):
    data: RunRef
    meta: ResponseMeta


class RunStateResponse(BaseModel):
    data: RunState
    meta: ResponseMeta


class ApplyRouteRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    recommendation_id: Uuid
    """
    The recommendation the route was offered in, so the choice is auditable.
    """
    route_id: RecordId
    risk_acknowledged: bool | None = False
    """
    Required when the chosen route is MEDIUM or HIGH. Records that the traveller was
    shown the risk and accepted it. It never overrides a closure.

    """


class Data1(BaseModel):
    trip: Trip
    run: RunRef


class ApplyRouteResponse(BaseModel):
    data: Data1
    meta: ResponseMeta


class ConversationListResponse(BaseModel):
    data: list[Conversation]
    meta: ResponseMeta
    page: PageMeta


class ConversationMessageRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    question: str = Field(..., max_length=2000, min_length=1)
    trip_id: Uuid | None = None
    """
    Trip this question is about, when the thread is not already bound to one.
    """
    locale: Locale | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    recommendation_id: Uuid
    category: FeedbackCategory
    text: str | None = Field(None, max_length=2000)
    """
    Free text. Redacted for phone numbers, e-mail addresses and precise coordinates
    before storage.

    """


class FeedbackResponse(BaseModel):
    data: FeedbackEvent
    meta: ResponseMeta


class CreateAlertSubscriptionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    trip_id: Uuid
    channel: DeliveryChannel
    consent_id: Uuid
    min_severity: Severity | None = None


class AlertSubscriptionResponse(BaseModel):
    data: AlertSubscription
    meta: ResponseMeta


class OfficialContactListResponse(BaseModel):
    data: list[OfficialContact]
    meta: ResponseMeta


class UserProfile(BaseModel):
    """
    The caller's own profile. user_id is an internal UUID; the OIDC subject is never exposed to the browser and email is never a primary key.
    """

    user_id: Uuid
    display_name: str | None = Field(None, max_length=256)
    """
    Name taken from the identity provider, shown only back to the owner.
    """
    locale: Locale
    timezone: Timezone
    home_country_code: CountryCode | None = None
    consents: list[ConsentRecord]
    """
    Current effective consent state, one entry per ConsentType the user has ever acted on.
    """
    has_emergency_profile: bool | None = False
    """
    Whether an encrypted emergency profile exists. The profile content itself is never included here.
    """
    created_at: Timestamp
    updated_at: Timestamp
    deleted_at: NullableTimestamp | None = None


class RecommendationResponse(BaseModel):
    """
    The object the web app renders. Every displayed fact carries its source and freshness; when a dependency could not be reached the response says so in degraded_services and limitations rather than filling the gap. The public API revalidates this against the schema before it reaches the browser.
    """

    recommendation_id: Uuid
    request_id: Uuid
    trip_id: Uuid
    conversation_id: Uuid | None = None
    decision_id: Uuid | None = None
    snapshot_id: Uuid | None = None
    status: RunStatus
    """
    COMPLETED or PARTIAL. A PARTIAL result is still safe to show but must be labelled as incomplete in the UI.
    """
    action_code: ActionCode
    risk_level: RiskLevel
    confidence: UnitInterval
    short_summary: str = Field(..., max_length=1000)
    immediate_actions: list[ImmediateAction] | None = []
    reasons: list[DecisionReason]
    primary_route: RouteCandidate | None = None
    alternatives: list[RouteCandidate] | None = []
    alerts: list[DisasterEvent] | None = []
    """
    Hazards and official alerts that intersect this journey.
    """
    emergency_instructions: list[EmergencyInstruction] | None = []
    official_contacts: list[OfficialContact] | None = []
    sources: list[SourceProvenance]
    freshness: Freshness
    limitations: list[Limitation]
    degraded_services: list[DegradedService]
    versions: ResponseVersions
    expires_at: NullableTimestamp | None = None
    """
    After this instant the result must be re-assessed before being presented as current.
    """
    created_at: Timestamp


class SafetyEvent(BaseModel):
    """
    Map-sized summary of one hazard for the safety map. It is a projection of a canonical DisasterEvent or weather window: enough to draw a marker and open a detail panel, with the freshness the UI is required to show, and never a substitute for the full record.
    """

    event_id: RecordId
    layer: SafetyLayer
    event_type: DisasterEventType
    title: str = Field(..., max_length=512)
    severity: Severity
    geometry: Geometry
    official: bool
    valid_from: NullableTimestamp | None = None
    valid_to: NullableTimestamp | None = None
    detail_url: str | None = Field(None, max_length=512)
    """
    Relative public API path for the full canonical record.
    """
    quality: DataQuality
    source: SourceProvenance


class EmergencyPoi(BaseModel):
    """
    A nearby hospital, police station or embassy returned by a licensed places provider. A POI is a navigation aid, not a verified phone directory: any number shown here is the provider's and is labelled as such, while dialable emergency numbers come from OfficialContact.
    """

    poi_id: RecordId
    poi_type: PoiType
    """
    OTHER is the required escape hatch: a provider category this contract does not model is mapped to OTHER and kept, never discarded and never guessed into a neighbouring type. provider_category, where a producer supplies it, records what the provider actually said.
    """
    name: str | None = Field(..., max_length=512)
    """
    Null when the provider has no name for the place. OpenStreetMap leaves roughly one emergency POI in ten untagged, including real hospitals; the shared context calls this data 'frequently stale or missing'. The two alternatives were both worse: dropping the record hides the nearest hospital from somebody who needs it, and synthesising 'Unnamed hospital' puts words in the provider's mouth inside a data field. A consumer renders the type and the distance, and says the name is unknown.
    """
    location: Point
    address: str | None = Field(None, max_length=512)
    phone: str | None = Field(None, max_length=32)
    """
    As published by the places provider. Never presented as an official emergency number.
    """
    distance_m: float | None = Field(..., ge=0.0)
    """
    Straight-line metres from the query point, not travel distance — there may be no road. Null when the provider did not give one, rather than zero, which would read as 'you are here'.
    """
    open_now: bool | None = None
    """
    Null unless the provider supplies opening hours; unknown is not open.
    """
    quality: DataQuality
    source: SourceProvenance


class UserProfileResponse(BaseModel):
    data: UserProfile
    meta: ResponseMeta


class RecommendationResponseEnvelope(BaseModel):
    data: RecommendationResponse
    meta: ResponseMeta


class SafetyEventListResponse(BaseModel):
    data: list[SafetyEvent]
    meta: ResponseMeta
    page: PageMeta


class EmergencyPoiListResponse(BaseModel):
    data: list[EmergencyPoi]
    meta: ResponseMeta
