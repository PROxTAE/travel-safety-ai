# ruff: noqa: S106 -- deterministic non-production credential used only by auth tests

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth import require_internal_auth
from app.context import RequestContextMiddleware
from app.errors import install_error_handlers
from app.settings import Settings

VALID_HEADERS = {
    "Authorization": "Bearer unit-test-service-token",
    "X-Request-ID": "40000000-0000-4000-8000-000000000001",
    "X-Correlation-ID": "40000000-0000-4000-8000-000000000002",
    "X-Contract-Version": "1",
    "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
}


def _app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/internal", dependencies=[Depends(require_internal_auth)])
    async def internal() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/forbidden")
    async def forbidden() -> None:
        raise HTTPException(status_code=403, detail="Forbidden")

    return app


def test_internal_api_rejects_missing_token() -> None:
    settings = Settings(INTERNAL_SERVICE_TOKEN="unit-test-service-token")
    with TestClient(_app(settings)) as client:
        response = client.get("/internal")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_internal_api_rejects_missing_contract_headers() -> None:
    settings = Settings(INTERNAL_SERVICE_TOKEN="unit-test-service-token")
    with TestClient(_app(settings)) as client:
        response = client.get(
            "/internal", headers={"Authorization": "Bearer unit-test-service-token"}
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_internal_api_accepts_constant_time_token_and_headers() -> None:
    settings = Settings(INTERNAL_SERVICE_TOKEN="unit-test-service-token")
    with TestClient(_app(settings)) as client:
        response = client.get("/internal", headers=VALID_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_fastapi_http_exception_uses_standard_error_envelope() -> None:
    settings = Settings(INTERNAL_SERVICE_TOKEN="unit-test-service-token")
    with TestClient(_app(settings)) as client:
        response = client.get("/forbidden")

    assert response.status_code == 403
    assert response.headers["X-Error-Code"] == "FORBIDDEN"
    assert response.json()["error"]["code"] == "FORBIDDEN"
