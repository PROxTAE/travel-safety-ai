"""What `official` means, and the one case the decision did not name.

Issue #32: `official` used to mean "a government body recorded this", which was
true of all 514 events in a live query - including a magnitude -0.48 earthquake
nobody can feel. A field with one value on every record carries no information.

The Lead settled it as "a warning or order has actually been issued". That
matters more than it sounds: shared context § 13 scenario 3 makes official
closure or high alert force `AVOID` **over** the LLM and the model score. It is
the strongest shortcut in the system.

The action item said "GDACS Orange/Red → True, USGS/EONET → False", which
matches the sample the issue was written from: the live feeds had no USGS PAGER
alert above green. But USGS PAGER does publish orange and red, for perhaps a
handful of earthquakes a year - and those are exactly the earthquakes this
field exists for. Hard-coding USGS to False would make the answer wrong at the
only moment it is load-bearing, and would contradict the definition just
agreed. So the rule here follows the definition rather than the provider list,
and `test_a_pager_red_earthquake_is_official` is the case to look at if that
reading is wrong.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from app.domain.canonical import warning_has_been_issued
from app.domain.enums import ProviderStatus
from app.domain.queries import DisasterQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture


def _adapter(provider_id: str, adapter_class: type) -> Any:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == provider_id)
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return adapter_class(provider, ProviderTransport(Defaults()), env="test")


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://example.invalid/feed",
        fetched_at=time.time(),
        elapsed_seconds=0.2,
    )


def _events(provider_id: str, adapter_class: type, payload: Any) -> list[Any]:
    adapter = _adapter(provider_id, adapter_class)
    response = _response(payload)
    return adapter.normalize(adapter.validate(response), response, DisasterQuery())


def _copy(fixture: str) -> Any:
    return json.loads(json.dumps(load_fixture(fixture)))


# ------------------------------------------------------------- the predicate


@pytest.mark.parametrize("level", ["Orange", "Red", "orange", "red", " RED "])
def test_a_high_alert_counts_as_a_warning(level: str) -> None:
    """Case and whitespace vary between providers: GDACS writes `Orange`, USGS
    PAGER writes `orange`."""
    assert warning_has_been_issued(level) is True


@pytest.mark.parametrize("level", ["Green", "green", "yellow", "", "   ", None])
def test_anything_below_orange_is_not_a_warning(level: str | None) -> None:
    """Green is a logged event and yellow is an advisory. Neither is the thing
    that forces AVOID."""
    assert warning_has_been_issued(level) is False


def test_an_unrecognised_level_is_not_treated_as_a_warning() -> None:
    """A provider inventing a new level must not silently escalate. Under-
    reporting is recoverable; a false AVOID on every record is not."""
    assert warning_has_been_issued("catastrophic") is False


# ------------------------------------------------------------------- GDACS


def test_a_gdacs_orange_event_is_official() -> None:
    payload = _copy("gdacs/eventlist_eq.json")
    for feature in payload["features"]:
        feature["properties"]["alertlevel"] = "Orange"

    from app.adapters.gdacs import GdacsAdapter

    events = _events("gdacs", GdacsAdapter, payload)

    assert events
    assert all(event.official for event in events)


def test_a_gdacs_green_event_is_not_official() -> None:
    from app.adapters.gdacs import GdacsAdapter

    payload = _copy("gdacs/eventlist_eq.json")
    for feature in payload["features"]:
        feature["properties"]["alertlevel"] = "Green"

    events = _events("gdacs", GdacsAdapter, payload)

    assert events
    assert not any(event.official for event in events)


def test_the_raw_alert_level_is_still_carried_either_way() -> None:
    """`official` is a summary. Module 06 may want the level itself, and losing
    it would force a second call to the provider."""
    from app.adapters.gdacs import GdacsAdapter

    payload = _copy("gdacs/eventlist_eq.json")
    for feature in payload["features"]:
        feature["properties"]["alertlevel"] = "Green"

    events = _events("gdacs", GdacsAdapter, payload)
    assert all(event.alert_level == "Green" for event in events)


# -------------------------------------------------------------------- USGS


def test_an_ordinary_earthquake_is_not_official() -> None:
    """The regression this change exists for.

    A magnitude -0.48 reading was `official: true` before, and so was every
    other entry in the catalogue.
    """
    from app.adapters.usgs import UsgsAdapter

    events = _events("usgs_earthquake", UsgsAdapter, _copy("usgs/significant_month.json"))

    assert events
    assert not any(event.official for event in events)


def test_a_pager_red_earthquake_is_official() -> None:
    """The case the action item did not name, and the one that matters most.

    USGS PAGER publishes orange and red for the few earthquakes a year with
    serious expected impact. Hard-coding USGS to False would report
    `official: false` for a destructive earthquake with an active PAGER red -
    wrong at the only moment the field is load-bearing, and contrary to the
    definition agreed in #32.

    If the intent really was "USGS never", this is the test that should fail.
    """
    from app.adapters.usgs import UsgsAdapter

    payload = _copy("usgs/significant_month.json")
    payload["features"][0]["properties"]["alert"] = "red"

    events = _events("usgs_earthquake", UsgsAdapter, payload)

    official = [event for event in events if event.official]
    assert len(official) == 1
    assert official[0].alert_level == "red"


def test_a_pager_green_earthquake_is_not_official() -> None:
    from app.adapters.usgs import UsgsAdapter

    payload = _copy("usgs/significant_month.json")
    for feature in payload["features"]:
        feature["properties"]["alert"] = "green"

    events = _events("usgs_earthquake", UsgsAdapter, payload)

    assert events
    assert not any(event.official for event in events)


# ------------------------------------------------------------------- EONET


def test_no_eonet_event_is_official() -> None:
    """EONET curates and tracks; it issues no warnings, so nothing from it can
    have had one issued."""
    from app.adapters.eonet import EonetAdapter

    events = _events("nasa_eonet", EonetAdapter, _copy("eonet/events.json"))

    assert events
    assert not any(event.official for event in events)


# ------------------------------------------------------- the property itself


def test_official_is_not_the_same_value_on_every_record() -> None:
    """The one-line check that would have caught the original problem.

    A field that never varies is not a measurement, and a consumer filtering on
    it gets either everything or nothing.
    """
    from app.adapters.gdacs import GdacsAdapter

    payload = _copy("gdacs/eventlist_eq.json")
    for index, feature in enumerate(payload["features"]):
        feature["properties"]["alertlevel"] = "Red" if index % 2 == 0 else "Green"

    events = _events("gdacs", GdacsAdapter, payload)

    assert len(events) > 1
    assert len({event.official for event in events}) == 2


def test_official_never_implies_a_severity() -> None:
    """`official` says a warning exists. It does not say how bad the thing is -
    that is still module 06/07's call, and severity stays UNKNOWN.
    """
    from app.adapters.gdacs import GdacsAdapter
    from app.domain.enums import Severity

    payload = _copy("gdacs/eventlist_eq.json")
    for feature in payload["features"]:
        feature["properties"]["alertlevel"] = "Red"

    events = _events("gdacs", GdacsAdapter, payload)

    assert all(event.official for event in events)
    assert all(event.severity is Severity.UNKNOWN for event in events)
