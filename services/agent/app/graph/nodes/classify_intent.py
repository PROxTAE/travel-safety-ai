"""`classify_intent` node.

Phase 2 (`feat/03-intent-extraction`): deterministic rules first
(`docs/intent-and-required-fields.md` §1, `app/intent/rules.py`); the LLM classifier
(`app/intent/llm_classifier.py`) only runs when the deterministic rules find the question
ambiguous *and* an LLM classifier was actually built (`Settings.llm_enabled` plus a usable API
key — see `build_llm_classifier`). Any LLM failure — not configured, timeout, malformed response —
falls back to `ASK_INFORMATION` rather than failing the run: intent is a routing hint, not a
safety-critical fact on its own (the *safety-critical* intents, `EMERGENCY` and `CHECK_SAFETY`,
are matched deterministically before the LLM is ever consulted), so a safe default beats a hard
stop here.

Built as a factory (`build_classify_intent_node`), not a bare `async def`, because it needs
`Settings` and the optional LLM client — both come from `app/graph/builder.py` at graph-build
time, never from `AgentState` (an LLM client is not serializable and must never enter a
checkpoint).
"""

from __future__ import annotations

from app.budgets import NodeFn, NodeUpdate
from app.graph.state import AgentState, Intent
from app.intent.llm_classifier import IntentClassifierClient
from app.intent.rules import classify_deterministic
from app.settings import Settings


async def _try_llm_classify(
    client: IntentClassifierClient, question: str, locale: str
) -> Intent | None:
    """`None` on any failure — not configured, timeout, malformed response. The LLM path
    degrades to the deterministic default (`ASK_INFORMATION`); it never fails the run.
    """
    try:
        result = await client.classify(question, locale)
    except Exception:
        return None
    return result.intent


def build_classify_intent_node(
    settings: Settings, llm_classifier: IntentClassifierClient | None
) -> NodeFn:
    async def classify_intent(state: AgentState) -> NodeUpdate:
        deterministic = classify_deterministic(state.input)
        if deterministic is not None:
            return {"input": state.input.model_copy(update={"intent": deterministic})}

        question = state.input.travel_request.question
        # classify_deterministic only returns None when the request carries a question.
        assert question is not None

        intent = Intent.ASK_INFORMATION
        if settings.llm_enabled and llm_classifier is not None:
            llm_intent = await _try_llm_classify(
                llm_classifier, question, state.input.travel_request.locale
            )
            if llm_intent is not None:
                intent = llm_intent

        return {"input": state.input.model_copy(update={"intent": intent})}

    return classify_intent
