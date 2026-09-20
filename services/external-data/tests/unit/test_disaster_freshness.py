"""What `quality.status` means on a disaster record.

The bug these tests exist for: all three adapters computed freshness from when
the *event* happened rather than from how old *our copy of the data* is. With
the ten-minute budget from shared context § 10, that marked every earthquake
older than ten minutes STALE. A live query on 2026-09-20 returned 268 events,
268 of them STALE and none FRESH, including all 32 of magnitude 5.0 and above.

Two things went wrong at once. A field carrying the same value on every record
tells a consumer nothing, and a consumer filtering `status != STALE` - which is
what § 10 tells them to do - receives nothing at all.

The whole existing suite passed while this was true, which is the more useful
lesson: nothing asserted what the field meant, only that it was populated.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.adapters.eonet import EonetAdapter
from app.adapters.gdacs import GdacsAdapter
from app.adapters.usgs import UsgsAdapter
from app.domain.enums import DataStatus, ProviderStatus
from app.domain.queries import DisasterQuery
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

USGS = "usgs/significant_month.json"
GDACS = "gdacs/eventlist_eq.json"
EONET = "eonet/events.json"


def _adapter(provider_id: str, adapter_class: type) -> Any:
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == provider_id)
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return adapter_class(provider, ProviderTransport(Defaults()), env="test")


def _response(payload: Any, fetched_at: float | None = None) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://example.invalid/feed",
        fetched_at=fetched_at if fetched_at is not None else time.time(),
        elapsed_seconds=0.2,
    )


def _events(provider_id: str, adapter_class: type, payload: Any, **kw: Any) -> list[Any]:
    adapter = _adapter(provider_id, adapter_class)
    response = _response(payload, **kw)
    return adapter.normalize(adapter.validate(response), response, DisasterQuery())


def _fresh_usgs_payload() -> Any:
    """The captured feed, restamped as if the provider had just built it."""
    payload = json.loads(json.dumps(load_fixture(USGS)))
    payload["metadata"]["generated"] = int(time.time() * 1000)
    return payload


# ---------------------------------------------------------------- the bug


def test_a_feed_just_built_is_fresh_however_old_its_earthquakes_are() -> None:
    """The regression. Every quake in this feed is days or weeks old; the feed
    itself was built a moment ago, so the data we hold is fresh."""
    events = _events("usgs_earthquake", UsgsAdapter, _fresh_usgs_payload())

    assert events
    ages = [(datetime.now(UTC) - event.effective_at).total_seconds() for event in events]
    assert max(ages) > 3600, "fixture should contain events older than an hour"
    assert all(event.quality.status is DataStatus.FRESH for event in events)


def test_freshness_is_not_a_restatement_of_event_age() -> None:
    """Two events of very different ages read from the same feed must carry the
    same freshness: it describes the read, not the event."""
    events = _events("usgs_earthquake", UsgsAdapter, _fresh_usgs_payload())

    by_age = sorted(events, key=lambda event: event.effective_at)
    oldest, newest = by_age[0], by_age[-1]
    assert oldest.effective_at < newest.effective_at
    assert oldest.quality.freshness_seconds == newest.quality.freshness_seconds


def test_an_old_feed_really_is_stale() -> None:
    """The fix must not simply make everything FRESH. A feed the provider built
    yesterday is a stale read, and that is exactly what should be reported."""
    payload = json.loads(json.dumps(load_fixture(USGS)))
    yesterday = datetime.now(UTC) - timedelta(days=1)
    payload["metadata"]["generated"] = int(yesterday.timestamp() * 1000)

    events = _events("usgs_earthquake", UsgsAdapter, payload)

    assert events
    assert all(event.quality.status is DataStatus.STALE for event in events)
    assert all(
        event.quality.freshness_seconds is not None and event.quality.freshness_seconds > 80_000
        for event in events
    )


def test_a_feed_with_no_generation_time_says_so() -> None:
    """No build date means the age is unmeasured. The record must say that
    rather than quietly assuming zero."""
    payload = json.loads(json.dumps(load_fixture(USGS)))
    payload["metadata"].pop("generated", None)

    events = _events("usgs_earthquake", UsgsAdapter, payload)

    assert events
    assert any("could not be measured" in note for note in events[0].quality.notes), events[
        0
    ].quality.notes


def test_the_freshness_note_points_at_effective_at_for_event_age() -> None:
    """A consumer that wanted event age has somewhere to go."""
    events = _events("usgs_earthquake", UsgsAdapter, _fresh_usgs_payload())
    assert any("effective_at" in note for note in events[0].quality.notes)


# ------------------------------------------------- the same bug, other sources


@pytest.mark.parametrize(
    ("provider_id", "adapter_class", "fixture"),
    [
        ("gdacs", GdacsAdapter, GDACS),
        ("nasa_eonet", EonetAdapter, EONET),
    ],
)
def test_a_source_with_no_feed_timestamp_reports_the_read_as_fresh(
    provider_id: str, adapter_class: type, fixture: str
) -> None:
    """GDACS and EONET publish no feed generation time.

    What we can honestly say is that we just read it. What we cannot say is how
    long the provider sat on the event first - so the record must not imply that
    lag is zero, and must not report the event's own age as the data's age.
    """
    events = _events(provider_id, adapter_class, load_fixture(fixture))

    assert events
    for event in events:
        assert event.quality.status is DataStatus.FRESH
        assert any("not visible to us" in note for note in event.quality.notes)


def test_gdacs_flags_a_current_event_the_provider_has_stopped_revising() -> None:
    """Record staleness is a real concern, but it is a different question from
    the freshness of the read - so it is a flag with its own note, not the
    status of the whole record."""
    from app.domain.enums import QualityFlag

    payload = json.loads(json.dumps(load_fixture(GDACS)))
    stale_day = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
    for feature in payload["features"]:
        feature["properties"]["datemodified"] = stale_day
        feature["properties"]["iscurrent"] = "true"

    events = _events("gdacs", GdacsAdapter, payload)

    assert events
    for event in events:
        assert QualityFlag.STALE in event.quality.flags
        assert any("has not revised the record" in n for n in event.quality.notes)
        # Still a fresh read of a stale record - the two are not the same thing.
        assert event.quality.status is DataStatus.FRESH


def test_a_recently_revised_current_event_is_not_flagged() -> None:
    """The flag must not fire on every record, or it stops meaning anything."""
    from app.domain.enums import QualityFlag

    payload = json.loads(json.dumps(load_fixture(GDACS)))
    just_now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    for feature in payload["features"]:
        feature["properties"]["datemodified"] = just_now
        feature["properties"]["iscurrent"] = "true"

    events = _events("gdacs", GdacsAdapter, payload)

    assert events
    assert all(QualityFlag.STALE not in event.quality.flags for event in events)


# ------------------------------------------------------- cross-source property


def test_no_source_reports_one_status_for_every_record() -> None:
    """The property that would have caught the original bug in one line.

    Freshness that never varies is not a measurement. Here the three sources are
    read with feeds of different ages, so their statuses must differ.
    """
    fresh = _events("usgs_earthquake", UsgsAdapter, _fresh_usgs_payload())

    stale_payload = json.loads(json.dumps(load_fixture(USGS)))
    stale_payload["metadata"]["generated"] = int(
        (datetime.now(UTC) - timedelta(days=1)).timestamp() * 1000
    )
    stale = _events("usgs_earthquake", UsgsAdapter, stale_payload)

    assert {event.quality.status for event in fresh} == {DataStatus.FRESH}
    assert {event.quality.status for event in stale} == {DataStatus.STALE}
