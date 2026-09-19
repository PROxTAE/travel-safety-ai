"""Configuration validation.

The point of these tests is that a misconfiguration stops the process at startup instead of
becoming a 500 on a user's first request, and that production cannot be started with settings that
would be unsafe there.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings
from tests.conftest import TEST_ENV


def build(**overrides: str) -> Settings:
    values = {key.lower(): value for key, value in TEST_ENV.items()}
    values.update({key.lower(): value for key, value in overrides.items()})
    return Settings(**values)  # type: ignore[arg-type]


def test_missing_database_password_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail at startup, not on the first user request an hour later.

    The environment is cleared explicitly: inside the container POSTGRES_PASSWORD is genuinely set,
    and a test that only passed because the host happened not to have it would be asserting
    something about the test machine rather than about the code.
    """
    for key in ("POSTGRES_PASSWORD", "POSTGRES_USER"):
        monkeypatch.delenv(key, raising=False)

    values = {key.lower(): value for key, value in TEST_ENV.items()}
    del values["postgres_password"]

    with pytest.raises(ValidationError):
        Settings(**values)  # type: ignore[arg-type]


def test_password_is_not_rendered_in_the_repr() -> None:
    """Settings end up in crash dumps and debugger output."""
    settings = build()

    assert "not-a-real-password" not in repr(settings)
    assert "not-a-real-password" not in str(settings)


def test_database_url_carries_the_password_but_the_settings_object_does_not() -> None:
    settings = build()

    assert "not-a-real-password" in settings.database_url
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_alembic_uses_a_synchronous_driver() -> None:
    """Alembic does not run in the event loop, and asyncpg cannot serve it."""
    assert build().sync_database_url.startswith("postgresql+psycopg://")


def test_wildcard_cors_origin_is_rejected() -> None:
    """This API answers with credentials; a wildcard would let any site read a user's trips."""
    with pytest.raises(ValidationError, match="listed exactly"):
        build(API_CORS_ALLOWED_ORIGINS="*")


def test_cors_origins_accept_a_comma_separated_string() -> None:
    settings = build(API_CORS_ALLOWED_ORIGINS="http://localhost:3000, http://localhost:3001")

    assert settings.cors_allowed_origins == ("http://localhost:3000", "http://localhost:3001")


def test_issuer_trailing_slash_is_stripped() -> None:
    """The issuer is compared byte-for-byte with the `iss` claim."""
    settings = build(OIDC_ISSUER="https://id.example.test/realms/smart-travel/")

    assert settings.oidc_issuer == "https://id.example.test/realms/smart-travel"
    assert settings.oidc_discovery_url.endswith("/.well-known/openid-configuration")


def test_production_rejects_plain_http_cors_origins() -> None:
    with pytest.raises(ValidationError, match="Plain-HTTP CORS origins"):
        build(
            APP_ENV="production",
            OIDC_ISSUER="https://id.example.test/realms/smart-travel",
            API_CORS_ALLOWED_ORIGINS="http://app.example.test",
        )


def test_production_rejects_a_plain_http_issuer() -> None:
    with pytest.raises(ValidationError, match="must be https in production"):
        build(
            APP_ENV="production",
            API_CORS_ALLOWED_ORIGINS="https://app.example.test",
            OIDC_ISSUER="http://keycloak:8080/realms/smart-travel",
        )


def test_development_allows_plain_http() -> None:
    """Local development has no certificates, and requiring them would push people to disable the
    check entirely."""
    settings = build(APP_ENV="development")

    assert settings.app_env == "development"


def test_redis_namespace_follows_the_key_convention() -> None:
    """`sta:{env}:` — a shared convention only works if every service derives it the same way."""
    assert build(APP_ENV="test").redis_namespace == "sta:test"


def test_trusted_proxy_hops_defaults_to_zero() -> None:
    """Trusting a forwarding header by default lets any client choose its own rate-limit bucket."""
    assert build().trusted_proxy_hops == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("API_MAX_REQUEST_BODY_BYTES", "0"),
        ("API_READINESS_TIMEOUT_SECONDS", "0"),
        ("API_DB_POOL_SIZE", "0"),
        ("POSTGRES_PORT", "70000"),
    ],
)
def test_out_of_range_values_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        build(**{field: value})
