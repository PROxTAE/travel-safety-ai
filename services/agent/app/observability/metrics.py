"""Prometheus metrics exposed at `GET /metrics`.

Deliberately minimal for Phase 1 (the plan's step 1 asks only for a working `/metrics` endpoint).
Per-node span/duration tracing, LLM token/cost metrics and the full evaluation-suite metrics
(`03_TRAVEL_AI_AGENT_IMPLEMENTATION.md` Phase 6, "Observability and evaluation") land later —
this module is the foundation `guard_node` can attach to then (see its docstring), not the final
metric set.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

RUNS_TOTAL = Counter("agent_runs_total", "Agent runs completed, by terminal status", ["status"])
RUN_DURATION_SECONDS = Histogram(
    "agent_run_duration_seconds", "Wall-clock time from run creation to terminal status"
)
