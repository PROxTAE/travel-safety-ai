"""OIDC discovery and the JWKS cache.

Verifying a token needs the identity provider's public signing keys. Fetching them per request
would put an outbound HTTP call in front of every API call and take the service down whenever
Keycloak is briefly slow, so they are cached. Caching them forever would break every token the
moment the provider rotates its keys, which providers do on their own schedule.

The cache therefore does three things:

* **Serves from memory for a TTL.** The common path touches no network.
* **Refetches when a token carries a key id it has not seen**, because that is what a rotation
  looks like from here.
* **Rate-limits that refetch.** A token's `kid` is attacker-controlled: without a cooldown, a
  stream of tokens carrying random key ids turns one request into one outbound fetch against the
  identity provider, with this service as the amplifier.

Discovery is fetched the same way, and its `issuer` is checked against the configured one. If they
disagree, something is pointing at the wrong realm and no token is trusted.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from app.observability.logging import get_logger

if TYPE_CHECKING:
    from app.settings import Settings

logger = get_logger(__name__)


class JwksUnavailable(Exception):
    """The signing keys could not be retrieved.

    Distinct from "the token is invalid": this is our dependency failing, so the caller answers
    503 rather than 401. Telling a user their session expired when the identity provider is down
    would send them round a login loop that cannot succeed.
    """


class SigningKeyNotFound(Exception):
    """The token names a key id the provider does not publish, even after a refresh."""


@dataclass
class _CacheEntry:
    keys_by_kid: dict[str, dict[str, Any]]
    fetched_at: float


@dataclass
class JwksCache:
    """Caches the discovery document and the signing keys for one issuer."""

    settings: Settings
    client: httpx.AsyncClient

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _entry: _CacheEntry | None = field(default=None, repr=False)
    _jwks_uri: str | None = field(default=None, repr=False)
    #: Negative infinity, not zero: `time.monotonic()` can start near zero, and a zero here would
    #: make the cooldown look active for the first half-minute of the process's life.
    _last_unknown_kid_refresh: float = field(default=float("-inf"), repr=False)

    async def get_key(self, kid: str) -> dict[str, Any]:
        """The JWK for `kid`, refreshing at most once if it is not already cached."""
        entry = self._entry
        now = time.monotonic()
        cache_is_fresh = (
            entry is not None and now - entry.fetched_at < self.settings.oidc_jwks_ttl_seconds
        )

        if cache_is_fresh:
            assert entry is not None  # narrowed by cache_is_fresh
            key = entry.keys_by_kid.get(kid)
            if key is not None:
                return key

            # An unknown kid against a fresh cache is either a rotation we have not seen yet or a
            # forged token. Refetching tells the two apart, so the first one is always allowed —
            # otherwise a rotation would lock every user out until the TTL expired. The cooldown
            # applies to the *next* one, which bounds an attacker sending random key ids to one
            # outbound fetch per cooldown rather than one per request.
            if now - self._last_unknown_kid_refresh < self.settings.oidc_jwks_min_refresh_seconds:
                raise SigningKeyNotFound(kid)
            self._last_unknown_kid_refresh = now

        await self._refresh(seen=entry)

        entry = self._entry
        if entry is None or kid not in entry.keys_by_kid:
            raise SigningKeyNotFound(kid)
        return entry.keys_by_kid[kid]

    async def warm(self) -> None:
        """Populate the cache ahead of the first request. Failure is not fatal."""
        try:
            await self._refresh()
        except JwksUnavailable:
            # Startup must not depend on the identity provider being up: readiness already
            # reports it, and the cache fills itself on the first request that needs it.
            logger.warning("jwks_warm_failed", event_type="auth")

    async def _refresh(self, *, seen: _CacheEntry | None = None) -> None:
        """Refetch the key set.

        `seen` is the cache entry the caller had before it decided to refresh. If it has changed by
        the time the lock is acquired, someone else already did the work and this caller returns
        without a second fetch — which is what keeps a cold-start burst to one request.
        """
        async with self._lock:
            if self._entry is not None and self._entry is not seen:
                return

            jwks_uri = await self._resolve_jwks_uri()

            try:
                response = await self.client.get(
                    jwks_uri, timeout=self.settings.oidc_discovery_timeout_seconds
                )
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("jwks_fetch_failed", event_type="auth", reason=type(exc).__name__)
                raise JwksUnavailable from exc

            keys = {
                key["kid"]: key
                for key in document.get("keys", [])
                if isinstance(key, dict) and key.get("kid")
            }
            if not keys:
                raise JwksUnavailable("the JWKS document published no usable keys")

            self._entry = _CacheEntry(keys_by_kid=keys, fetched_at=time.monotonic())
            logger.info("jwks_refreshed", event_type="auth", key_count=len(keys))

    async def _resolve_jwks_uri(self) -> str:
        """Read `jwks_uri` from the discovery document, once per process.

        Taking it from discovery rather than hard-coding the provider's path means a Keycloak
        upgrade that moves the endpoint does not silently break authentication.
        """
        if self._jwks_uri is not None:
            return self._jwks_uri

        try:
            response = await self.client.get(
                self.settings.oidc_discovery_url,
                timeout=self.settings.oidc_discovery_timeout_seconds,
            )
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("oidc_discovery_failed", event_type="auth", reason=type(exc).__name__)
            raise JwksUnavailable from exc

        published_issuer = str(document.get("issuer", "")).rstrip("/")
        if published_issuer != self.settings.oidc_issuer:
            # Pointing at the wrong realm would mean verifying tokens against keys that belong to
            # a different trust domain. Refuse rather than guess.
            logger.error(
                "oidc_issuer_mismatch",
                event_type="auth",
                configured=self.settings.oidc_issuer,
                published=published_issuer,
            )
            raise JwksUnavailable("the discovery document reports a different issuer")

        jwks_uri = document.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise JwksUnavailable("the discovery document has no jwks_uri")

        self._jwks_uri = jwks_uri
        return jwks_uri
