"""FastAPI dependencies for authentication and authorisation.

Authentication is a dependency rather than a middleware. A middleware would have to run for
`/health/*` and `/metrics` too and then decide to skip them — a list that grows stale and fails
open. A dependency is declared per router, so a route is unauthenticated only when someone wrote
that down, and the OpenAPI document reflects it.

The chain for a protected route is:

1. `get_principal` — verify the token, resolve the subject to a local profile, refuse a disabled
   or deleted account, and bind a non-reversible caller handle to the log context.
2. `require_scopes(...)` / `require_roles(...)` — authorisation, which is a separate answer from
   authentication: 401 means "we do not know who you are", 403 means "we do, and no".
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.auth.token import verify_access_token
from app.db.engine import session_scope
from app.errors.exceptions import AuthenticationRequired, Forbidden
from app.observability.logging import get_logger
from app.observability.metrics import auth_failures_total
from app.repositories import user_profiles
from app.settings import Settings

logger = get_logger(__name__)

#: `auto_error=False` so a missing header reaches our own handler and produces the contract error
#: envelope, rather than Starlette's bare `{"detail": "Not authenticated"}`.
_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request, committed on success and rolled back on any exception."""
    async with session_scope(request.app.state.session_factory) as session:
        yield session


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> Principal:
    """Verify the bearer token and resolve it to a local user."""
    if credentials is None or not credentials.credentials:
        auth_failures_total.labels(reason="missing_token").inc()
        raise AuthenticationRequired

    if credentials.scheme.lower() != "bearer":
        auth_failures_total.labels(reason="wrong_scheme").inc()
        raise AuthenticationRequired

    try:
        claims = await verify_access_token(
            credentials.credentials, settings=settings, jwks=request.app.state.jwks
        )
    except AuthenticationRequired:
        auth_failures_total.labels(reason="invalid_token").inc()
        raise

    profile = await user_profiles.get_or_create_by_subject(
        session,
        subject_id=claims.subject,
        default_locale=claims.locale or "en-US",
        default_timezone="UTC",
    )

    # A JWT cannot be withdrawn once issued. Without these two checks, disabling or deleting an
    # account would leave it working until the token expired.
    if profile.disabled_at is not None:
        auth_failures_total.labels(reason="account_disabled").inc()
        logger.warning("account_disabled", event_type="auth", user_id=str(profile.id))
        raise AuthenticationRequired("This account is not active.")
    if profile.deleted_at is not None:
        auth_failures_total.labels(reason="account_deleted").inc()
        raise AuthenticationRequired("This account is not active.")

    principal = Principal(
        user_id=profile.id,
        subject=claims.subject,
        scopes=claims.scopes,
        roles=claims.roles,
        expires_at=claims.expires_at,
        token_id=claims.token_id,
        display_name=claims.display_name,
    )

    # Bound to the log context rather than logged once, so every line for this request carries it.
    # The digest, not the subject: enough to correlate a user's requests during an investigation
    # without writing an identity-provider id into log storage.
    structlog.contextvars.bind_contextvars(
        user_id=str(principal.user_id), subject_digest=principal.subject_digest
    )
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


def require_scopes(*required: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Require every listed OAuth scope.

    Separate from authentication on purpose: a valid token with the wrong scope is 403, not 401.
    Answering 401 would tell the client to refresh, which returns the same token and loops.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        missing = sorted(scope for scope in required if not principal.has_scope(scope))
        if missing:
            auth_failures_total.labels(reason="missing_scope").inc()
            logger.info(
                "authorization_denied",
                event_type="auth",
                reason="missing_scope",
                missing_scopes=missing,
            )
            raise Forbidden("This application is not authorised for that action.")
        return principal

    return dependency


def require_roles(*required: str) -> Callable[[Principal], Awaitable[Principal]]:
    """Require every listed realm role."""

    async def dependency(principal: CurrentPrincipal) -> Principal:
        missing = sorted(role for role in required if not principal.has_role(role))
        if missing:
            auth_failures_total.labels(reason="missing_role").inc()
            logger.info(
                "authorization_denied",
                event_type="auth",
                reason="missing_role",
                missing_roles=missing,
            )
            raise Forbidden
        return principal

    return dependency
