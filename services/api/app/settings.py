"""Configuration, validated once at startup.

Everything this service needs to know about its environment arrives here and nowhere else. Two
rules shape the module:

* **Fail at startup, not at request time.** A missing database password should stop the container
  from reporting ready, not surface as a 500 on the first user request an hour later.
* **No business default may be hard-coded elsewhere.** Freshness windows, timeout budgets and rate
  limits are configuration, because the delivery rules require them to be tunable without a code
  change. Their defaults live here with the reasoning attached.

Secrets are read from the environment. Nothing in this file may carry a working credential, and
`__repr__` on the secret fields is suppressed by pydantic's `SecretStr`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "staging", "production"]


class Settings(BaseSettings):
    """Runtime configuration for the public API."""

    model_config = SettingsConfigDict(
        env_file=None,  # the container gets its environment from compose, not from a mounted file
        env_nested_delimiter="__",
        extra="ignore",  # the root .env is shared by every service; ours is a subset of it
        frozen=True,
        # Fields are named for the environment variable they read, but tests construct Settings
        # directly with the Python names rather than mutating the process environment.
        populate_by_name=True,
    )

    # --- Identity of this process ------------------------------------------------------------

    app_env: Environment = Field(default="development", alias="APP_ENV")
    service_name: str = Field(default="api", alias="SERVICE_NAME")
    service_version: str = Field(default="0.1.0", alias="SERVICE_VERSION")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )
    contract_version: str = Field(default="1.0.0", alias="CONTRACT_VERSION")

    # --- PostgreSQL ---------------------------------------------------------------------------

    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT", ge=1, le=65535)
    postgres_db: str = Field(default="smart_travel", alias="POSTGRES_DB")
    postgres_user: str = Field(alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(alias="POSTGRES_PASSWORD")

    db_pool_size: int = Field(default=10, alias="API_DB_POOL_SIZE", ge=1, le=100)
    db_max_overflow: int = Field(default=5, alias="API_DB_MAX_OVERFLOW", ge=0, le=100)
    db_connect_timeout_seconds: float = Field(
        default=5.0, alias="API_DB_CONNECT_TIMEOUT_SECONDS", gt=0, le=60
    )
    db_statement_timeout_ms: int = Field(
        default=10_000,
        alias="API_DB_STATEMENT_TIMEOUT_MS",
        ge=100,
        le=120_000,
        description="Server-side cap so one pathological query cannot hold a connection forever.",
    )

    # --- Redis --------------------------------------------------------------------------------

    redis_url: RedisDsn = Field(default=RedisDsn("redis://redis:6379/0"), alias="REDIS_URL")
    redis_key_prefix: str = Field(
        default="sta",
        alias="REDIS_KEY_PREFIX",
        description=(
            "Combined with app_env into the `sta:{env}:` prefix that the key conventions require."
        ),
    )
    redis_timeout_seconds: float = Field(
        default=2.0, alias="API_REDIS_TIMEOUT_SECONDS", gt=0, le=30
    )

    # --- OIDC ----------------------------------------------------------------------------------

    oidc_issuer: str = Field(
        default="http://keycloak:8080/realms/smart-travel", alias="OIDC_ISSUER"
    )
    oidc_audience: str = Field(default="smart-travel-api", alias="OIDC_AUDIENCE")
    oidc_discovery_timeout_seconds: float = Field(
        default=3.0, alias="API_OIDC_TIMEOUT_SECONDS", gt=0, le=30
    )
    oidc_allowed_algorithms: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("RS256", "RS384", "RS512", "ES256", "ES384"),
        alias="API_OIDC_ALLOWED_ALGORITHMS",
        description=(
            "Asymmetric algorithms only, and checked against the header before verification. "
            "Accepting `none` or an HMAC algorithm here is the classic JWT forgery: the public "
            "signing key is published in the JWKS, so an attacker could sign a token with it."
        ),
    )
    oidc_leeway_seconds: float = Field(
        default=30.0,
        alias="API_OIDC_LEEWAY_SECONDS",
        ge=0,
        le=300,
        description=(
            "Clock-skew tolerance on exp/nbf/iat. A large value extends a stolen token's life."
        ),
    )
    oidc_jwks_ttl_seconds: float = Field(
        default=600.0,
        alias="API_OIDC_JWKS_TTL_SECONDS",
        gt=0,
        le=86400,
        description="How long a fetched JWKS is reused before it is refetched on the next use.",
    )
    oidc_jwks_min_refresh_seconds: float = Field(
        default=30.0,
        alias="API_OIDC_JWKS_MIN_REFRESH_SECONDS",
        ge=0,
        le=3600,
        description=(
            "Cooldown between refreshes triggered by an unknown key id. Without it, tokens "
            "carrying random `kid` values would let anyone turn one request into one outbound "
            "fetch against the identity provider."
        ),
    )

    # --- Emergency profile encryption ----------------------------------------------------------

    emergency_encryption_keys: str | None = Field(
        default=None,
        alias="API_EMERGENCY_ENCRYPTION_KEYS",
        description=(
            "Versioned key-encryption keys as `v1:<base64>,v2:<base64>`. Generate one with "
            "`python -m app.cli.generate_key`. Absent means the emergency profile endpoints "
            "report themselves unavailable; there is no plaintext fallback."
        ),
    )
    emergency_encryption_active_version: str | None = Field(
        default=None,
        alias="API_EMERGENCY_ENCRYPTION_ACTIVE_VERSION",
        description="Which key new records are sealed under. Defaults to the last one listed.",
    )

    # --- Consent ---------------------------------------------------------------------------------
    #
    # Ceilings, not defaults: a client may ask for less, never for more. A location grant that
    # outlives the reason it was given is indistinguishable from tracking.

    consent_location_once_ttl_seconds: int = Field(
        default=3600,
        alias="API_CONSENT_LOCATION_ONCE_TTL_SECONDS",
        ge=60,
        le=86_400,
        description="How long a one-off location grant survives. It is for a single errand.",
    )
    consent_location_live_max_ttl_seconds: int = Field(
        default=86_400,
        alias="API_CONSENT_LOCATION_LIVE_MAX_TTL_SECONDS",
        ge=300,
        le=2_592_000,
        description="Ceiling on a live-location session, so one can never be granted indefinitely.",
    )
    consent_policy_retention_days: int = Field(
        default=2_555,
        alias="API_CONSENT_RETENTION_DAYS",
        ge=365,
        description=(
            "How long revoked consent records are kept. Consent evidence outlives the consent "
            "itself: proving what someone agreed to, and when, is the point of recording it."
        ),
    )

    # --- Trip domain -----------------------------------------------------------------------------
    #
    # Business limits, not constants: the delivery rules require them tunable without a code change.

    trip_max_backdate_seconds: int = Field(
        default=3600,
        alias="API_TRIP_MAX_BACKDATE_SECONDS",
        ge=0,
        le=604_800,
        description=(
            "How far in the past a departure may be set. Not zero: a traveller already on the "
            "road still needs to save the trip they are taking. Historical analysis is a separate "
            "endpoint and is not reachable from here."
        ),
    )
    trip_max_future_days: int = Field(
        default=365,
        alias="API_TRIP_MAX_FUTURE_DAYS",
        ge=1,
        le=3650,
        description=(
            "Upper bound on a departure date. No provider forecasts that far ahead, so a trip "
            "beyond it can be saved but never usefully assessed; the bound keeps a typo in the "
            "year field from becoming a row nothing will ever answer for."
        ),
    )
    trip_supported_travel_modes: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("TRAIN", "BUS", "CAR", "WALK", "BICYCLE", "MULTIMODAL"),
        alias="API_TRIP_SUPPORTED_TRAVEL_MODES",
        description=(
            "Travel modes this deployment has a real data source for. FLIGHT is absent by "
            "default: the contract's flight provider is Amadeus production, the shared context "
            "rules its test environment out as acceptance data, and claiming coverage we cannot "
            "back is the failure this project exists to avoid. A mode outside this list is "
            "refused with UNSUPPORTED_COVERAGE rather than accepted and silently not assessed. "
            "Region-aware coverage needs module 04's provider registry and is not this check."
        ),
    )
    trip_list_default_limit: int = Field(
        default=20, alias="API_TRIP_LIST_DEFAULT_LIMIT", ge=1, le=100
    )

    # --- Internal services ----------------------------------------------------------------------
    #
    # Base URLs come from configuration and are never taken from a request. Anything else would
    # turn this service into an SSRF proxy for everything on the internal network.

    agent_service_url: str = Field(default="http://agent:8001", alias="AGENT_SERVICE_URL")
    external_data_service_url: str = Field(
        default="http://external-data:8002", alias="EXTERNAL_DATA_SERVICE_URL"
    )
    recommendation_service_url: str = Field(
        default="http://recommendation:8006", alias="RECOMMENDATION_SERVICE_URL"
    )
    internal_service_token: SecretStr | None = Field(
        default=None,
        alias="INTERNAL_SERVICE_TOKEN",
        description=(
            "Shared secret presented to internal services. Absent means calls that need it "
            "report the capability unavailable rather than being attempted unauthenticated."
        ),
    )

    location_search_cache_seconds: int = Field(
        default=300,
        alias="API_LOCATION_SEARCH_CACHE_SECONDS",
        ge=0,
        le=86_400,
        description=(
            "How long a browser may reuse a geocoding result. Always `private`: the query text "
            "is something a person typed, and a shared cache would serve it to somebody else."
        ),
    )

    downstream_connect_timeout_seconds: float = Field(
        default=2.0, alias="API_DOWNSTREAM_CONNECT_TIMEOUT_SECONDS", gt=0, le=30
    )
    downstream_read_timeout_seconds: float = Field(
        default=10.0, alias="API_DOWNSTREAM_READ_TIMEOUT_SECONDS", gt=0, le=120
    )

    # --- Assessment runs ------------------------------------------------------------------------

    agent_accept_timeout_seconds: float = Field(
        default=5.0,
        alias="API_AGENT_ACCEPT_TIMEOUT_SECONDS",
        gt=0,
        le=30,
        description=(
            "Budget for the agent to accept a run, not to perform it. The call returns 202 and "
            "the work is followed over status and SSE, so a long assessment must never hold the "
            "HTTP request that started it."
        ),
    )
    agent_cancel_timeout_seconds: float = Field(
        default=3.0,
        alias="API_AGENT_CANCEL_TIMEOUT_SECONDS",
        gt=0,
        le=30,
        description=(
            "Budget for propagating a cancellation. Short because the caller is already leaving, "
            "and the run is marked cancelled here whether or not the agent answers."
        ),
    )
    run_status_cache_seconds: int = Field(
        default=2,
        alias="API_RUN_STATUS_CACHE_SECONDS",
        ge=0,
        le=60,
        description=(
            "How long a browser may reuse a run's polled state. Always `private`: the state "
            "belongs to one person's journey. Small, because the point of polling is freshness."
        ),
    )
    sse_heartbeat_seconds: float = Field(
        default=15.0,
        alias="API_SSE_HEARTBEAT_SECONDS",
        gt=0,
        le=120,
        description="Idle gap after which a heartbeat is sent so intermediaries do not close it.",
    )
    sse_max_duration_seconds: float = Field(
        default=900.0,
        alias="API_SSE_MAX_DURATION_SECONDS",
        gt=0,
        le=3600,
        description=(
            "Hard cap on one stream. A client that needs longer reconnects with Last-Event-ID, "
            "which costs it nothing and stops an abandoned tab holding a worker for ever."
        ),
    )
    sse_max_streams_per_user: int = Field(
        default=4,
        alias="API_SSE_MAX_STREAMS_PER_USER",
        ge=1,
        le=64,
        description=(
            "Concurrent streams one person may hold. The contract requires a cap; without one a "
            "single client can exhaust the connection pool for everybody."
        ),
    )
    run_event_stream_ttl_seconds: int = Field(
        default=3600,
        alias="API_RUN_EVENT_STREAM_TTL_SECONDS",
        ge=60,
        le=86_400,
        description=(
            "How long a run's event stream is kept in Redis after its last write. Long enough "
            "for a client to reconnect and catch up; the key conventions forbid a permanent key."
        ),
    )
    run_event_stream_max_length: int = Field(
        default=1000,
        alias="API_RUN_EVENT_STREAM_MAX_LENGTH",
        ge=10,
        le=100_000,
        description="Bounded buffer per run, so one talkative agent cannot fill Redis.",
    )

    # --- HTTP surface ----------------------------------------------------------------------------

    # NoDecode stops pydantic-settings from trying to JSON-decode the environment value first.
    # `API_CORS_ALLOWED_ORIGINS=http://localhost:3000` is not JSON, and without this the process
    # fails to start with a parse error instead of reading the comma-separated list below.
    cors_allowed_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("http://localhost:3000",),
        alias="API_CORS_ALLOWED_ORIGINS",
        description="Exact origins, never a wildcard: responses carry credentials.",
    )
    trusted_proxy_hops: int = Field(
        default=0,
        alias="API_TRUSTED_PROXY_HOPS",
        ge=0,
        le=4,
        description=(
            "How many reverse proxies sit in front of this service. The client IP is taken that "
            "many hops from the right of X-Forwarded-For. Zero means the socket address is used "
            "and forwarding headers are ignored, so a client cannot spoof its own IP for rate "
            "limiting by sending the header itself."
        ),
    )
    max_request_body_bytes: int = Field(
        default=256 * 1024,
        alias="API_MAX_REQUEST_BODY_BYTES",
        ge=1024,
        le=16 * 1024 * 1024,
        description="Public bodies are small; a trip is a few kilobytes at most.",
    )

    # --- Rate limiting --------------------------------------------------------------------------
    #
    # Token bucket parameters per endpoint. The delivery rules require these to be tunable without
    # a code change.

    rate_limit_enabled: bool = Field(default=True, alias="API_RATE_LIMIT_ENABLED")
    rate_limit_default_capacity: int = Field(
        default=60, alias="API_RATE_LIMIT_DEFAULT_CAPACITY", ge=1, le=10_000
    )
    rate_limit_default_refill_per_second: float = Field(
        default=1.0, alias="API_RATE_LIMIT_DEFAULT_REFILL_PER_SECOND", gt=0, le=1000.0
    )
    rate_limit_location_search_capacity: int = Field(
        default=30, alias="API_RATE_LIMIT_LOCATION_SEARCH_CAPACITY", ge=1, le=10_000
    )
    rate_limit_location_search_refill_per_second: float = Field(
        default=0.5, alias="API_RATE_LIMIT_LOCATION_SEARCH_REFILL_PER_SECOND", gt=0, le=1000.0
    )
    rate_limit_assessment_capacity: int = Field(
        default=5, alias="API_RATE_LIMIT_ASSESSMENT_CAPACITY", ge=1, le=10_000
    )
    rate_limit_assessment_refill_per_second: float = Field(
        default=0.1, alias="API_RATE_LIMIT_ASSESSMENT_REFILL_PER_SECOND", gt=0, le=1000.0
    )
    rate_limit_auth_capacity: int = Field(
        default=10, alias="API_RATE_LIMIT_AUTH_CAPACITY", ge=1, le=10_000
    )
    rate_limit_auth_refill_per_second: float = Field(
        default=0.2, alias="API_RATE_LIMIT_AUTH_REFILL_PER_SECOND", gt=0, le=1000.0
    )

    # --- Observability -----------------------------------------------------------------------

    otel_exporter_endpoint: str | None = Field(
        default=None,
        alias="OTEL_EXPORTER_OTLP_ENDPOINT",
        description="Unset means traces are collected in-process and dropped rather than exported.",
    )
    metrics_enabled: bool = Field(default=True, alias="API_METRICS_ENABLED")

    # --- Readiness -----------------------------------------------------------------------------

    readiness_timeout_seconds: float = Field(
        default=3.0,
        alias="API_READINESS_TIMEOUT_SECONDS",
        gt=0,
        le=30,
        description=(
            "Whole-probe budget. Readiness must answer faster than the orchestrator's probe "
            "timeout, otherwise a slow dependency looks like a dead container."
        ),
    )

    @field_validator(
        "cors_allowed_origins",
        "oidc_allowed_algorithms",
        "trip_supported_travel_modes",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string, which is what an env var can carry."""
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("oidc_allowed_algorithms")
    @classmethod
    def _reject_symmetric_algorithms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Asymmetric signatures only.

        `none` needs no key at all. An HMAC algorithm is worse than it looks: the verifier would
        use the identity provider's *public* signing key as the shared secret, and that key is
        published in the JWKS, so anyone could mint a valid token.
        """
        allowed_prefixes = ("RS", "ES", "PS", "EdDSA")
        rejected = [
            algorithm
            for algorithm in value
            if not algorithm.startswith(allowed_prefixes) or algorithm.upper() == "NONE"
        ]
        if rejected or not value:
            raise ValueError(
                "OIDC algorithms must be asymmetric (RS*, PS*, ES*, EdDSA) and non-empty; "
                f"rejected: {rejected or ['<empty>']}"
            )
        return value

    @field_validator("internal_service_token", mode="before")
    @classmethod
    def _blank_token_is_unset(cls, value: object) -> object:
        """Treat an empty value as absent.

        `.env.example` ships `INTERNAL_SERVICE_TOKEN=` for an operator to fill in. Copied verbatim
        that is an empty string, and sending `Authorization: Bearer ` would earn a 401 from the
        internal service — reported here as that service being broken, which sends whoever is on
        call to look at the wrong thing. Unset is the honest reading, and it fails closed.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("trip_supported_travel_modes")
    @classmethod
    def _modes_are_in_the_contract(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Every configured mode must be a `TravelMode` the contract defines.

        A typo here would otherwise be indistinguishable from a deliberate restriction, and would
        silently refuse a mode the deployment meant to support.
        """
        known = {"FLIGHT", "TRAIN", "BUS", "CAR", "WALK", "BICYCLE", "MULTIMODAL"}
        unknown = sorted(set(value) - known)
        if unknown or not value:
            raise ValueError(
                f"unknown travel modes: {unknown or ['<empty>']}; allowed: {sorted(known)}"
            )
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "*" in value:
            raise ValueError(
                "CORS origins must be listed exactly. This API answers with credentials, and a "
                "wildcard would let any site read a signed-in user's trips."
            )
        return value

    @field_validator("oidc_issuer")
    @classmethod
    def _issuer_has_no_trailing_slash(cls, value: str) -> str:
        # The issuer is compared byte-for-byte against the `iss` claim, where a trailing slash
        # would make every token look like it came from somewhere else.
        return value.rstrip("/")

    @model_validator(mode="after")
    def _production_requires_transport_security(self) -> Settings:
        if self.app_env != "production":
            return self

        insecure = [origin for origin in self.cors_allowed_origins if origin.startswith("http://")]
        if insecure:
            raise ValueError(
                f"Plain-HTTP CORS origins are not allowed in production: {insecure}. "
                "A cookie sent over http:// is readable by anyone on the path."
            )
        if self.oidc_issuer.startswith("http://"):
            raise ValueError(
                "OIDC_ISSUER must be https in production; tokens verified over plain HTTP can be "
                "substituted in transit."
            )
        if not self.emergency_encryption_keys:
            raise ValueError(
                "API_EMERGENCY_ENCRYPTION_KEYS is required in production. The emergency profile "
                "holds medical details, and starting without a key would mean the endpoint is "
                "silently unavailable to people who may need it most."
            )
        return self

    # --- Derived values ------------------------------------------------------------------------

    @property
    def database_url(self) -> str:
        """Async DSN used by the application."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN for Alembic, which does not run in the event loop."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def redis_namespace(self) -> str:
        """`sta:{env}:` — the prefix every key this service writes must start with."""
        return f"{self.redis_key_prefix}:{self.app_env}"

    @property
    def oidc_discovery_url(self) -> str:
        return f"{self.oidc_issuer}/.well-known/openid-configuration"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings are read once per process; tests clear the cache instead of mutating the object."""
    # Every field is read from the environment, so no constructor argument is needed here.
    return Settings()
