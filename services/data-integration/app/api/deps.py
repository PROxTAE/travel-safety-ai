"""Internal bearer authentication."""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.settings import get_settings


def require_internal_auth(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    token = get_settings().internal_service_token
    if token is None:
        raise HTTPException(status_code=401, detail="internal authentication unavailable")
    if request.headers.get("cookie"):
        raise HTTPException(status_code=401, detail="browser credentials are not accepted")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing internal credential")
    presented = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(presented, token.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid internal credential")


InternalAuth = Annotated[None, Depends(require_internal_auth)]
