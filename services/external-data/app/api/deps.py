"""Internal service authentication and per-request context.

Contract § 5: internal endpoints use service authentication and must not accept a
browser token. Phase 1 implements that as a shared bearer secret in
`INTERNAL_SERVICE_TOKEN`, compared in constant time.

This is a *proposed* mechanism - the contract names the requirement but not the
scheme, and the callers are modules 03 and 05. It is recorded in the handoff for
cross-module review rather than treated as settled.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from app.domain.errors import ApiErrorCode
from app.settings import Settings, get_settings


class InternalAuthError(HTTPException):
    def __init__(self, message: str) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)
        self.api_code = ApiErrorCode.AUTHENTICATION_REQUIRED


def require_internal_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Fail closed.

    An unset token is a misconfiguration, not a development convenience. If we
    allowed open access when the secret is missing, the safest-looking
    deployment - one that forgot to set it - would be the least protected.
    """
    settings: Settings = get_settings()
    configured = settings.internal_service_token

    if configured is None:
        raise InternalAuthError("internal service authentication is not configured")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise InternalAuthError("missing internal service credential")

    presented = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(presented, configured.get_secret_value()):
        raise InternalAuthError("invalid internal service credential")

    # A browser-issued OIDC token must never authenticate an internal route.
    if request.headers.get("cookie"):
        raise InternalAuthError("browser credentials are not accepted here")


InternalAuth = Annotated[None, Depends(require_internal_auth)]
