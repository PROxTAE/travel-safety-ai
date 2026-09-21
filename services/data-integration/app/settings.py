"""Environment-only runtime configuration."""

from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    contract_version: str = Field(default="1.0.0", alias="CONTRACT_VERSION")
    internal_service_token: SecretStr | None = Field(default=None, alias="INTERNAL_SERVICE_TOKEN")
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="smart_travel", alias="POSTGRES_DB")
    postgres_user: str = Field(default="smart_travel", alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(default=SecretStr(""), alias="POSTGRES_PASSWORD")
    quarantine_retention_days: int = Field(default=30, alias="QUARANTINE_RETENTION_DAYS", ge=1)
    corridor_radius_m: float = Field(default=5000, alias="CORRIDOR_RADIUS_M", gt=0)
    route_sample_spacing_m: float = Field(default=1000, alias="ROUTE_SAMPLE_SPACING_M", gt=0)
    weather_time_tolerance_seconds: float = Field(
        default=1800, alias="WEATHER_TIME_TOLERANCE_SECONDS", ge=0
    )
    transport_time_tolerance_seconds: float = Field(
        default=600, alias="TRANSPORT_TIME_TOLERANCE_SECONDS", ge=0
    )
    duplicate_distance_m: float = Field(default=25000, alias="DUPLICATE_DISTANCE_M", ge=0)
    duplicate_time_seconds: float = Field(default=3600, alias="DUPLICATE_TIME_SECONDS", ge=0)
    quality_minimum_score: float = Field(default=0.85, alias="QUALITY_MINIMUM_SCORE", ge=0, le=1)
    quality_minimum_coverage: float = Field(
        default=0.8, alias="QUALITY_MINIMUM_COVERAGE", ge=0, le=1
    )

    @field_validator("internal_service_token", mode="after")
    @classmethod
    def empty_token_is_absent(cls, value: SecretStr | None) -> SecretStr | None:
        return value if value and value.get_secret_value().strip() else None

    @property
    def database_url(self) -> str:
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
