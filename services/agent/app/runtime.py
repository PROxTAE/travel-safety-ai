"""The app's shared runtime objects (compiled graph, checkpointer, repositories, publisher).

Built once in `app.main`'s lifespan and stored on `app.state.runtime`; `app/api/internal.py`
depends on `get_runtime` rather than importing from `app.main` directly, which would be circular
(`main.py` includes `api/internal.py`'s router).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from app.checkpoints.postgres import RunsRepository
from app.graph.state import AgentState
from app.progress.publisher import ProgressPublisher
from app.settings import Settings


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    graph: CompiledStateGraph[AgentState, None, AgentState, AgentState]
    checkpointer: BaseCheckpointSaver[str] | None
    runs: RunsRepository | None
    publisher: ProgressPublisher | None
    #: Set when a startup dependency (database/checkpointer) failed to come up. `/health/ready`
    #: reports it; requests still fail individually rather than crash-looping the process.
    startup_error: str | None = None


def get_runtime(request: Request) -> AppRuntime:
    runtime = request.app.state.runtime
    assert isinstance(runtime, AppRuntime)  # narrows Any from Starlette's app.state
    return runtime
