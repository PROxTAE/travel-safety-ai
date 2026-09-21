"""The assessment run state machine.

A run is the one thing in this service whose state is decided somewhere else. The agent reports
progress, and this module decides which of those reports are allowed to change what the API
believes. Without it, an out-of-order or replayed message could move a run backwards — and a run
that has already been reported to a traveller as FAILED must never start claiming to be RUNNING
again, because the traveller has by then done something with the failure.

Three rules, and each one exists because the alternative is worse:

* **A terminal state is final.** `COMPLETED`, `PARTIAL`, `FAILED` and `CANCELLED` accept no
  successor. A late message from the agent about work that finished is dropped, not applied.
* **Progress does not run backwards.** `RUNNING` cannot return to `QUEUED`. Stage order is not
  enforced — the agent may legitimately revisit a stage — but the status is.
* **An unknown status is refused.** A status this contract does not define is a version skew
  between two services, and guessing which of ours it resembles is how a failure gets displayed
  as a success.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

RunStatus = Literal[
    "QUEUED",
    "RUNNING",
    "NEEDS_INPUT",
    "COMPLETED",
    "PARTIAL",
    "FAILED",
    "CANCELLED",
]

RunStage = Literal[
    "VALIDATING",
    "FETCHING_EXTERNAL_DATA",
    "INTEGRATING_DATA",
    "ASSESSING_RISK",
    "RETRIEVING_GUIDANCE",
    "EVALUATING_ROUTES",
    "MAKING_DECISION",
    "EXPLAINING",
    "FORMATTING_RESPONSE",
]

#: Every status the contract defines, for validating what a downstream service sent us.
ALL_STATUSES: Final[frozenset[str]] = frozenset(get_args(RunStatus))
ALL_STAGES: Final[frozenset[str]] = frozenset(get_args(RunStage))

#: States from which no further transition is permitted. The run is over and the record is history.
TERMINAL: Final[frozenset[str]] = frozenset({"COMPLETED", "PARTIAL", "FAILED", "CANCELLED"})

#: What may follow what. Absent from a value's set means the transition is refused.
#:
#: `RUNNING -> RUNNING` is allowed on purpose: that is a stage or percent update, which is the most
#: common message of all. `NEEDS_INPUT -> RUNNING` is the resume path. Nothing returns to `QUEUED`,
#: because queued means "not yet started" and a run that has started cannot become unstarted.
_ALLOWED: Final[dict[str, frozenset[str]]] = {
    "QUEUED": frozenset({"RUNNING", "NEEDS_INPUT", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}),
    "RUNNING": frozenset({"RUNNING", "NEEDS_INPUT", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}),
    "NEEDS_INPUT": frozenset(
        {"RUNNING", "NEEDS_INPUT", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"}
    ),
    "COMPLETED": frozenset(),
    "PARTIAL": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}


class UnknownStatus(ValueError):
    """A status outside the contract. Treated as version skew, never coerced into a known one."""


class IllegalTransition(ValueError):
    """A transition the state machine refuses."""

    def __init__(self, current: str, proposed: str) -> None:
        super().__init__(f"{current} -> {proposed}")
        self.current = current
        self.proposed = proposed


def is_terminal(status: str) -> bool:
    return status in TERMINAL


def ensure_known(status: str) -> RunStatus:
    """Validate a status that arrived from another service."""
    if status not in ALL_STATUSES:
        raise UnknownStatus(status)
    return status  # type: ignore[return-value]


def can_transition(current: str, proposed: str) -> bool:
    """Whether `proposed` may follow `current`. Both must already be known statuses."""
    return proposed in _ALLOWED.get(current, frozenset())


def transition(current: str, proposed: str) -> RunStatus:
    """The new status, or an exception explaining why it was refused.

    Raises `UnknownStatus` when either side is outside the contract, and `IllegalTransition` when
    the move is backwards or out of a terminal state.
    """
    ensure_known(current)
    ensure_known(proposed)
    if not can_transition(current, proposed):
        raise IllegalTransition(current, proposed)
    return proposed  # type: ignore[return-value]


def stage_or_none(stage: str | None) -> RunStage | None:
    """Keep a stage only if the contract defines it.

    An unrecognised stage becomes `None` rather than an error: the stage is a display hint, and
    losing the hint is a much smaller harm than failing a run over a label. The status, which
    decides what the traveller is told, gets the strict treatment instead.
    """
    if stage is None or stage not in ALL_STAGES:
        return None
    return stage  # type: ignore[return-value]
