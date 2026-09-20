"""The registry is the gate every provider call passes through, so its status
reconciliation is the highest-value thing to test in Phase 1."""

from __future__ import annotations

import pytest

from app.domain.enums import ProviderKind, ProviderStatus
from app.providers.registry import ResolvedRegistry, _resolve, load_registry
from app.settings import Settings, get_settings
from tests.conftest import REGISTRY_PATH


@pytest.fixture
def registry() -> ResolvedRegistry:
    return ResolvedRegistry(load_registry(REGISTRY_PATH), get_settings())


def test_registry_file_parses_and_ids_are_unique(registry: ResolvedRegistry) -> None:
    ids = [p.id for p in registry.all()]
    assert len(ids) == len(set(ids))
    assert len(ids) == 9


def test_keyless_providers_are_callable(registry: ResolvedRegistry) -> None:
    expected = {
        "open_meteo_geocoding",
        "open_meteo_forecast",
        "usgs_earthquake",
        "gdacs",
        "nasa_eonet",
    }
    assert {p.id for p in registry.all() if p.is_callable} == expected


def test_missing_credential_downgrades_an_active_provider(settings: Settings) -> None:
    """A provider marked ACTIVE in the file must not be callable when its key is
    absent. Without this, the failure surfaces as a 401 from the provider at
    request time instead of an honest unavailable capability."""
    raw = load_registry(REGISTRY_PATH)
    ors = next(p for p in raw.providers if p.id == "openrouteservice")
    ors.status = ProviderStatus.ACTIVE  # pretend the Lead approved it

    resolved = ResolvedRegistry(raw, settings).get("openrouteservice")
    assert resolved is not None
    assert resolved.effective_status is ProviderStatus.PENDING_CREDENTIAL
    assert resolved.missing_credentials == ["ORS_API_KEY"]
    assert not resolved.is_callable
    assert resolved.reason is not None and "ORS_API_KEY" in resolved.reason


def test_present_credential_does_not_self_approve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supplying a key must not promote a provider nobody has approved - the
    status field records an approval decision, not just reachability.

    Written against a synthetic entry rather than whichever provider happens to
    be pending today. The first version of this test used openrouteservice; the
    moment that provider was approved the test went green for the wrong reason
    and stopped guarding anything.
    """
    monkeypatch.setenv("ORS_API_KEY", "not-a-real-key")
    get_settings.cache_clear()

    approved = next(
        entry
        for entry in load_registry(REGISTRY_PATH).providers
        if entry.id == "openrouteservice"
    )
    pending = approved.model_copy(
        update={"status": ProviderStatus.PENDING_CREDENTIAL}
    )

    resolved = _resolve(pending, get_settings())
    assert resolved.effective_status is ProviderStatus.PENDING_CREDENTIAL
    assert resolved.missing_credentials == []
    assert resolved.reason is not None and "not yet approved" in resolved.reason


def test_blocked_providers_carry_a_reason(registry: ResolvedRegistry) -> None:
    for provider in registry.all():
        if not provider.is_callable:
            assert provider.reason, f"{provider.id} is blocked without a reason"


def test_every_provider_declares_attribution(registry: ResolvedRegistry) -> None:
    for provider in registry.all():
        attribution = provider.entry.attribution
        if attribution.required and provider.entry.kind is not ProviderKind.TRANSIT:
            assert attribution.text, f"{provider.id} requires attribution but has no text"


def test_attributions_are_deduplicated(registry: ResolvedRegistry) -> None:
    texts = registry.attributions(["usgs_earthquake", "usgs_earthquake", "gdacs"])
    assert len(texts) == 2


def test_active_providers_have_a_health_probe(registry: ResolvedRegistry) -> None:
    for provider in registry.all():
        if provider.is_callable:
            assert provider.entry.health.url, f"{provider.id} has no health probe"


def test_active_providers_resolve_a_base_url(registry: ResolvedRegistry) -> None:
    for provider in registry.all():
        if provider.is_callable:
            assert provider.base_url, f"{provider.id} has no base URL configured"


def test_cache_ttls_match_the_shared_freshness_table(
    registry: ResolvedRegistry,
) -> None:
    """Shared context § 10: disaster 10 min, hourly forecast 60 min."""
    ttls = {p.id: p.entry.cache.effective_ttl for p in registry.all()}
    assert ttls["usgs_earthquake"] <= 600
    assert ttls["gdacs"] <= 600
    assert ttls["nasa_eonet"] <= 600
    assert ttls["open_meteo_forecast"] <= 3600


def test_every_provider_has_a_positive_cache_ttl(registry: ResolvedRegistry) -> None:
    """The Redis conventions forbid a key without a TTL."""
    for provider in registry.all():
        assert provider.entry.cache.effective_ttl > 0


def test_an_unverified_quota_carries_no_number(registry: ResolvedRegistry) -> None:
    """The registry must never imply a ceiling nobody measured.

    A provider may say "verified" only once someone has read the real limit off
    the provider - for openrouteservice that was its own X-Ratelimit-* headers
    on 2026-09-20. Everything still unverified must leave `daily_limit` empty
    rather than carrying a plausible guess.
    """
    for provider in registry.all():
        quota = provider.entry.quota
        if quota.verification_required:
            assert quota.daily_limit is None, (
                f"{provider.id} claims a quota of {quota.daily_limit} "
                "while still marked unverified"
            )
        else:
            assert quota.daily_limit is not None, (
                f"{provider.id} is marked verified but records no number"
            )


def test_the_two_openrouteservice_endpoints_have_separate_budgets(
    registry: ResolvedRegistry,
) -> None:
    """Measured, not assumed: directions allows 200 calls a day and POIs 50.

    Sharing one account does not mean sharing one pool. Treating them as one
    would let route lookups quietly exhaust the emergency directory.
    """
    routing = registry.get("openrouteservice")
    pois = registry.get("ors_pois")
    assert routing is not None and pois is not None
    assert routing.entry.quota.daily_limit == 200
    assert pois.entry.quota.daily_limit == 50


def test_registry_has_no_inline_secret() -> None:
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        if key.strip() in {"env", "owner"}:
            continue
        assert "secret" not in value.lower() or "client_secret" in value.upper().lower()


def test_blank_credential_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: `.env.example` ships `ORS_API_KEY=` with no value, so an
    unfilled deployment presents an empty string. Treating that as "present"
    made the health endpoint claim the key was supplied."""
    monkeypatch.setenv("ORS_API_KEY", "   ")
    get_settings.cache_clear()

    raw = load_registry(REGISTRY_PATH)
    ors = next(p for p in raw.providers if p.id == "openrouteservice")
    ors.status = ProviderStatus.ACTIVE

    resolved = ResolvedRegistry(raw, get_settings()).get("openrouteservice")
    assert resolved is not None
    assert resolved.missing_credentials == ["ORS_API_KEY"]
    assert not resolved.is_callable


def test_blank_internal_token_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "")
    get_settings.cache_clear()
    assert get_settings().internal_service_token is None
