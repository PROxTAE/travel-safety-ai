from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

SERVICE_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Validated runtime configuration with no usable secret defaults."""

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    contract_version: str = Field(default="1.0.0", validation_alias="CONTRACT_VERSION")
    service_version: str = Field(default="0.1.0", validation_alias="RISK_KNOWLEDGE_VERSION")

    internal_api_token: SecretStr | None = Field(
        default=None,
        validation_alias="INTERNAL_SERVICE_TOKEN",
    )
    data_integration_url: str = Field(
        default="http://data-integration:8003",
        validation_alias="DATA_INTEGRATION_URL",
    )
    data_integration_token: SecretStr | None = Field(
        default=None,
        validation_alias="DATA_INTEGRATION_SERVICE_TOKEN",
    )

    database_url: SecretStr | None = Field(
        default=None,
        validation_alias="RISK_KNOWLEDGE_DATABASE_URL",
    )
    postgres_host: str = Field(default="postgres", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="smart_travel", validation_alias="POSTGRES_DB")
    postgres_user: str = Field(default="smart_travel", validation_alias="POSTGRES_USER")
    postgres_password: SecretStr | None = Field(default=None, validation_alias="POSTGRES_PASSWORD")
    database_pool_size: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias="RISK_KNOWLEDGE_DATABASE_POOL_SIZE",
    )

    qdrant_url: str = Field(default="http://qdrant:6333", validation_alias="QDRANT_URL")
    qdrant_api_key: SecretStr | None = Field(default=None, validation_alias="QDRANT_API_KEY")
    qdrant_collection_prefix: str = Field(
        default="sta-knowledge",
        validation_alias="RISK_KNOWLEDGE_QDRANT_COLLECTION_PREFIX",
    )
    qdrant_active_alias: str = Field(
        default="sta-knowledge-active",
        validation_alias="RISK_KNOWLEDGE_QDRANT_ACTIVE_ALIAS",
    )
    qdrant_vector_size: int = Field(
        default=768,
        ge=1,
        validation_alias="RISK_KNOWLEDGE_QDRANT_VECTOR_SIZE",
    )

    artifact_root: Path = Field(
        default=Path("/artifacts"),
        validation_alias="RISK_KNOWLEDGE_ARTIFACT_ROOT",
    )
    artifact_signature_required: bool = Field(
        default=True,
        validation_alias="RISK_KNOWLEDGE_REQUIRE_ARTIFACT_SIGNATURE",
    )
    artifact_public_key_path: Path | None = Field(
        default=None,
        validation_alias="RISK_KNOWLEDGE_ARTIFACT_PUBLIC_KEY_PATH",
    )
    active_model_name: str = Field(
        default="route-risk-baseline",
        validation_alias="RISK_KNOWLEDGE_ACTIVE_MODEL_NAME",
    )

    feature_schema_path: Path = Field(
        default=SERVICE_ROOT / "governance" / "feature_schema.v1.yaml",
        validation_alias="RISK_KNOWLEDGE_FEATURE_SCHEMA_PATH",
    )
    model_acceptance_path: Path = Field(
        default=SERVICE_ROOT / "governance" / "model_acceptance.yaml",
        validation_alias="RISK_KNOWLEDGE_MODEL_ACCEPTANCE_PATH",
    )
    route_policy_path: Path = Field(
        default=SERVICE_ROOT / "governance" / "route_exposure_policy.v1.yaml",
        validation_alias="RISK_KNOWLEDGE_ROUTE_POLICY_PATH",
    )
    knowledge_sources_path: Path = Field(
        default=SERVICE_ROOT / "knowledge" / "sources.yaml",
        validation_alias="RISK_KNOWLEDGE_SOURCES_PATH",
    )

    dependency_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        le=10,
        validation_alias="RISK_KNOWLEDGE_DEPENDENCY_TIMEOUT_SECONDS",
    )
    artifact_verification_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        le=120,
        validation_alias="RISK_KNOWLEDGE_ARTIFACT_VERIFICATION_TIMEOUT_SECONDS",
    )
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    otel_service_name: str = Field(
        default="risk-knowledge",
        validation_alias="OTEL_SERVICE_NAME",
    )

    @field_validator("qdrant_url")
    @classmethod
    def validate_qdrant_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("QDRANT_URL must use http or https")
        return normalized

    @field_validator("data_integration_url")
    @classmethod
    def validate_data_integration_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("DATA_INTEGRATION_URL must use http or https")
        return normalized

    def sqlalchemy_url(self) -> URL | str:
        if self.database_url is not None and self.database_url.get_secret_value():
            return self.database_url.get_secret_value()
        if self.postgres_password is None or not self.postgres_password.get_secret_value():
            raise ValueError("POSTGRES_PASSWORD or RISK_KNOWLEDGE_DATABASE_URL is required")
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    def sqlalchemy_url_string(self) -> str:
        url = self.sqlalchemy_url()
        if isinstance(url, URL):
            return url.render_as_string(hide_password=False)
        return url

    @property
    def internal_auth_configured(self) -> bool:
        return bool(self.internal_api_token and self.internal_api_token.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
