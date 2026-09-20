"""Builds the adapter for each provider the registry knows about.

Only `ACTIVE` providers get an adapter. Asking for a capability whose provider
is blocked raises OUTSIDE_COVERAGE with the registry's own reason, which is how
an unconfigured credential reaches the caller as an honest unavailable state
instead of a 500.
"""

from __future__ import annotations

from app.adapters.base import HealthRecorder, ProviderAdapter
from app.adapters.eonet import EonetAdapter
from app.adapters.gdacs import GdacsAdapter
from app.adapters.gtfs import GtfsAdapter
from app.adapters.open_meteo_geocoding import OpenMeteoGeocodingAdapter
from app.adapters.open_meteo_weather import OpenMeteoWeatherAdapter
from app.adapters.openrouteservice import OpenRouteServiceAdapter
from app.adapters.ors_pois import OrsPoisAdapter
from app.adapters.usgs import UsgsAdapter
from app.cache.provider_cache import ProviderCache
from app.domain.enums import ProviderKind
from app.domain.errors import ProviderError, ProviderErrorCode
from app.providers.registry import ResolvedRegistry
from app.transport.http import ProviderTransport

ADAPTERS: dict[str, type[ProviderAdapter]] = {  # type: ignore[type-arg]
    "open_meteo_geocoding": OpenMeteoGeocodingAdapter,
    "open_meteo_forecast": OpenMeteoWeatherAdapter,
    "usgs_earthquake": UsgsAdapter,
    "gdacs": GdacsAdapter,
    "nasa_eonet": EonetAdapter,
    "openrouteservice": OpenRouteServiceAdapter,
    "ors_pois": OrsPoisAdapter,
    "gtfs_registry": GtfsAdapter,
}


class AdapterRegistry:
    def __init__(
        self,
        registry: ResolvedRegistry,
        transport: ProviderTransport,
        cache: ProviderCache | None,
        *,
        env: str,
        health_recorder: HealthRecorder | None = None,
    ) -> None:
        self._registry = registry
        self._adapters: dict[str, ProviderAdapter] = {}  # type: ignore[type-arg]

        for resolved in registry.all():
            adapter_class = ADAPTERS.get(resolved.id)
            if adapter_class is None or not resolved.is_callable:
                continue
            self._adapters[resolved.id] = adapter_class(
                resolved, transport, cache, env=env, health_recorder=health_recorder
            )

    def get(self, provider_id: str) -> ProviderAdapter | None:  # type: ignore[type-arg]
        return self._adapters.get(provider_id)

    def all_for_kind(self, kind: ProviderKind) -> list[ProviderAdapter]:  # type: ignore[type-arg]
        """Every usable adapter for a capability, in registry order.

        Disaster sources are complementary rather than interchangeable - the
        same earthquake appears in several of them and the plan forbids
        dropping a duplicate - so the caller fans out to all of them.
        """
        return [
            adapter
            for resolved in self._registry.for_kind(kind)
            if (adapter := self._adapters.get(resolved.id)) is not None
        ]

    def blocked_reason(self, kind: ProviderKind) -> str:
        return (
            "; ".join(
                f"{p.id}: {p.reason}" for p in self._registry.for_kind(kind) if p.reason
            )
            or f"no provider configured for {kind}"
        )

    def for_kind(self, kind: ProviderKind) -> ProviderAdapter:  # type: ignore[type-arg]
        """First usable adapter for a capability, or an explicit unavailable."""
        for resolved in self._registry.for_kind(kind):
            adapter = self._adapters.get(resolved.id)
            if adapter is not None:
                return adapter

        blocked = self._registry.for_kind(kind)
        reason = (
            "; ".join(f"{p.id}: {p.reason}" for p in blocked if p.reason)
            or f"no provider configured for {kind}"
        )
        raise ProviderError(
            ProviderErrorCode.OUTSIDE_COVERAGE,
            provider_id=str(kind),
            message=reason,
        )

    @property
    def ids(self) -> list[str]:
        return list(self._adapters)
