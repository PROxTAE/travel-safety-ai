"""Runtime configuration for the agent service (module 03).

Every budget and timeout named in IMPLEMENTATION_PLANS/03_TRAVEL_AI_AGENT_IMPLEMENTATION.md
("Budgets and stop conditions") lives here and nowhere else, so that a stop condition can be
changed by configuration and the value in force can be recorded with a run.

Two rules shape this file:

* **Fail closed.** A production process without a service credential does not start, and a
  process that has none in development rejects every request rather than accepting them all.
* **Nothing is invented.** The plan leaves the token and cost ceilings undefined (`...`). They
  default to unset, and the LLM cannot be switched on until an operator sets them, so no run can
  spend against a limit nobody chose.

Values marked "proposal" are not in the plan or the shared contract and need confirming with the
team (see docs/diagrams/agent-state.md, "คำถามที่ต้องตกลง").
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Tools on the MVP allowlist (plan, "Tool registry rules"). A run that reaches the end makes one
#: call to each, so a ceiling below this could never complete.
ALLOWLISTED_TOOL_COUNT = 5

#: Shortest service credential accepted in production. A proposal, not a contract value.
MIN_SERVICE_TOKEN_LENGTH = 16


class Settings(BaseSettings):
    """Environment-driven settings. Variable names are the upper-case form of the field names."""

    # `hide_input_in_errors` matters here: without it pydantic prints the rejected input in the
    # validation error, which for a bad INTERNAL_SERVICE_TOKEN means the secret itself reaches
    # the container log at start-up.
    model_config = SettingsConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    service_name: str = "agent"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    #: Sent as the major number in `X-Contract-Version`, reported in response `meta`.
    contract_version: str = "1.0.0"

    #: Shared secret module 02 presents as `Authorization: Bearer <token>`. Internal endpoints
    #: refuse every request while this is unset.
    internal_service_token: SecretStr | None = None

    #: Postgres connection string for the LangGraph checkpointer and `agent.runs`
    #: (app/checkpoints/postgres.py). Unset means the service still starts — `/health/ready`
    #: reports it — but every run fails to persist rather than being invented in memory. Whoever
    #: wires `compose.yaml`'s `agent:` service should set this the same way `decision-engine`
    #: sets `DECISION_DATABASE_URL`, assembled from the shared `POSTGRES_*` variables.
    database_url: str | None = None
    #: Redis connection string for `app/progress/publisher.py`. Unset disables progress
    #: publishing (`run.accepted`/`run.progress`/... are simply not sent) rather than failing the
    #: run — SSE delivery degrading is not, by itself, a reason to refuse a request.
    redis_url: str | None = None

    # -- Tool base URLs (app/tools/registry.py, "base URL จาก env allowlist; agent ห้ามรับ URL จาก
    # model/user") — the agent never accepts one of these from a request body or a model output.
    # Defaults are each service's own Docker Compose network name and the port its own Dockerfile
    # EXPOSEs; unset for the two with neither observed yet.
    external_data_base_url: str = "http://external-data:8002"
    data_integration_base_url: str = "http://data-integration:8003"
    risk_knowledge_base_url: str = "http://risk-knowledge:8004"
    decision_engine_base_url: str = "http://decision-engine:8005"
    recommendation_base_url: str | None = None

    # -- Budgets and stop conditions (values from the plan) ------------------------------------
    max_agent_steps: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=10, ge=1)
    agent_total_timeout_seconds: float = Field(default=45.0, gt=0)
    agent_tool_timeout_seconds: float = Field(default=12.0, gt=0)
    max_llm_calls: int = Field(default=2, ge=0)

    # -- Tool client policy (proposals) --------------------------------------------------------
    agent_tool_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    #: Attempts per tool call, first try included. 5 tools x 2 attempts fits `max_tool_calls`.
    agent_tool_max_attempts: int = Field(default=2, ge=1)
    #: How many times `validate_evidence` may send the run back to `build_evidence`.
    evidence_retry_max: int = Field(default=1, ge=0)

    # -- LLM (used only for ambiguous intent, plan Phase 2) ------------------------------------
    llm_enabled: bool = False
    #: The plan leaves these three as `...`; unset means "no ceiling chosen yet".
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    max_estimated_cost_usd: float | None = Field(default=None, gt=0)
    #: Provider credential for app/intent/llm_classifier.py. Unset means the LLM path can never
    #: run even if LLM_ENABLED is true — see OpenAIIntentClassifier's own fail-closed check.
    openai_api_key: SecretStr | None = None
    openai_intent_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = Field(default=10.0, gt=0)

    @model_validator(mode="after")
    def _validate_consistency(self) -> Self:
        problems: list[str] = []

        if self.agent_tool_timeout_seconds > self.agent_total_timeout_seconds:
            problems.append(
                "AGENT_TOOL_TIMEOUT_SECONDS must not exceed AGENT_TOTAL_TIMEOUT_SECONDS"
            )
        if self.agent_tool_connect_timeout_seconds > self.agent_tool_timeout_seconds:
            problems.append(
                "AGENT_TOOL_CONNECT_TIMEOUT_SECONDS must not exceed AGENT_TOOL_TIMEOUT_SECONDS"
            )
        if self.max_tool_calls < ALLOWLISTED_TOOL_COUNT:
            problems.append(
                f"MAX_TOOL_CALLS must be at least {ALLOWLISTED_TOOL_COUNT}, "
                "one call per allowlisted tool"
            )

        if self.llm_enabled:
            if self.max_llm_calls < 1:
                problems.append("LLM_ENABLED needs MAX_LLM_CALLS of at least 1")
            for name, value in (
                ("MAX_INPUT_TOKENS", self.max_input_tokens),
                ("MAX_OUTPUT_TOKENS", self.max_output_tokens),
                ("MAX_ESTIMATED_COST_USD", self.max_estimated_cost_usd),
            ):
                if value is None:
                    problems.append(f"LLM_ENABLED needs {name} to be set")

        if self.app_env == "production":
            token = self.internal_service_token
            if token is None or len(token.get_secret_value()) < MIN_SERVICE_TOKEN_LENGTH:
                problems.append(
                    "INTERNAL_SERVICE_TOKEN must be set to at least "
                    f"{MIN_SERVICE_TOKEN_LENGTH} characters in production"
                )

        if problems:
            # Names only, never values: a rejected token must not end up in the error text.
            raise ValueError("; ".join(problems))
        return self

    def initial_budget(self) -> dict[str, int]:
        """The counters a new run starts with, in the shape of `ControlSection.remaining_budget`."""
        return {
            "steps": self.max_agent_steps,
            "tool_calls": self.max_tool_calls,
            "llm_calls": self.max_llm_calls if self.llm_enabled else 0,
        }


@lru_cache
def get_settings() -> Settings:
    """Read settings once per process. Tests build `Settings(...)` directly instead."""
    return Settings()
