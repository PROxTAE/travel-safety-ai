from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: Literal["development", "test", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    CONTRACT_VERSION: str = "1.0.0"
    SERVICE_NAME: str = "recommendation"
    SERVICE_PORT: int = 8006

    # Internal service-to-service auth token
    INTERNAL_SERVICE_TOKEN: str = Field(default="")

    # PostgreSQL Database
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "smart_travel"
    POSTGRES_USER: str = "smart_travel"
    POSTGRES_PASSWORD: str = "smart_travel_password"  # noqa: S105
    POSTGRES_SCHEMA: str = "recommendation"
    TEST_DATABASE_URL: str | None = None

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Emergency Directory Source Path
    EMERGENCY_DIRECTORY_PATH: str = str(
        Path(__file__).resolve().parent.parent / "emergency-directory" / "sources.yaml"
    )

    # Web Push / VAPID (optional; graceful degradation if not provided)
    VAPID_PRIVATE_KEY: str | None = None
    VAPID_PUBLIC_KEY: str | None = None
    VAPID_CLAIMS_SUB: str = "mailto:safety-alerts@smarttravel.local"

    # Email / SMS providers (optional)
    EMAIL_PROVIDER_ENABLED: bool = False
    SMS_PROVIDER_ENABLED: bool = False

    # OpenTelemetry
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_SERVICE_NAME: str = "recommendation"

    def database_url(self) -> str:
        if self.TEST_DATABASE_URL:
            # If using sqlite in memory or asyncpg url
            url = self.TEST_DATABASE_URL
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+asyncpg://", 1)
            if url.startswith("postgresql+psycopg://"):
                return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def sync_database_url(self) -> str:
        if self.TEST_DATABASE_URL:
            url = self.TEST_DATABASE_URL
            if url.startswith("postgresql+asyncpg://"):
                return url.replace("postgresql+asyncpg://", "postgresql://", 1)
            return url
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
