"""The run state machine, and the event bridge's refusal to forward what it cannot validate.

Pure unit tests — no database, no Redis, no HTTP. These cover the two decisions that stop a
downstream service from saying something this service would then repeat to a traveller:

* a report that would move a run backwards, or out of a terminal state, is refused;
* an event whose payload is not exactly what the contract describes is dropped.

The second one is the leak guard. It is tested with the shapes that would actually hurt — a prompt,
a provider body, an access token riding along in an extra field — because "extras are forbidden" is
a claim about behaviour, not a config line.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.domain import run as machine
from app.services import run_events

TERMINAL = ["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]
IN_FLIGHT = ["QUEUED", "RUNNING", "NEEDS_INPUT"]


class TestTransitions:
    @pytest.mark.parametrize("status", TERMINAL)
    @pytest.mark.parametrize("proposed", [*TERMINAL, *IN_FLIGHT])
    def test_nothing_follows_a_terminal_state(self, status: str, proposed: str) -> None:
        """A finished run stays finished, whatever arrives afterwards.

        This is the one that matters most. A traveller told their assessment failed has already
        decided what to do about it; a late message reviving the run would change the answer under
        them without their ever seeing why.
        """
        assert not machine.can_transition(status, proposed)
        with pytest.raises(machine.IllegalTransition):
            machine.transition(status, proposed)

    @pytest.mark.parametrize("status", IN_FLIGHT)
    def test_nothing_returns_to_queued(self, status: str) -> None:
        """Queued means not yet started, and a started run cannot become unstarted."""
        assert not machine.can_transition(status, "QUEUED")

    def test_running_may_repeat_itself(self) -> None:
        """The most common message of all: a stage or percent update on a run already running."""
        assert machine.can_transition("RUNNING", "RUNNING")

    def test_needs_input_may_resume(self) -> None:
        assert machine.can_transition("NEEDS_INPUT", "RUNNING")

    @pytest.mark.parametrize("proposed", TERMINAL)
    def test_an_in_flight_run_may_finish_any_way(self, proposed: str) -> None:
        assert machine.can_transition("QUEUED", proposed)
        assert machine.can_transition("RUNNING", proposed)

    def test_an_unknown_status_is_refused_not_guessed(self) -> None:
        """Version skew is reported, never coerced onto the nearest known value.

        `SUCCEEDED` is the trap: it is obviously meant to be `COMPLETED`, and guessing that would
        be how a future agent release starts reporting failures as successes.
        """
        with pytest.raises(machine.UnknownStatus):
            machine.ensure_known("SUCCEEDED")
        with pytest.raises(machine.UnknownStatus):
            machine.transition("RUNNING", "SUCCEEDED")

    def test_terminal_set_matches_the_contract(self) -> None:
        assert frozenset(TERMINAL) == machine.TERMINAL
        assert frozenset(TERMINAL) | frozenset(IN_FLIGHT) == machine.ALL_STATUSES

    def test_an_unknown_stage_becomes_none_rather_than_failing(self) -> None:
        """A stage is a display hint. Losing the hint beats failing a run over a label."""
        assert machine.stage_or_none("ASSESSING_RISK") == "ASSESSING_RISK"
        assert machine.stage_or_none("READING_TEA_LEAVES") is None
        assert machine.stage_or_none(None) is None


class TestEventDecoding:
    """`decode` is the last point at which a bad event can be stopped before a browser sees it."""

    def _entry(self, event_type: str, payload: dict[str, object]) -> dict[str, str]:
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "occurred_at": datetime.now(UTC).isoformat(),
            "producer": "agent",
            "schema_version": "1",
            "correlation_id": "",
            "payload": json.dumps(payload, default=str),
        }

    def test_a_valid_progress_event_survives(self) -> None:
        request_id = uuid.uuid4()
        entry = self._entry(
            "run.progress",
            {
                "request_id": str(request_id),
                "stage": "ASSESSING_RISK",
                "percent": 40,
                "message_key": "run.assessing_risk",
            },
        )
        decoded = run_events.decode(entry)
        assert decoded is not None
        event_type, payload = decoded
        assert event_type == "run.progress"
        assert payload["stage"] == "ASSESSING_RISK"
        assert payload["percent"] == 40

    @pytest.mark.parametrize(
        ("leak_field", "leak_value"),
        [
            ("prompt", "You are a travel safety assistant. The user's home address is..."),
            ("raw_provider_body", {"observations": [{"lat": 13.7, "lon": 100.5}]}),
            ("access_token", "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"),
            ("chain_of_thought", "First I considered the flood risk, then..."),
        ],
    )
    def test_an_event_carrying_an_undeclared_field_is_dropped(
        self, leak_field: str, leak_value: object
    ) -> None:
        """The contract forbids these on the wire, and the bridge is what enforces it.

        Dropping the whole event rather than stripping the field is deliberate: an event that
        contains something nobody expected is an event nobody has reasoned about, and forwarding
        the rest of it assumes the surprise was confined to the one field that was noticed.
        """
        entry = self._entry(
            "run.progress",
            {
                "request_id": str(uuid.uuid4()),
                "stage": "ASSESSING_RISK",
                "percent": 40,
                "message_key": "run.assessing_risk",
                leak_field: leak_value,
            },
        )
        assert run_events.decode(entry) is None

    def test_an_unknown_event_type_is_dropped(self) -> None:
        entry = self._entry("run.thinking_out_loud", {"request_id": str(uuid.uuid4())})
        assert run_events.decode(entry) is None

    def test_a_malformed_payload_is_dropped(self) -> None:
        entry = self._entry("run.progress", {})
        entry["payload"] = "{not json"
        assert run_events.decode(entry) is None

    def test_a_progress_event_missing_a_required_field_is_dropped(self) -> None:
        entry = self._entry(
            "run.progress",
            {"request_id": str(uuid.uuid4()), "percent": 40},  # no stage, no message_key
        )
        assert run_events.decode(entry) is None

    def test_a_rendered_sentence_is_refused_where_a_key_belongs(self) -> None:
        """`message_key` is a translation key. A sentence here would be one locale's only."""
        entry = self._entry(
            "run.progress",
            {
                "request_id": str(uuid.uuid4()),
                "stage": "ASSESSING_RISK",
                "message_key": "Checking the weather along your route",
            },
        )
        assert run_events.decode(entry) is None

    def test_percent_outside_the_range_is_dropped(self) -> None:
        entry = self._entry(
            "run.progress",
            {
                "request_id": str(uuid.uuid4()),
                "stage": "ASSESSING_RISK",
                "percent": 140,
                "message_key": "run.assessing_risk",
            },
        )
        assert run_events.decode(entry) is None


