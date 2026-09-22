"""Tests for the agent's runtime configuration (app/settings.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import ALLOWLISTED_TOOL_COUNT, Settings, get_settings

VALID_TOKEN = "x" * 16


def _settings(**overrides: object) -> Settings:
    """Build settings from arguments only, ignoring the developer's real environment."""
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_match_the_plan() -> None:
    settings = _settings()
    assert settings.max_agent_steps == 12
    assert settings.max_tool_calls == 10
    assert settings.agent_total_timeout_seconds == 45
    assert settings.agent_tool_timeout_seconds == 12
    assert settings.max_llm_calls == 2


def test_token_and_cost_ceilings_are_unset_by_default() -> None:
    settings = _settings()
    assert settings.max_input_tokens is None
    assert settings.max_output_tokens is None
    assert settings.max_estimated_cost_usd is None
    assert settings.llm_enabled is False


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_AGENT_STEPS", "8")
    monkeypatch.setenv("AGENT_TOTAL_TIMEOUT_SECONDS", "30")
    settings = Settings()
    assert settings.max_agent_steps == 8
    assert settings.agent_total_timeout_seconds == 30


def test_unrelated_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "shared-compose-variable")
    assert Settings().service_name == "agent"


def test_tool_timeout_cannot_exceed_total_timeout() -> None:
    with pytest.raises(ValidationError, match="AGENT_TOOL_TIMEOUT_SECONDS"):
        _settings(agent_tool_timeout_seconds=60, agent_total_timeout_seconds=45)


def test_connect_timeout_cannot_exceed_tool_timeout() -> None:
    with pytest.raises(ValidationError, match="CONNECT_TIMEOUT"):
        _settings(agent_tool_connect_timeout_seconds=20, agent_tool_timeout_seconds=12)


def test_tool_call_ceiling_must_cover_every_allowlisted_tool() -> None:
    with pytest.raises(ValidationError, match="MAX_TOOL_CALLS"):
        _settings(max_tool_calls=ALLOWLISTED_TOOL_COUNT - 1)


@pytest.mark.parametrize(
    "field",
    ["max_agent_steps", "max_tool_calls", "agent_total_timeout_seconds"],
)
def test_budgets_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: 0})


def test_llm_cannot_be_enabled_without_ceilings() -> None:
    with pytest.raises(ValidationError, match="MAX_INPUT_TOKENS"):
        _settings(llm_enabled=True)


def test_llm_can_be_enabled_once_ceilings_are_set() -> None:
    settings = _settings(
        llm_enabled=True,
        max_input_tokens=4000,
        max_output_tokens=500,
        max_estimated_cost_usd=0.05,
    )
    assert settings.initial_budget()["llm_calls"] == 2


def test_llm_needs_at_least_one_call_allowed() -> None:
    with pytest.raises(ValidationError, match="MAX_LLM_CALLS"):
        _settings(
            llm_enabled=True,
            max_llm_calls=0,
            max_input_tokens=4000,
            max_output_tokens=500,
            max_estimated_cost_usd=0.05,
        )


def test_production_requires_a_service_token() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_SERVICE_TOKEN"):
        _settings(app_env="production")


def test_production_rejects_a_short_token() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_SERVICE_TOKEN"):
        _settings(app_env="production", internal_service_token="short")


def test_production_accepts_a_long_enough_token() -> None:
    settings = _settings(app_env="production", internal_service_token=VALID_TOKEN)
    assert settings.internal_service_token is not None


def test_development_may_start_without_a_token() -> None:
    assert _settings(app_env="development").internal_service_token is None


def test_rejected_token_value_never_appears_in_the_error() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(app_env="production", internal_service_token="secret-1")
    assert "secret-1" not in str(excinfo.value)


def test_token_is_masked_in_repr_and_str() -> None:
    settings = _settings(internal_service_token=VALID_TOKEN)
    assert VALID_TOKEN not in repr(settings)
    assert VALID_TOKEN not in str(settings)


def test_settings_are_immutable() -> None:
    settings = _settings()
    with pytest.raises(ValidationError):
        settings.max_agent_steps = 99


def test_initial_budget_matches_settings() -> None:
    settings = _settings(max_agent_steps=7, max_tool_calls=9)
    assert settings.initial_budget() == {"steps": 7, "tool_calls": 9, "llm_calls": 0}


def test_get_settings_reads_the_environment_once(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_AGENT_STEPS", "9")
    try:
        first = get_settings()
        monkeypatch.setenv("MAX_AGENT_STEPS", "3")
        assert get_settings() is first
        assert first.max_agent_steps == 9
    finally:
        get_settings.cache_clear()
