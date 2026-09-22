from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True, extra="ignore")

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    service_version: str = Field(default="0.1.0", validation_alias="DECISION_ENGINE_VERSION")
    contract_version: str = Field(default="1.0.0", validation_alias="CONTRACT_VERSION")
    internal_service_token: str | None = Field(default=None, validation_alias="INTERNAL_SERVICE_TOKEN")
    database_url: str | None = Field(default=None, validation_alias="DECISION_DATABASE_URL")
    policy_path: Path = Field(default=SERVICE_ROOT / "policies" / "v1" / "decision-table.yaml", validation_alias="DECISION_POLICY_PATH")
    policy_checksum: str | None = Field(default=None, validation_alias="DECISION_POLICY_CHECKSUM")
    migrations_path: Path = Field(
        default=SERVICE_ROOT / "migrations",
        validation_alias="DECISION_MIGRATIONS_PATH",
    )

    @property
    def internal_auth_configured(self) -> bool:
        return bool(self.internal_service_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()