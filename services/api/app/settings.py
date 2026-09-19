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

    # --- OIDC (verified in phase 2; discovery is probed by readiness from phase 1) --------------

    oidc_issuer: str = Field(
        default="http://keycloak:8080/realms/smart-travel", alias="OIDC_ISSUER"
    )
    oidc_audience: str = Field(default="smart-travel-api", alias="OIDC_AUDIENCE")
    oidc_discovery_timeout_seconds: float = Field(
        default=3.0, alias="API_OIDC_TIMEOUT_SECONDS", gt=0, le=30
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

    downstream_connect_timeout_seconds: float = Field(
        default=2.0, alias="API_DOWNSTREAM_CONNECT_TIMEOUT_SECONDS", gt=0, le=30
    )
    downstream_read_timeout_seconds: float = Field(
        default=10.0, alias="API_DOWNSTREAM_READ_TIMEOUT_SECONDS", gt=0, le=120
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

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string, which is what an env var can carry."""
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
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
