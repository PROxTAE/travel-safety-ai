"""Access token verification.

One function, `verify_access_token`, and everything it checks is required by §"User identity" of
the module plan: issuer, audience, signature, expiry, not-before.

The order matters. The algorithm is checked against an allowlist taken from the *header*, before
any key is loaded, because that is the step an attacker attacks: a token claiming `alg: none`
needs no key, and one claiming `HS256` would be verified with the provider's public key as a
shared secret — and that key is published in the JWKS.

Failures are deliberately indistinguishable to the caller. Every invalid token produces the same
401 with the same message, so the response cannot be used to work out which check failed. The
reason is recorded in the log instead, where it is useful and not attacker-visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import jwt
from jwt import PyJWK

from app.auth.jwks import JwksCache, JwksUnavailable, SigningKeyNotFound
from app.errors.exceptions import AuthenticationRequired, DependencyUnavailable
from app.observability.logging import get_logger

if TYPE_CHECKING:
    from app.settings import Settings

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """The claims this service acts on. Everything else in the token is ignored."""

    subject: str
    scopes: frozenset[str]
    roles: frozenset[str]
    expires_at: datetime
    issued_at: datetime | None
    token_id: str | None
    authorized_party: str | None
    locale: str | None
    display_name: str | None


def _parse_scopes(raw: object) -> frozenset[str]:
    """`scope` is a space-delimited string in OAuth 2, not a list."""
    if isinstance(raw, str):
        return frozenset(part for part in raw.split(" ") if part)
    if isinstance(raw, list):
        return frozenset(str(part) for part in raw if part)
    return frozenset()


def _parse_roles(payload: dict[str, Any]) -> frozenset[str]:
    """Realm roles, as Keycloak nests them under `realm_access.roles`."""
    realm_access = payload.get("realm_access")
    if isinstance(realm_access, dict):
        roles = realm_access.get("roles")
        if isinstance(roles, list):
            return frozenset(str(role) for role in roles if role)
    return frozenset()


async def verify_access_token(token: str, *, settings: Settings, jwks: JwksCache) -> TokenClaims:
    """Verify a bearer token and return the claims worth acting on.

    Raises `AuthenticationRequired` for anything wrong with the token, and
    `DependencyUnavailable` when the identity provider cannot be reached — telling a user their
    session expired while Keycloak is down would send them round a login loop that cannot succeed.
    """

    def reject(reason: str) -> AuthenticationRequired:
        # The reason goes to the log, never to the response: a caller that can tell "expired"
        # from "wrong audience" from "bad signature" can probe the configuration.
        logger.info("token_rejected", event_type="auth", reason=reason)
        return AuthenticationRequired(log_context={"auth_reason": reason})

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise reject("malformed_header") from None

    algorithm = header.get("alg")
    if algorithm not in settings.oidc_allowed_algorithms:
        raise reject(f"algorithm_not_allowed:{algorithm}")

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        # Every key in a rotating JWKS is identified by kid; a token without one cannot be
        # matched to a key without trying them all, which is a way to hide a forgery attempt.
        raise reject("missing_kid")

    try:
        jwk = await jwks.get_key(kid)
    except SigningKeyNotFound:
        raise reject("unknown_kid") from None
    except JwksUnavailable as exc:
        logger.warning("jwks_unavailable_during_verification", event_type="auth")
        raise DependencyUnavailable("oidc") from exc

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            key=PyJWK.from_dict(jwk).key,
            algorithms=list(settings.oidc_allowed_algorithms),
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            leeway=settings.oidc_leeway_seconds,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise reject("expired") from None
    except jwt.ImmatureSignatureError:
        raise reject("not_yet_valid") from None
    except jwt.InvalidIssuerError:
        raise reject("wrong_issuer") from None
    except jwt.InvalidAudienceError:
        raise reject("wrong_audience") from None
    except jwt.MissingRequiredClaimError as exc:
        raise reject(f"missing_claim:{exc.claim}") from None
    except jwt.InvalidSignatureError:
        raise reject("bad_signature") from None
    except jwt.PyJWTError as exc:
        raise reject(f"invalid_token:{type(exc).__name__}") from None

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise reject("missing_subject")

    return TokenClaims(
        subject=subject,
        scopes=_parse_scopes(payload.get("scope")),
        roles=_parse_roles(payload),
        expires_at=datetime.fromtimestamp(float(payload["exp"]), tz=UTC),
        issued_at=(
            datetime.fromtimestamp(float(payload["iat"]), tz=UTC)
            if payload.get("iat") is not None
            else None
        ),
        token_id=str(payload["jti"]) if payload.get("jti") else None,
        authorized_party=str(payload["azp"]) if payload.get("azp") else None,
        locale=str(payload["locale"]) if payload.get("locale") else None,
        # Held only long enough to answer the owner's own request; never persisted, never logged.
        display_name=(
            str(payload["name"])
            if payload.get("name")
            else (str(payload["preferred_username"]) if payload.get("preferred_username") else None)
        ),
    )
