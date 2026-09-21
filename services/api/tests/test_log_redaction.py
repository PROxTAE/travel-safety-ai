"""Log redaction.

Redaction is a processor in the logging pipeline rather than a rule people follow, so these tests
check the pipeline. The cases are the ones that actually happen: a token that arrives as a header
value, a coordinate nested inside a trip object, an email inside a free-text message, and a medical
note in a profile.

Exact coordinates are treated as sensitive alongside credentials and medical data. A latitude in a
log file is a person's location history.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.observability.logging import REDACTED, _redact_text, redact_processor


def redact(event: dict[str, Any]) -> dict[str, Any]:
    return redact_processor(None, "info", event)


def test_authorization_header_value_is_removed() -> None:
    result = redact({"event": "request", "authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.abc.def"})

    assert result["authorization"] == REDACTED


@pytest.mark.parametrize(
    "key",
    ["access_token", "refresh_token", "id_token", "password", "client_secret", "api_key", "cookie"],
)
def test_every_credential_key_is_removed(key: str) -> None:
    assert redact({key: "value-that-must-not-appear"})[key] == REDACTED


@pytest.mark.parametrize(
    "key", ["medical_notes", "allergies", "medications", "blood_type", "emergency_profile"]
)
def test_health_data_is_removed(key: str) -> None:
    assert redact({key: "anything"})[key] == REDACTED


@pytest.mark.parametrize("key", ["lat", "lon", "latitude", "longitude", "coordinates"])
def test_exact_coordinates_are_removed(key: str) -> None:
    assert redact({key: 13.7563})[key] == REDACTED


def test_coordinates_nested_inside_a_trip_are_removed() -> None:
    """The realistic case: nobody logs a bare latitude, they log the object that contains one."""
    event = {
        "event": "trip_created",
        "trip": {
            "origin": {"display_name": "Bangkok", "coordinates": [100.5014, 13.754]},
            "travel_modes": ["TRAIN"],
        },
    }

    rendered = json.dumps(redact(event))

    assert "100.5014" not in rendered
    assert "13.754" not in rendered


def test_coarse_location_is_kept() -> None:
    """Country and timezone make a log useful for debugging coverage without locating a person."""
    result = redact({"country_code": "TH", "timezone": "Asia/Bangkok"})

    assert result["country_code"] == "TH"
    assert result["timezone"] == "Asia/Bangkok"


def test_request_and_response_bodies_are_never_logged() -> None:
    """There is no safe subset of a body on this API."""
    for key in ("body", "request_body", "response_body", "payload"):
        assert redact({key: {"anything": "at all"}})[key] == REDACTED


def test_a_token_embedded_in_a_message_is_scrubbed() -> None:
    message = "upstream rejected Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature"

    assert "eyJhbGciOiJIUzI1NiJ9" not in _redact_text(message)


def test_an_email_in_free_text_is_scrubbed() -> None:
    assert "traveller@example.com" not in _redact_text("could not notify traveller@example.com")


def test_a_long_digit_run_is_scrubbed() -> None:
    """Catches phone numbers and policy references that arrive inside a sentence."""
    assert "0812345678" not in _redact_text("contact 0812345678 for assistance")


def test_short_numbers_survive() -> None:
    """Emergency short codes and status codes must stay readable."""
    text = _redact_text("emergency number 191 returned status 503")

    assert "191" in text
    assert "503" in text


def test_matching_is_on_the_whole_key_not_a_substring() -> None:
    """`authorization_policy_version` is metadata, not a credential."""
    result = redact({"authorization_policy_version": "1.2.0"})

    assert result["authorization_policy_version"] == "1.2.0"


def test_key_matching_ignores_case_and_hyphens() -> None:
    assert redact({"X-Access-Token": "secret"})["X-Access-Token"] == REDACTED


def test_lists_of_objects_are_walked() -> None:
    event = {
        "contacts": [{"name": "A", "phone": "0812345678"}, {"name": "B", "phone": "0899999999"}]
    }

    rendered = json.dumps(redact(event))

    assert "0812345678" not in rendered
    assert "0899999999" not in rendered


def test_deep_nesting_is_truncated_rather_than_emitted_unexamined() -> None:
    """Refusing to walk further is safe; guessing what is down there is not."""
    event: dict[str, Any] = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"secret": "deep"}}}}}}}}

    assert "deep" not in json.dumps(redact(event))


def test_redaction_is_not_fooled_by_a_numeric_coordinate() -> None:
    """Redaction keys on the field name, so the value's type does not matter."""
    assert redact({"longitude": 100.5014})["longitude"] == REDACTED
    assert redact({"longitude": "100.5014"})["longitude"] == REDACTED


def test_correlation_identifiers_survive_verbatim() -> None:
    """A UUID whose first group is all digits was being mangled by the long-number rule.

    The correlation id is the one field that must be byte-identical across eight services; a
    partially redacted one silently breaks every trace lookup that uses it.
    """
    correlation = "12345678-8cf2-467a-aff6-1b58721517f9"

    result = redact({"correlation_id": correlation, "request_id": correlation})

    assert result["correlation_id"] == correlation
    assert result["request_id"] == correlation


def test_resource_identifiers_survive_verbatim() -> None:
    """Debugging a report needs the trip id it is about; the id itself reveals nothing."""
    trip_id = "00000000-1111-4222-8333-444444444444"

    assert redact({"trip_id": trip_id})["trip_id"] == trip_id


def test_an_identifier_key_does_not_excuse_a_sensitive_one() -> None:
    """The allowlist is checked after the deny list, not instead of it."""
    assert (
        redact({"access_token": "12345678-8cf2-467a-aff6-1b58721517f9"})["access_token"] == REDACTED
    )
