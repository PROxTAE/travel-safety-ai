"""`degraded_or_escalate` node."""

from __future__ import annotations

from app.graph.state import AgentState, QualityFlag


async def degraded_or_escalate(state: AgentState) -> dict[str, object]:
    degraded = list(state.quality.degraded_services)
    if "evidence" not in degraded:
        degraded.append("evidence")
    quality = state.quality.model_copy(
        update={
            "degraded_services": degraded,
            "quality_flags": [*state.quality.quality_flags, QualityFlag.INCOMPLETE],
        }
    )
    return {"quality": quality}
