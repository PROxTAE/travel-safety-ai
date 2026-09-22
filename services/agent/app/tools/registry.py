"""Tool registry — `03_TRAVEL_AI_AGENT_IMPLEMENTATION.md` "Tool registry rules".

Every one of the plan's 5 allowlisted MVP tools is declared here, whether or not it has a working
client yet, because the rule is "every tool must declare its metadata", not "every tool must
work". `available=False` on the last three (see each entry's `unavailable_reason`) is the honest
state: `services/agent` cannot generate a typed client for a service that has not published an
OpenAPI contract (`packages/contracts/openapi/` has only `internal-data-integration.yaml` and
`internal-risk-knowledge.yaml`), and this service's own scope stops at `services/agent/` — it
cannot go publish one on their behalf either.

The LLM never sees this registry or any tool schema directly: nodes call typed client methods
(`app/tools/clients/`), not a generic "call a tool by name" primitive, so there is no path for a
model to request an arbitrary URL, tool, or HTTP verb — the plan's "ห้ามให้ LLM เห็น generic HTTP,
shell, filesystem, database หรือ arbitrary Python tool" is true by construction, not by a runtime
check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.graph.state import GraphStage, Intent

#: `Intent`s the standard evidence -> decision -> recommendation pipeline runs for.
#: `EMERGENCY` never reaches these tools — it takes `emergency_shortcut` instead
#: (`app/graph/nodes/emergency_shortcut.py`).
_PIPELINE_INTENTS = frozenset(
    {Intent.PLAN_TRIP, Intent.CHECK_SAFETY, Intent.ASK_INFORMATION, Intent.FOLLOW_UP}
)


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    #: Stable name/version, e.g. "data_integration.create_snapshot@1" — recorded on every tool
    #: call audit row (`agent.tool_calls.tool_name`), never a bare service/endpoint name.
    name: str
    #: Which node calls it — the one place `guard_node`'s per-tool budget bookkeeping and a
    #: future permission check can look up "is this node allowed to use this tool".
    node: str
    allowed_intents: frozenset[Intent]
    allowed_stages: frozenset[GraphStage]
    #: Env var name whose value is this tool's base URL — never a literal here and never a value
    #: an LLM or the request body can influence ("base URL จาก env allowlist; agent ห้ามรับ URL จาก
    #: model/user"). Resolved through `Settings`, not read from `os.environ` directly, so it goes
    #: through the same env-var allowlisting pydantic-settings already applies everywhere else.
    base_url_setting: str
    #: Contract error codes (00_API_AND_DATA_CONTRACTS.md §1) this tool's client retries.
    #: Everything else is a non-retryable failure on the first attempt.
    retryable_error_codes: frozenset[str]
    max_attempts: int
    #: True if a caller-supplied `Idempotency-Key`/`request_id` makes a repeat with the same body
    #: return the original result rather than creating a duplicate.
    idempotent: bool
    #: Field names in this tool's request/response that must never be logged or included in a
    #: tool-call audit row verbatim (`agent.tool_calls` never stores "sensitive raw payload").
    redact_fields: frozenset[str] = field(default_factory=frozenset)
    #: `None` while the tool has no published OpenAPI contract yet.
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


#: Contract error codes that are safe to retry on every tool: a dependency that was briefly
#: unreachable or rate-limited, not one that rejected the request outright.
_TRANSIENT_ERROR_CODES = frozenset({"DEPENDENCY_TIMEOUT", "DEPENDENCY_UNAVAILABLE", "RATE_LIMITED"})

REGISTRY: dict[str, ToolDescriptor] = {
    "external_data.query_context@1": ToolDescriptor(
        name="external_data.query_context@1",
        node="fetch_external_data",
        allowed_intents=_PIPELINE_INTENTS,
        allowed_stages=frozenset({GraphStage.FETCHING_EXTERNAL_DATA}),
        base_url_setting="external_data_base_url",
        retryable_error_codes=_TRANSIENT_ERROR_CODES,
        max_attempts=2,
        idempotent=True,
        unavailable_reason=(
            "module 04 has not published an OpenAPI contract for /internal/v1/context/query yet"
        ),
    ),
    "data_integration.create_snapshot@1": ToolDescriptor(
        name="data_integration.create_snapshot@1",
        node="integrate_data",
        allowed_intents=_PIPELINE_INTENTS,
        allowed_stages=frozenset({GraphStage.INTEGRATING_DATA}),
        base_url_setting="data_integration_base_url",
        retryable_error_codes=_TRANSIENT_ERROR_CODES,
        max_attempts=2,
        idempotent=True,  # keyed on request_id + content hash + schema_version, per the spec
    ),
    "risk_knowledge.build_evidence_package@1": ToolDescriptor(
        name="risk_knowledge.build_evidence_package@1",
        node="build_evidence",
        allowed_intents=_PIPELINE_INTENTS,
        allowed_stages=frozenset(
            {
                GraphStage.ASSESSING_RISK,
                GraphStage.RETRIEVING_GUIDANCE,
                GraphStage.EVALUATING_ROUTES,
            }
        ),
        base_url_setting="risk_knowledge_base_url",
        retryable_error_codes=_TRANSIENT_ERROR_CODES,
        max_attempts=2,
        # Not idempotent per its own contract (no idempotency key in the spec); a retry after a
        # confirmed non-timeout failure is not safe to assume returns the same package.
        idempotent=False,
    ),
    "decision_engine.create_decision@1": ToolDescriptor(
        name="decision_engine.create_decision@1",
        node="make_decision",
        allowed_intents=_PIPELINE_INTENTS,
        allowed_stages=frozenset({GraphStage.MAKING_DECISION, GraphStage.EXPLAINING}),
        base_url_setting="decision_engine_base_url",
        retryable_error_codes=_TRANSIENT_ERROR_CODES,
        max_attempts=2,
        # services/decision-engine/app/main.py accepts an `Idempotency-Key` header on this
        # endpoint — read directly from its code, since it has no published OpenAPI contract to
        # read instead.
        idempotent=True,
        unavailable_reason=(
            "module 07 has not published an OpenAPI contract for /internal/v1/decisions yet"
        ),
    ),
    "recommendation.create_recommendation@1": ToolDescriptor(
        name="recommendation.create_recommendation@1",
        node="format_recommendation",
        allowed_intents=_PIPELINE_INTENTS,
        allowed_stages=frozenset({GraphStage.FORMATTING_RESPONSE}),
        base_url_setting="recommendation_base_url",
        retryable_error_codes=_TRANSIENT_ERROR_CODES,
        max_attempts=2,
        idempotent=True,
        unavailable_reason=(
            "module 08 has not published an OpenAPI contract for /internal/v1/recommendations yet"
        ),
    ),
}
