"""Unit tests for historical data ingestion."""

import re
from pathlib import Path

import respx

from training.ingest import (
    OPEN_METEO_ARCHIVE_URL,
    USGS_API_URL,
    HistoricalDataIngester,
    compute_query_checksum,
)


def test_compute_query_checksum_format() -> None:
    params = {"format": "geojson", "minmagnitude": "4.5", "starttime": "2024-01-01"}
    checksum = compute_query_checksum("https://example.com/api", params)
    assert checksum.startswith("sha256:")
    assert re.match(r"^sha256:[0-9a-f]{64}$", checksum)


def test_real_corridors_loaded(tmp_path: Path) -> None:
    ingester = HistoricalDataIngester(raw_dir=tmp_path / "raw")
    corridors = ingester.get_corridors()
    assert len(corridors) >= 4
    groups = {c["geography_group"] for c in corridors}
    assert len(groups) >= 2
    for c in corridors:
        assert c["distance_m"] > 0
        assert c["duration_seconds"] > 0
        assert len(c["waypoints"]) >= 2
        for wp in c["waypoints"]:
            assert len(wp) == 2
            assert 90.0 <= wp[0] <= 110.0  # Lon
            assert 5.0 <= wp[1] <= 25.0  # Lat


@respx.mock
def test_fetch_usgs_earthquakes(tmp_path: Path) -> None:
    respx.get(USGS_API_URL).respond(
        status_code=200,
        json={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "usp000test",
                    "properties": {"mag": 4.5, "place": "Northern Thailand", "time": 1715000000000},
                    "geometry": {"type": "Point", "coordinates": [99.5, 18.5, 10.0]},
                }
            ],
        },
    )

    ingester = HistoricalDataIngester(raw_dir=tmp_path)
    meta, events = ingester.fetch_usgs_earthquakes()
    assert meta.authority == "OFFICIAL"
    assert "USGS" in meta.name
    assert meta.query_checksum.startswith("sha256:")
    assert len(events) == 1
    assert events[0]["properties"]["mag"] == 4.5


@respx.mock
def test_fetch_open_meteo_archive(tmp_path: Path) -> None:
    respx.get(OPEN_METEO_ARCHIVE_URL).respond(
        status_code=200,
        json={
            "latitude": 13.75,
            "longitude": 100.5,
            "hourly": {
                "time": ["2024-05-01T00:00", "2024-05-01T01:00"],
                "temperature_2m": [30.5, 30.2],
                "relative_humidity_2m": [70, 72],
                "precipitation": [0.0, 5.2],
                "weather_code": [0, 61],
                "wind_gusts_10m": [15.0, 35.0],
            },
        },
    )

    ingester = HistoricalDataIngester(raw_dir=tmp_path)
    meta, payload = ingester.fetch_open_meteo_archive(
        latitude=13.75,
        longitude=100.5,
        start_date="2024-05-01",
        end_date="2024-05-02",
    )
    assert meta.authority == "LICENSED_PROVIDER"
    assert "Open-Meteo" in meta.name
    assert "hourly" in payload
    assert len(payload["hourly"]["time"]) == 2
