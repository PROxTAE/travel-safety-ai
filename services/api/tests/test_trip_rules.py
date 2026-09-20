"""The trip domain rules, tested without a request, a session or a container.

These are the checks that decide whether a journey can be saved, and they are the cheapest place in
the service to be thorough. Every case here corresponds to something a real client sends: a naive
timestamp from a date picker, a return before a departure, a mode nobody has data for, a pin the
user never confirmed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import trip as rules
from app.errors.codes import FieldErrorCode

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def codes(errors: list[object]) -> list[str]:
    return [error.code.value for error in errors]  # type: ignore[attr-defined]


def paths(errors: list[object]) -> list[str]:
    return [error.path for error in errors]  # type: ignore[attr-defined]


# --- time zones -----------------------------------------------------------------------------------


def test_a_real_time_zone_is_accepted() -> None:
    assert rules.validate_timezone("Asia/Bangkok") == []


def test_a_plausible_misspelling_is_rejected() -> None:
    """`Asia/Bangkgok` matches the contract's pattern and is not a zone.

    Pattern validation alone would store it, and every local time computed from the trip afterwards
    would be wrong in a way nothing else would catch.
    """
    errors = rules.validate_timezone("Asia/Bangkgok")

    assert codes(errors) == [FieldErrorCode.INVALID_FORMAT.value]


def test_the_timezone_error_path_can_be_redirected() -> None:
    """PATCH validates the merged journey, so the path has to name the field that was sent."""
    errors = rules.validate_timezone("Nowhere/Here", path="trip.timezone")

    assert paths(errors) == ["trip.timezone"]


# --- departure and return ---------------------------------------------------------------------


def test_a_departure_inside_the_window_is_accepted() -> None:
    errors = rules.validate_departure_window(
        NOW + timedelta(days=3), None, now=NOW, max_backdate_seconds=3600, max_future_days=365
    )

    assert errors == []


def test_a_traveller_already_under_way_can_still_save_the_trip() -> None:
    """Backdating is allowed inside the configured window; zero would be wrong.

    Someone who set off an hour ago and only now opens the app is the case this exists for.
    """
    errors = rules.validate_departure_window(
        NOW - timedelta(minutes=30), None, now=NOW, max_backdate_seconds=3600, max_future_days=365
    )

    assert errors == []


def test_a_departure_well_in_the_past_is_rejected() -> None:
    errors = rules.validate_departure_window(
        NOW - timedelta(days=2), None, now=NOW, max_backdate_seconds=3600, max_future_days=365
    )

    assert codes(errors) == [FieldErrorCode.OUT_OF_RANGE.value]
    assert paths(errors) == ["departure_time"]


def test_a_departure_beyond_the_horizon_is_rejected() -> None:
    errors = rules.validate_departure_window(
        NOW + timedelta(days=400), None, now=NOW, max_backdate_seconds=3600, max_future_days=365
    )

    assert codes(errors) == [FieldErrorCode.OUT_OF_RANGE.value]


def test_a_return_before_departure_is_rejected() -> None:
    errors = rules.validate_departure_window(
        NOW + timedelta(days=3),
        NOW + timedelta(days=2),
        now=NOW,
        max_backdate_seconds=3600,
        max_future_days=365,
    )

    assert codes(errors) == [FieldErrorCode.INCONSISTENT.value]
    assert paths(errors) == ["return_time"]


def test_a_return_equal_to_departure_is_rejected() -> None:
    """A zero-length trip is a date picker that never moved, not a journey."""
    departure = NOW + timedelta(days=3)
    errors = rules.validate_departure_window(
        departure, departure, now=NOW, max_backdate_seconds=3600, max_future_days=365
    )

    assert codes(errors) == [FieldErrorCode.INCONSISTENT.value]


def test_every_time_problem_is_reported_at_once() -> None:
    """Reporting one error per round trip costs the user a submission per mistake."""
    errors = rules.validate_departure_window(
        NOW - timedelta(days=5),
        NOW - timedelta(days=6),
        now=NOW,
        max_backdate_seconds=3600,
        max_future_days=365,
    )

    assert sorted(paths(errors)) == ["departure_time", "return_time"]


# --- travel modes -----------------------------------------------------------------------------


def test_a_supported_mode_is_accepted() -> None:
    assert rules.validate_travel_modes(["CAR"], supported=["CAR", "TRAIN"]) == []


def test_a_mode_with_no_data_source_is_refused() -> None:
    """Accepting it would mean assessing a leg nothing can answer for.

    An answer that says nothing about the flight reads as an answer that found nothing wrong with
    it, which is the failure this whole project is built to avoid.
    """
    errors = rules.validate_travel_modes(["FLIGHT"], supported=["CAR", "TRAIN"])

    assert codes(errors) == [FieldErrorCode.UNSUPPORTED_VALUE.value]
    assert paths(errors) == ["travel_modes[0]"]


def test_the_index_of_the_unsupported_mode_is_reported() -> None:
    errors = rules.validate_travel_modes(["CAR", "FLIGHT"], supported=["CAR"])

    assert paths(errors) == ["travel_modes[1]"]


def test_a_repeated_mode_is_rejected() -> None:
    errors = rules.validate_travel_modes(["CAR", "CAR"], supported=["CAR"])

    assert codes(errors) == [FieldErrorCode.INCONSISTENT.value]


# --- confirmation -------------------------------------------------------------------------------


def test_two_confirmed_endpoints_pass() -> None:
    assert rules.validate_endpoints_confirmed(True, True) == []


@pytest.mark.parametrize(
    ("origin", "destination", "expected"),
    [
        (False, True, ["origin.confirmed_by_user"]),
        (True, False, ["destination.confirmed_by_user"]),
        (False, False, ["origin.confirmed_by_user", "destination.confirmed_by_user"]),
    ],
)
def test_an_unconfirmed_endpoint_is_named(
    origin: bool, destination: bool, expected: list[str]
) -> None:
    """Geocoding "Springfield" returns a list, and the first entry is a guess."""
    errors = rules.validate_endpoints_confirmed(origin, destination)

    assert paths(errors) == expected
    assert set(codes(errors)) == {FieldErrorCode.NOT_CONFIRMED.value}


# --- status transitions ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        ("DRAFT", "PLANNED"),
        ("PLANNED", "ACTIVE"),
        ("ACTIVE", "COMPLETED"),
        ("PLANNED", "CANCELLED"),
        ("DRAFT", "DRAFT"),
    ],
)
def test_an_allowed_transition_passes(current: str, requested: str) -> None:
    assert rules.validate_status_transition(current, requested) == []


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        ("COMPLETED", "ACTIVE"),
        ("CANCELLED", "PLANNED"),
        ("ACTIVE", "DRAFT"),
        ("DRAFT", "ACTIVE"),
    ],
)
def test_a_backwards_transition_is_refused(current: str, requested: str) -> None:
    """Re-opening a finished trip would silently re-use an assessment made for other conditions."""
    errors = rules.validate_status_transition(current, requested)

    assert codes(errors) == [FieldErrorCode.INCONSISTENT.value]


def test_a_client_cannot_set_deleted_through_patch() -> None:
    """DELETE also schedules the purge of child data; PATCH would skip that."""
    errors = rules.validate_status_transition("PLANNED", "DELETED")

    assert codes(errors) == [FieldErrorCode.UNSUPPORTED_VALUE.value]


def test_every_contract_status_appears_in_the_transition_table() -> None:
    """A status added to the contract without a row here would be unreachable."""
    assert set(rules.ALLOWED_TRANSITIONS) == rules.TRIP_STATUSES


# --- assessment invalidation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["origin", "destination", "departure_time", "return_time", "timezone", "travel_modes"]
)
def test_changing_the_journey_invalidates_its_assessment(field: str) -> None:
    assert rules.journey_changed({field}) is True


@pytest.mark.parametrize("field", ["title", "preferences", "status"])
def test_changing_something_else_does_not(field: str) -> None:
    """Renaming a trip must not throw away a verdict that still applies to it."""
    assert rules.journey_changed({field}) is False


# --- ETags --------------------------------------------------------------------------------------


def test_the_etag_is_the_weak_form_the_contract_specifies() -> None:
    assert rules.etag_for(3) == 'W/"3"'


@pytest.mark.parametrize("header", ['W/"3"', '"3"', "3", ' W/"3" ', 'w/"3"'])
def test_every_way_a_client_quotes_if_match_is_accepted(header: str) -> None:
    """Clients and proxies each quote it differently; rejecting over quoting is a bad trade."""
    assert rules.revision_from_if_match(header) == 3


@pytest.mark.parametrize("header", ["*", "", "abc", 'W/"abc"', "3.5", "-1"])
def test_anything_that_is_not_a_revision_is_refused(header: str) -> None:
    """`*` especially: it means "any current version", which is the overwrite this prevents."""
    assert rules.revision_from_if_match(header) is None
