"""The JWKS cache.

Three behaviours are load-bearing and none is visible from the token tests:

* the common path touches no network;
* a key id the cache has not seen triggers exactly one refresh, because that is what a rotation
  looks like from here;
* that refresh is rate-limited, because `kid` is attacker-controlled and an unlimited refresh makes
  this service an amplifier pointed at its own identity provider.

httpx is intercepted with respx so the cache's real code runs against real HTTP semantics.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.auth.jwks import JwksCache, JwksUnavailable, SigningKeyNotFound
from app.settings import Settings
from tests.conftest import build_settings
from tests.keys import DEFAULT_ISSUER, SigningKeyPair

DISCOVERY_URL = f"{DEFAULT_ISSUER}/.well-known/openid-configuration"
JWKS_URL = f"{DEFAULT_ISSUER}/protocol/openid-connect/certs"


def discovery_body(issuer: str = DEFAULT_ISSUER) -> dict[str, object]:
    return {"issuer": issuer, "jwks_uri": JWKS_URL}


def jwks_body(*keys: SigningKeyPair) -> dict[str, object]:
    return {"keys": [key.public_jwk for key in keys]}


@pytest.fixture
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
def rotated_key() -> SigningKeyPair:
    return SigningKeyPair.generate(kid="rotated-key")


async def build_cache(settings: Settings) -> JwksCache:
    return JwksCache(settings=settings, client=httpx.AsyncClient())


@respx.mock
async def test_the_first_lookup_fetches_discovery_then_the_keys(
    key: SigningKeyPair, settings: Settings
) -> None:
    discovery = respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=discovery_body())
    )
    jwks = respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body(key)))

    cache = await build_cache(settings)
    assert await cache.get_key(key.kid) == key.public_jwk

    assert discovery.call_count == 1
    assert jwks.call_count == 1


@respx.mock
async def test_a_cached_key_costs_no_request(key: SigningKeyPair, settings: Settings) -> None:
    """The common path is every authenticated request; it must not call the provider."""
    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=discovery_body()))
    jwks = respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body(key)))

    cache = await build_cache(settings)
    for _ in range(25):
        await cache.get_key(key.kid)

    assert jwks.call_count == 1


@respx.mock
async def test_an_unknown_key_id_triggers_one_refresh(
    key: SigningKeyPair, rotated_key: SigningKeyPair, settings: Settings
) -> None:
    """A rotation looks exactly like this: a token arrives signed by a key we have never seen."""
    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=discovery_body()))
    jwks = respx.get(JWKS_URL).mock(
        side_effect=[
            httpx.Response(200, json=jwks_body(key)),
            httpx.Response(200, json=jwks_body(key, rotated_key)),
        ]
    )

    cache = await build_cache(settings)
    await cache.get_key(key.kid)

    assert await cache.get_key(rotated_key.kid) == rotated_key.public_jwk
    assert jwks.call_count == 2


@respx.mock
async def test_repeated_unknown_key_ids_do_not_become_repeated_fetches(
    key: SigningKeyPair, settings: Settings
) -> None:
    """The amplification case.

    `kid` comes from the token, so an attacker chooses it. Without the cooldown, a stream of
    tokens carrying random key ids would be one outbound fetch each, with this service doing the
    work against its own identity provider.
    """
    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=discovery_body()))
    jwks = respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body(key)))

    cache = await build_cache(settings)
    await cache.get_key(key.kid)
    fetches_after_warmup = jwks.call_count

    for index in range(50):
        with pytest.raises(SigningKeyNotFound):
            await cache.get_key(f"forged-kid-{index}")

    assert (
        jwks.call_count - fetches_after_warmup <= 1
    ), f"{jwks.call_count - fetches_after_warmup} fetches for 50 forged key ids"


@respx.mock
async def test_a_zero_cooldown_still_refreshes(
    key: SigningKeyPair, rotated_key: SigningKeyPair
) -> None:
    """The cooldown is configurable; setting it to zero must not break rotation handling."""
    settings = build_settings(API_OIDC_JWKS_MIN_REFRESH_SECONDS="0")
    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=discovery_body()))
    respx.get(JWKS_URL).mock(
        side_effect=[
            httpx.Response(200, json=jwks_body(key)),
            httpx.Response(200, json=jwks_body(key, rotated_key)),
        ]
    )

    cache = JwksCache(settings=settings, client=httpx.AsyncClient())
    await cache.get_key(key.kid)

    assert await cache.get_key(rotated_key.kid) == rotated_key.public_jwk


@respx.mock
async def test_a_discovery_document_for_a_different_realm_is_refused(
    settings: Settings,
) -> None:
    """Pointing at the wrong realm means verifying tokens from a different trust domain."""
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(
            200, json=discovery_body(issuer="https://accounts.example.invalid/realms/other")
        )
    )

    cache = await build_cache(settings)
    with pytest.raises(JwksUnavailable):
        await cache.get_key("any-kid")


@respx.mock
async def test_a_discovery_document_without_a_jwks_uri_is_refused(settings: Settings) -> None:
    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json={"issuer": DEFAULT_ISSUER}))

    cache = await build_cache(settings)
    with pytest.raises(JwksUnavailable):
        await cache.get_key("any-kid")


@respx.mock
async def test_an_empty_key_set_is_refused(settings: Settings) -> None:
    """Accepting an empty JWKS would cache "no keys exist" and reject every token until the TTL."""
    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=discovery_body()))
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": []}))

    cache = await build_cache(settings)
    with pytest.raises(JwksUnavailable):
        await cache.get_key("any-kid")


@respx.mock
async def test_an_unreachable_provider_raises_unavailable_not_not_found(
    settings: Settings,
) -> None:
    """The distinction the caller turns into 503 rather than 401."""
    respx.get(DISCOVERY_URL).mock(side_effect=httpx.ConnectError("refused"))

    cache = await build_cache(settings)
    with pytest.raises(JwksUnavailable):
        await cache.get_key("any-kid")


@respx.mock
async def test_a_five_hundred_from_the_jwks_endpoint_is_unavailable(
    settings: Settings,
) -> None:
    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=discovery_body()))
    respx.get(JWKS_URL).mock(return_value=httpx.Response(500))

    cache = await build_cache(settings)
    with pytest.raises(JwksUnavailable):
        await cache.get_key("any-kid")


@respx.mock
async def test_warming_up_never_raises(settings: Settings) -> None:
    """Startup must not depend on the identity provider being up.

    Readiness already reports it, and the cache fills itself on the first request that needs it.
    Raising here would turn a brief Keycloak restart into a crash loop.
    """
    respx.get(DISCOVERY_URL).mock(side_effect=httpx.ConnectError("refused"))

    cache = await build_cache(settings)
    await cache.warm()


@respx.mock
async def test_concurrent_first_lookups_fetch_once(key: SigningKeyPair, settings: Settings) -> None:
    """A cold start serves a burst of requests; they must not each fetch the key set."""
    import asyncio

    respx.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=discovery_body()))
    jwks = respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_body(key)))

    cache = await build_cache(settings)
    await asyncio.gather(*(cache.get_key(key.kid) for _ in range(20)))

    assert jwks.call_count == 1
