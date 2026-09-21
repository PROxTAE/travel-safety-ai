"""Runtime configuration.

Every value comes from the environment. Nothing here carries a default that
would let a credential-dependent provider look available when it is not.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # the container gets a real environment, not a mounted .env
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- runtime
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    contract_version: str = Field(default="1.0.0", alias="CONTRACT_VERSION")
    service_name: str = "external-data"
    service_port: int = 8002

    # ------------------------------------------------------------ internal auth
    # Shared secret between internal services. Callers send it as
    # `Authorization: Bearer <token>`. Absent => every internal route returns 401
    # and readiness reports NOT ready. We never fall back to "open in dev".
    internal_service_token: SecretStr | None = Field(default=None, alias="INTERNAL_SERVICE_TOKEN")

    # --------------------------------------------------------------- storage
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="smart_travel", alias="POSTGRES_DB")
    postgres_user: str = Field(default="smart_travel", alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(default=SecretStr(""), alias="POSTGRES_PASSWORD")
    db_schema: str = "provider"

    redis_url: RedisDsn = Field(default=RedisDsn("redis://redis:6379/0"), alias="REDIS_URL")

    # ------------------------------------------------------- provider registry
    provider_config_path: Path = Field(
        default=Path("/app/config/providers.yaml"), alias="GTFS_PROVIDER_CONFIG"
    )

    # Base URLs are config, never user input (SSRF rule, shared context § 11).
    open_meteo_base_url: str = Field(
        default="https://api.open-meteo.com", alias="OPEN_METEO_BASE_URL"
    )
    open_meteo_geocoding_url: str = Field(
        default="https://geocoding-api.open-meteo.com", alias="OPEN_METEO_GEOCODING_URL"
    )
    ors_base_url: str = Field(default="https://api.openrouteservice.org", alias="ORS_BASE_URL")
    amadeus_base_url: str = Field(default="https://api.amadeus.com", alias="AMADEUS_BASE_URL")
    usgs_feed_url: str = Field(
        default=("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"),
        alias="USGS_FEED_URL",
    )
    gdacs_base_url: str = Field(default="https://www.gdacs.org/gdacsapi", alias="GDACS_BASE_URL")
    eonet_base_url: str = Field(
        default="https://eonet.gsfc.nasa.gov/api/v3", alias="EONET_BASE_URL"
    )

    # ----------------------------------------------------------- credentials
    # Optional on purpose: absence is a legitimate state that must show up as an
    # explicit unavailable capability, never as a startup crash.
    ors_api_key: SecretStr | None = Field(default=None, alias="ORS_API_KEY")
    amadeus_client_id: SecretStr | None = Field(default=None, alias="AMADEUS_CLIENT_ID")
    amadeus_client_secret: SecretStr | None = Field(default=None, alias="AMADEUS_CLIENT_SECRET")

    # ------------------------------------------------------ health probing
    # How often to check each ACTIVE provider's documented health URL. Without
    # it a provider served entirely from cache never produces an observation
    # and stays UNKNOWN. 0 disables the probe entirely.
    provider_health_probe_seconds: float = Field(
        default=300.0, alias="PROVIDER_HEALTH_PROBE_SECONDS", ge=0.0
    )

    # ------------------------------------------------------------ observability
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator(
        "internal_service_token",
        "ors_api_key",
        "amadeus_client_id",
        "amadeus_client_secret",
        mode="after",
    )
    @classmethod
    def _blank_secret_is_absent(cls, v: SecretStr | None) -> SecretStr | None:
        """`.env.example` ships these keys with an empty value, so a deployment
        that has not filled one in presents an empty string rather than an unset
        variable. An empty credential is a missing credential."""
        if v is not None and not v.get_secret_value().strip():
            return None
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() not in {"development", "dev", "test"}

    @property
    def database_url(self) -> str:
        """SQLAlchemy async URL. Built here so the password never lands in a log."""
        dsn = PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)

    def credential_for(self, env_name: str) -> SecretStr | None:
        """Look up a provider credential by the env var name in providers.yaml."""
        return {
            "ORS_API_KEY": self.ors_api_key,
            "AMADEUS_CLIENT_ID": self.amadeus_client_id,
            "AMADEUS_CLIENT_SECRET": self.amadeus_client_secret,
        }.get(env_name)

    def base_url_for(self, env_name: str | None) -> str | None:
        if env_name is None:
            return None
        return {
            "OPEN_METEO_BASE_URL": self.open_meteo_base_url,
            "OPEN_METEO_GEOCODING_URL": self.open_meteo_geocoding_url,
            "ORS_BASE_URL": self.ors_base_url,
            "AMADEUS_BASE_URL": self.amadeus_base_url,
            "USGS_FEED_URL": self.usgs_feed_url,
            "GDACS_BASE_URL": self.gdacs_base_url,
            "EONET_BASE_URL": self.eonet_base_url,
        }.get(env_name)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
