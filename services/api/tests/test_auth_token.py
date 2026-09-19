"""Token verification.

The negative cases from the module plan's test matrix — expired, wrong issuer, wrong audience,
unknown kid — plus the forgery attempts that matter more than any of them: `alg: none` and the
HMAC substitution, where a token is signed with the provider's *public* key because that key is
published in the JWKS.

Every rejection must look identical from outside. A caller that can tell "expired" from "wrong
audience" can map the configuration by sending tokens and reading the differences.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest

from app.auth.jwks import JwksUnavailable
from app.auth.token import verify_access_token
from app.errors.exceptions import AuthenticationRequired, DependencyUnavailable
from app.settings import Settings
from tests.keys import DEFAULT_AUDIENCE, DEFAULT_ISSUER, SigningKeyPair, StubJwks


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture(scope="module")
def other_key() -> SigningKeyPair:
    """A key the provider does not publish — a forger's own."""
    return SigningKeyPair.generate(kid="attacker-key")


@pytest.fixture
def jwks(key: SigningKeyPair) -> StubJwks:
    return StubJwks.containing(key)


async def verify(token: str, settings: Settings, jwks: Any) -> Any:
    return await verify_access_token(token, settings=settings, jwks=jwks)


# --- the happy path ---------------------------------------------------------------------------


