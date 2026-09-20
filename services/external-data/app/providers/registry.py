"""Typed view over config/providers.yaml.

The YAML is the governance record; this module turns it into the objects the
runtime uses and - importantly - reconciles the declared status with what the
environment can actually satisfy. A provider declared ACTIVE whose credential is
missing becomes PENDING_CREDENTIAL here, so a misconfigured deployment degrades
honestly instead of failing at call time.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ProviderKind, ProviderStatus, SourceAuthority
from app.settings import Settings, get_settings


class TimeoutPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connect_seconds: float = 3.0
    read_seconds: float = 10.0
    total_seconds: float = 15.0


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = 3
    backoff: str = "exponential_jitter"
    initial_backoff_seconds: float = 0.5
    retry_on_status: list[int] = Field(
        default_factory=lambda: [408, 429, 500, 502, 503, 504]
    )


class CircuitPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failure_threshold: int = 5
    open_seconds: float = 60.0
    half_open_probes: int = 1


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_raw_body: bool = False
    fetch_log_days: int = 30
    cache_backend: str = "redis"


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    circuit_breaker: CircuitPolicy = Field(default_factory=CircuitPolicy)
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)


class HealthProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str | None = None
    method: str = "GET"
    expect_status: int = 200
    notes: str | None = None


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required: bool | str = False
    env: str | list[str] | None = None
    owner: str | None = None

    @property
    def env_names(self) -> list[str]:
        if self.env is None:
            return []
        return [self.env] if isinstance(self.env, str) else list(self.env)

    @property
    def is_required(self) -> bool:
        # "per_feed" means required, but resolved per feed rather than globally.
        return self.required is True


class License(BaseModel):
    model_config = ConfigDict(extra="allow")
    spdx_or_name: str | None = None
    url: str | None = None
    upstream: str | None = None
    commercial_use: bool | str | None = None


class Attribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required: bool = True
    text: str | None = None


class Quota(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documented: str | None = None
    source: str | None = None
    verification_required: bool = True


class CachePolicy(BaseModel):
    model_config = ConfigDict(extra="allow")
    ttl_seconds: int | None = None
    negative_ttl_seconds: int | None = None
    static_ttl_seconds: int | None = None
    realtime_ttl_seconds: int | None = None
    key_fields: list[str] = Field(default_factory=list)

    @property
    def effective_ttl(self) -> int:
        for value in (
            self.ttl_seconds,
            self.realtime_ttl_seconds,
            self.static_ttl_seconds,
        ):
            if value is not None:
                return value
        return 300


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    global_: bool | str = Field(default=False, alias="global")
    notes: str | None = None


class ProviderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: str
    kind: ProviderKind
    status: ProviderStatus
    authority: SourceAuthority
    base_url_env: str | None = None
    endpoints: dict[str, str] = Field(default_factory=dict)
    health: HealthProbe = Field(default_factory=HealthProbe)
    credential: Credential = Field(default_factory=Credential)
    coverage: Coverage
    license: License = Field(default_factory=License)
    attribution: Attribution = Field(default_factory=Attribution)
    quota: Quota = Field(default_factory=Quota)
    cache: CachePolicy = Field(default_factory=CachePolicy)
    feeds: list[dict[str, Any]] = Field(default_factory=list)


class ResolvedProvider(BaseModel):
    """A registry entry reconciled against the running environment."""

    model_config = ConfigDict(extra="forbid")

    entry: ProviderEntry
    effective_status: ProviderStatus
    base_url: str | None = None
    missing_credentials: list[str] = Field(default_factory=list)
    reason: str | None = None

    @property
    def id(self) -> str:
        return self.entry.id

    @property
    def is_callable(self) -> bool:
        return self.effective_status is ProviderStatus.ACTIVE


class ProviderRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    contract_version: str
    module: str
    phase: str
    defaults: Defaults = Field(default_factory=Defaults)
    providers: list[ProviderEntry]


def _resolve(entry: ProviderEntry, settings: Settings) -> ResolvedProvider:
    missing = [
        name
        for name in entry.credential.env_names
        if entry.credential.is_required and settings.credential_for(name) is None
    ]

    status = entry.status
    reason: str | None = None

    if status is ProviderStatus.ACTIVE and missing:
        # Declared active but the environment cannot satisfy it.
        status = ProviderStatus.PENDING_CREDENTIAL
        reason = "missing credential: " + ", ".join(missing)
    elif (
        status is ProviderStatus.PENDING_CREDENTIAL
        and not missing
        and entry.credential.env_names
    ):
        # The credential has since been supplied, so the registry file is stale
        # but the deployment is fine. Promoting silently would bypass the Lead
        # approval this status records, so stay blocked and say why.
        reason = "credential present but provider not yet approved in providers.yaml"
    elif status is not ProviderStatus.ACTIVE:
        reason = "registry status is " + str(status)

    return ResolvedProvider(
        entry=entry,
        effective_status=status,
        base_url=settings.base_url_for(entry.base_url_env),
        missing_credentials=missing,
        reason=reason,
    )


class ResolvedRegistry:
    """Registry plus environment reconciliation. Built once at startup."""

    def __init__(self, registry: ProviderRegistry, settings: Settings) -> None:
        self.registry = registry
        self.defaults = registry.defaults
        self._by_id: dict[str, ResolvedProvider] = {
            entry.id: _resolve(entry, settings) for entry in registry.providers
        }

    def get(self, provider_id: str) -> ResolvedProvider | None:
        return self._by_id.get(provider_id)

    def all(self) -> list[ResolvedProvider]:
        return list(self._by_id.values())

    def for_kind(self, kind: ProviderKind) -> list[ResolvedProvider]:
        return [p for p in self._by_id.values() if p.entry.kind is kind]

    def callable_for_kind(self, kind: ProviderKind) -> list[ResolvedProvider]:
        return [p for p in self.for_kind(kind) if p.is_callable]

    def attributions(self, provider_ids: list[str]) -> list[str]:
        texts: list[str] = []
        for provider_id in provider_ids:
            resolved = self._by_id.get(provider_id)
            if resolved and resolved.entry.attribution.required:
                text = resolved.entry.attribution.text
                if text and text not in texts:
                    texts.append(text)
        return texts


def load_registry(path: Path) -> ProviderRegistry:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return ProviderRegistry.model_validate(raw)


@lru_cache(maxsize=1)
def get_resolved_registry() -> ResolvedRegistry:
    settings = get_settings()
    return ResolvedRegistry(load_registry(settings.provider_config_path), settings)