class TestLastEventId:
    """A `Last-Event-ID` header is client-supplied and becomes an XREAD argument."""

    def test_a_valid_stream_id_is_kept(self) -> None:
        assert run_events.validate_last_event_id("1758355200000-0") == "1758355200000-0"

    def test_absent_means_from_the_beginning(self) -> None:
        assert run_events.validate_last_event_id(None) == "0-0"

    @pytest.mark.parametrize(
        "value",
        [
            "$",  # Redis' "only new entries" token: would silently skip what the client missed
            ">",
            "not-an-id",
            "1758355200000",
            "1758355200000-0-0",
            "*",
            "0-0; FLUSHALL",
            "x" * 65,
        ],
    )
    def test_anything_else_falls_back_to_the_beginning(self, value: str) -> None:
        """Replaying an event the client already saw is harmless. Guessing is not."""
        assert run_events.validate_last_event_id(value) == "0-0"


class TestWireFormat:
    def test_an_event_is_framed_with_id_event_and_data(self) -> None:
        frame = run_events.format_sse("17-0", "heartbeat", {"server_time": "2026-09-20T10:00:00Z"})
        assert frame.startswith("id: 17-0\nevent: heartbeat\ndata: ")
        assert frame.endswith("\n\n")
        body = frame.split("data: ", 1)[1].strip()
        assert json.loads(body) == {"server_time": "2026-09-20T10:00:00Z"}
