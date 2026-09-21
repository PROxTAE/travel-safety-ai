from app.settings import Settings


def test_database_url_rendering_keeps_password_for_driver_without_logging_it() -> None:
    settings = Settings(
        POSTGRES_HOST="database",
        POSTGRES_DB="smart_travel",
        POSTGRES_USER="risk_service",
        POSTGRES_PASSWORD="local-test-password",  # noqa: S106
    )
    rendered = settings.sqlalchemy_url_string()
    assert "local-test-password" in rendered
    assert "***" not in rendered