async def test_a_valid_token_is_accepted(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    claims = await verify(key.sign(), settings, jwks)

    assert claims.subject == "11111111-2222-3333-4444-555555555555"
    assert "travel" in claims.scopes
    assert "traveller" in claims.roles


async def test_scope_is_split_on_spaces_not_commas(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """`scope` is space-delimited in OAuth 2; treating it as one value would deny everything."""
    claims = await verify(key.sign({"scope": "openid travel"}), settings, jwks)

    assert claims.scopes == frozenset({"openid", "travel"})


async def test_roles_come_from_realm_access(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    claims = await verify(key.sign({"realm_access": {"roles": ["support"]}}), settings, jwks)

    assert claims.roles == frozenset({"support"})


async def test_a_token_without_roles_is_still_valid(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """Authentication and authorisation are separate; a role-less token is still signed in."""
    claims = await verify(key.sign({"realm_access": None}), settings, jwks)

    assert claims.roles == frozenset()


# --- the test matrix --------------------------------------------------------------------------


async def test_an_expired_token_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    now = int(time.time())
    expired = key.sign({"iat": now - 3600, "nbf": now - 3600, "exp": now - 1800})

    with pytest.raises(AuthenticationRequired):
        await verify(expired, settings, jwks)


async def test_a_token_from_the_future_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    now = int(time.time())
    premature = key.sign({"iat": now + 3600, "nbf": now + 3600, "exp": now + 7200})

    with pytest.raises(AuthenticationRequired):
        await verify(premature, settings, jwks)


async def test_clock_skew_within_the_leeway_is_tolerated(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """Two machines are never perfectly in step; a few seconds must not log everyone out."""
    now = int(time.time())
    just_expired = key.sign({"iat": now - 300, "nbf": now - 300, "exp": now - 5})

    claims = await verify(just_expired, settings, jwks)

    assert claims.subject


async def test_a_token_from_another_issuer_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """A token from a different realm is signed correctly and means nothing here."""
    foreign = key.sign({"iss": "https://accounts.example.invalid/realms/other"})

    with pytest.raises(AuthenticationRequired):
        await verify(foreign, settings, jwks)


async def test_a_trailing_slash_on_the_issuer_does_not_change_the_comparison(
    key: SigningKeyPair, jwks: StubJwks
) -> None:
    """The issuer is compared byte-for-byte, so the settings strip the slash, not the check."""
    from tests.conftest import build_settings

    settings = build_settings(OIDC_ISSUER=DEFAULT_ISSUER + "/")
    claims = await verify(key.sign(), settings, jwks)

    assert claims.subject


async def test_a_token_for_another_audience_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """The realm issues tokens for several clients. One meant for another service is not ours."""
    other_audience = key.sign({"aud": "some-other-service"})

    with pytest.raises(AuthenticationRequired):
        await verify(other_audience, settings, jwks)


async def test_a_token_with_our_audience_among_several_is_accepted(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """`aud` is legitimately a list when a token is meant for more than one service."""
    claims = await verify(key.sign({"aud": ["account", DEFAULT_AUDIENCE]}), settings, jwks)

    assert claims.subject


async def test_a_token_with_no_audience_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    with pytest.raises(AuthenticationRequired):
        await verify(key.sign({"aud": None}), settings, jwks)


async def test_a_token_signed_by_an_unpublished_key_is_rejected(
    other_key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """The forger's own key: correct shape, correct claims, wrong signer."""
    with pytest.raises(AuthenticationRequired):
        await verify(other_key.sign(), settings, jwks)


async def test_an_unknown_kid_is_looked_up_once_then_rejected(
    other_key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    with pytest.raises(AuthenticationRequired):
        await verify(other_key.sign(), settings, jwks)

    assert jwks.lookups == ["attacker-key"]


async def test_a_token_without_a_kid_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """Without a kid the key cannot be matched without trying them all, which hides a forgery."""
    token = jwt.encode(
        {"iss": DEFAULT_ISSUER, "aud": DEFAULT_AUDIENCE, "sub": "x", "exp": int(time.time()) + 300},
        key.private_key,
        algorithm="RS256",
    )

    with pytest.raises(AuthenticationRequired):
        await verify(token, settings, jwks)


async def test_a_token_missing_the_subject_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """The subject is the only thing that identifies the user; without it there is nobody to be."""
    with pytest.raises(AuthenticationRequired):
        await verify(key.sign({"sub": None}), settings, jwks)


async def test_garbage_is_rejected_without_raising_something_unexpected(
    jwks: StubJwks, settings: Settings
) -> None:
    for junk in ("", "not-a-token", "a.b.c", "Bearer x"):
        with pytest.raises(AuthenticationRequired):
            await verify(junk, settings, jwks)


# --- forgery ----------------------------------------------------------------------------------


async def test_an_unsigned_token_is_rejected(jwks: StubJwks, settings: Settings) -> None:
    """`alg: none` needs no key at all. Accepting it means accepting anything."""
    token = jwt.encode(
        {
            "iss": DEFAULT_ISSUER,
            "aud": DEFAULT_AUDIENCE,
            "sub": "attacker",
            "exp": int(time.time()) + 300,
        },
        key=None,  # type: ignore[arg-type]
        algorithm="none",
        headers={"kid": "test-key-1"},
    )

    with pytest.raises(AuthenticationRequired):
        await verify(token, settings, jwks)


def forge_hmac_token(public_pem: bytes, kid: str, claims: dict[str, Any]) -> str:
    """Hand-build an HS256 token using the provider's public key as the shared secret.

    Built by hand because PyJWT refuses to *encode* this — it recognises a PEM public key and
    raises. An attacker has no such guardrail, so the verifier has to be the thing that says no.
    """
    import base64
    import hashlib
    import hmac
    import json as json_module

    def segment(data: dict[str, Any]) -> bytes:
        raw = json_module.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    signing_input = segment({"alg": "HS256", "typ": "JWT", "kid": kid}) + b"." + segment(claims)
    signature = hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


def public_pem_of(key: SigningKeyPair) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


async def test_a_token_signed_with_the_public_key_as_an_hmac_secret_is_rejected(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """The classic algorithm-confusion attack.

    The provider's public key is published in the JWKS, so anyone can read it. A verifier that
    honoured `alg: HS256` would use that public key as a shared secret, and the attacker could mint
    tokens at will.
    """
    forged = forge_hmac_token(
        public_pem_of(key),
        key.kid,
        {
            "iss": DEFAULT_ISSUER,
            "aud": DEFAULT_AUDIENCE,
            "sub": "attacker",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
    )

    with pytest.raises(AuthenticationRequired):
        await verify(forged, settings, jwks)


async def test_the_algorithm_is_checked_before_a_key_is_fetched(
    key: SigningKeyPair, jwks: StubJwks, settings: Settings
) -> None:
    """Order matters: a disallowed algorithm must not even cause a JWKS lookup."""
    forged = forge_hmac_token(
        public_pem_of(key),
        key.kid,
        {"iss": DEFAULT_ISSUER, "aud": DEFAULT_AUDIENCE, "sub": "x", "exp": int(time.time()) + 300},
    )

    with pytest.raises(AuthenticationRequired):
        await verify(forged, settings, jwks)

    assert jwks.lookups == [], "a disallowed algorithm caused a key lookup"


def test_symmetric_algorithms_cannot_be_configured() -> None:
    """The allowlist is configurable, but not into an unsafe state."""
    from pydantic import ValidationError

    from tests.conftest import build_settings

    for unsafe in ("none", "HS256", "RS256,HS256", ""):
        with pytest.raises(ValidationError):
            build_settings(API_OIDC_ALLOWED_ALGORITHMS=unsafe)


# --- the provider being down is not the user's fault -------------------------------------------


async def test_an_unreachable_provider_is_reported_as_a_dependency_failure(
    key: SigningKeyPair, settings: Settings
) -> None:
    """503, not 401.

    Telling someone their session expired while Keycloak is down sends them to a login page that
    cannot work, and they retry until someone looks at a dashboard.
    """

    class DownJwks:
        async def get_key(self, kid: str) -> dict[str, Any]:
            raise JwksUnavailable

    with pytest.raises(DependencyUnavailable):
        await verify(key.sign(), settings, DownJwks())
