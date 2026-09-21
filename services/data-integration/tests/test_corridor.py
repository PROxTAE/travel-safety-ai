"""Route tests use captured ORS and Open-Meteo coordinates from module 04.

ORS Bangkok-Ayutthaya HTTP 200 capture: 2026-09-20T07:50:14Z.
Open-Meteo Fiji pair HTTP 200 capture: 2026-09-20T14:43:47Z.
The test route between Fiji points is a derived geometry, never served at runtime.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.canonical import GeoLineString
from app.pipeline.corridor import geodesic_distance_m, sample_route, split_dateline


def test_ors_route_samples_have_bounded_spacing_and_eta() -> None:
    line = GeoLineString(
        type="LineString",
        coordinates=[
            (100.538733, 13.764725),
            (100.538688, 13.76462),
        ],
    )
    departure = datetime(2026, 9, 20, 7, 50, 14, tzinfo=UTC)
    samples = sample_route(line, departure_at=departure, duration_seconds=64.9, max_spacing_m=5)
    assert len(samples) >= 3
    assert samples[0].eta == departure
    assert samples[-1].eta == departure + timedelta(seconds=64.9)
    assert all(
        geodesic_distance_m((left.longitude, left.latitude), (right.longitude, right.latitude))
        <= 5.01
        for left, right in zip(samples, samples[1:], strict=False)
    )


def test_fiji_dateline_route_splits_into_short_planar_parts() -> None:
    line = GeoLineString(
        type="LineString",
        coordinates=[
            (179.57103, -16.55536),
            (-179.82872, -16.414762),
        ],
    )
    samples = sample_route(
        line,
        departure_at=datetime(2026, 9, 20, 20, tzinfo=UTC),
        duration_seconds=3600,
        max_spacing_m=5000,
    )
    assert samples[-1].distance_m < 100_000
    parts = split_dateline(samples)
    assert len(parts) == 2
    assert parts[0][-1][0] == 180
    assert parts[1][0][0] == -180
    assert all(
        abs(right[0] - left[0]) < 180
        for part in parts
        for left, right in zip(part, part[1:], strict=False)
    )


def test_corridor_rejects_ambiguous_or_invalid_parameters() -> None:
    line = GeoLineString(
        type="LineString",
        coordinates=[
            (179.57103, -16.55536),
            (-179.82872, -16.414762),
        ],
    )
    with pytest.raises(ValueError):
        sample_route(
            line, departure_at=datetime(2026, 9, 20, 20), duration_seconds=3600, max_spacing_m=1000
        )
    with pytest.raises(ValueError):
        sample_route(
            line,
            departure_at=datetime(2026, 9, 20, 20, tzinfo=UTC),
            duration_seconds=3600,
            max_spacing_m=0,
        )
