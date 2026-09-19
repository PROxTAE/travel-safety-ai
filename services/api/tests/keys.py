"""Signing keys for the token tests.

Real RSA keys, generated in-process and thrown away. Not a fixture file: a committed private key is
a committed private key even when it is "only for tests", and it will eventually be copied
somewhere that matters.

The verifier under test is the real one. Only the source of the public keys is replaced, which is
the same substitution a JWKS HTTP mock would make.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

DEFAULT_ISSUER = "http://keycloak.invalid:8080/realms/smart-travel"
DEFAULT_AUDIENCE = "smart-travel-api"


@dataclass
class SigningKeyPair:
    """One RSA key pair with the `kid` it is published under."""

    kid: str
    private_key: rsa.RSAPrivateKey

    @classmethod
    def generate(cls, kid: str = "test-key-1") -> SigningKeyPair:
        return cls(
            kid=kid,
            # 2048 rather than 4096: the tests generate keys on every run and this is the size a
            # real provider uses anyway.
            private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        )

    @property
    def public_jwk(self) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(self.private_key.public_key()))
        jwk["kid"] = self.kid
        jwk["alg"] = "RS256"
        jwk["use"] = "sig"
        return jwk

    def sign(
        self,
        claims: dict[str, Any] | None = None,
        *,
        algorithm: str = "RS256",
        headers: dict[str, Any] | None = None,
    ) -> str:
        payload = {**default_claims(), **(claims or {})}
        # Drop anything set to None, so a test can remove a required claim by passing None.
        payload = {key: value for key, value in payload.items() if value is not None}
        return jwt.encode(
            payload,
            self.private_key,
            algorithm=algorithm,
            headers={"kid": self.kid, **(headers or {})},
        )


def default_claims(
    *, subject: str = "11111111-2222-3333-4444-555555555555", lifetime_seconds: int = 300
) -> dict[str, Any]:
    """A token that should pass every check, so a test only states what it changes."""
    now = int(time.time())
    return {
        "iss": DEFAULT_ISSUER,
        "aud": DEFAULT_AUDIENCE,
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime_seconds,
        "jti": "00000000-0000-4000-8000-000000000001",
        "azp": "smart-travel-test-cli",
        "scope": "openid travel profile",
        "realm_access": {"roles": ["traveller", "offline_access"]},
        "preferred_username": "test-user",
    }


@dataclass
class StubJwks:
    """Stands in for the JWKS cache, counting how often it is asked to refresh.

    The cache's own behaviour is tested separately in `test_auth_jwks.py`; here it is just the
    key source, so the token verifier is what is under test.
    """

    keys: dict[str, dict[str, Any]]
    lookups: list[str] = field(default_factory=list)

    @classmethod
    def containing(cls, *pairs: SigningKeyPair) -> StubJwks:
        return cls(keys={pair.kid: pair.public_jwk for pair in pairs})

    async def get_key(self, kid: str) -> dict[str, Any]:
        from app.auth.jwks import SigningKeyNotFound

        self.lookups.append(kid)
        try:
            return self.keys[kid]
        except KeyError:
            raise SigningKeyNotFound(kid) from None
