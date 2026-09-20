"""Log redaction.

Security invariant § 11: tokens, email, phone and exact coordinates must not
reach a log line. The timestamp case below is a regression test - the phone
pattern originally ate every ISO-8601 date it saw.
"""

from __future__ import annotations

import pytest

from app.observability.logging import _redact, _redact_text


def test_iso_timestamp_survives_redaction() -> None:
    """Regression: "2026-09-19" is ten digits joined by dashes, which the phone
    pattern matched, turning every log timestamp into "[PHONE]"."""
    stamp = "2026-09-19T08:09:49.757615Z"
    assert _redact_text(stamp) == stamp


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-09-19",
        "2026-09-19T08:09:49Z",
        "2026-09-19T08:09:49.123456Z",
        "2026-09-19 08:09:49",
        "2026-09-19T08:09:49+07:00",
    ],
)
def test_timestamp_shapes_are_preserved(stamp: str) -> None:
    assert _redact_text(stamp) == stamp


def test_timestamp_inside_a_message_is_preserved() -> None:
    message = "fetched at 2026-09-19T08:09:49Z from provider"
    assert _redact_text(message) == message


def test_phone_number_is_still_redacted() -> None:
    assert "[PHONE]" in _redact_text("call +66 81 234 5678 now")


def test_email_is_redacted() -> None:
    assert _redact_text("contact traveller@example.com") == "contact [EMAIL]"


def test_api_key_in_a_query_string_is_redacted() -> None:
    redacted = _redact_text("https://api.example/v1?api_key=abcd1234&x=1")
    assert "abcd1234" not in redacted
    assert "[REDACTED]" in redacted


def test_bearer_token_is_redacted() -> None:
    redacted = _redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9")
    assert "eyJhbGciOiJIUzI1NiJ9" not in redacted


def test_exact_coordinates_are_rounded() -> None:
    """Full precision identifies a person; the payload keeps it, the log does not."""
    event = _redact(None, "info", {"latitude": 13.756331, "longitude": 100.501762})
    assert event["latitude"] == 13.8
    assert event["longitude"] == 100.5


def test_redaction_leaves_ordinary_fields_alone() -> None:
    event = _redact(None, "info", {"event": "provider_retry", "provider": "gdacs"})
    assert event == {"event": "provider_retry", "provider": "gdacs"}
