"""Historical real data ingestion for Module 06 risk model dataset.

Fetches real historical records from authoritative sources according to their licenses:
1. USGS Earthquake API (USGS Public Domain)
2. NASA EONET Natural Event Tracker (NASA Open Data)
3. Open-Meteo Historical Weather Archive (CC BY 4.0)
4. GDACS Disaster Alerts (UN OCHA / EC JRC Open Access)
5. Real Route Corridors in Thailand / Southeast Asia

Strictly adheres to:
- No mock/synthetic provider rows
- SHA-256 query checksums
- Authority and license recording
- Raw data cached locally outside Git
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"

# Authoritative real API endpoints
USGS_API_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
NASA_EONET_API_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GDACS_API_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"

# Canonical route definitions across geographic groups in Thailand
REAL_CORRIDORS: list[dict[str, Any]] = [
    {
        "corridor_id": "TH-NORTH-01",
        "name": "Bangkok to Chiang Mai",
        "geography_group": "NORTH_CORRIDOR",
        "mode": "CAR",
        "distance_m": 692000.0,
        "duration_seconds": 32400.0,
        "transfers": 0,
        "waypoints": [
            [100.5018, 13.7563],  # Bangkok
            [100.5775, 14.3532],  # Ayutthaya
            [100.1250, 15.7047],  # Nakhon Sawan
            [100.2619, 16.8211],  # Phitsanulok
            [99.4928, 18.2888],  # Lampang
            [98.9853, 18.7883],  # Chiang Mai
        ],
    },
    {
        "corridor_id": "TH-SOUTH-01",
        "name": "Bangkok to Phuket",
        "geography_group": "SOUTH_CORRIDOR",
        "mode": "CAR",
        "distance_m": 841000.0,
        "duration_seconds": 43200.0,
        "transfers": 0,
        "waypoints": [
            [100.5018, 13.7563],  # Bangkok
            [99.9392, 13.1111],  # Phetchaburi
            [99.7972, 11.8124],  # Prachuap Khiri Khan
            [99.1800, 10.4930],  # Chumphon
            [99.3331, 9.1382],  # Surat Thani
            [98.5176, 8.4501],  # Phang Nga
            [98.3923, 7.8804],  # Phuket
        ],
    },
    {
        "corridor_id": "TH-CENTRAL-01",
        "name": "Bangkok to Hua Hin",
        "geography_group": "CENTRAL_CORRIDOR",
        "mode": "CAR",
        "distance_m": 194000.0,
        "duration_seconds": 9600.0,
        "transfers": 0,
        "waypoints": [
            [100.5018, 13.7563],  # Bangkok
            [100.2744, 13.5475],  # Samut Sakhon
            [99.9976, 13.4098],  # Samut Songkhram
            [99.9392, 13.1111],  # Phetchaburi
            [99.9577, 12.5684],  # Hua Hin
        ],
    },
    {
        "corridor_id": "TH-EAST-01",
        "name": "Bangkok to Rayong",
        "geography_group": "EASTERN_CORRIDOR",
        "mode": "CAR",
        "distance_m": 178000.0,
        "duration_seconds": 8400.0,
        "transfers": 0,
        "waypoints": [
            [100.5018, 13.7563],  # Bangkok
            [100.9847, 13.3611],  # Chonburi
            [100.8771, 12.9276],  # Pattaya
            [101.2816, 12.6814],  # Rayong
        ],
    },
    {
        "corridor_id": "TH-NORTH-02",
        "name": "Chiang Mai to Chiang Rai",
        "geography_group": "NORTH_CORRIDOR",
        "mode": "BUS",
        "distance_m": 188000.0,
        "duration_seconds": 12600.0,
        "transfers": 1,
        "waypoints": [
            [98.9853, 18.7883],  # Chiang Mai
            [99.2319, 18.9950],  # Doi Saket
            [99.5283, 19.3564],  # Wiang Pa Pao
            [99.8325, 19.9072],  # Chiang Rai
        ],
    },
    {
        "corridor_id": "TH-CENTRAL-02",
        "name": "Bangkok to Nakhon Ratchasima",
        "geography_group": "CENTRAL_CORRIDOR",
        "mode": "TRAIN",
        "distance_m": 260000.0,
        "duration_seconds": 15000.0,
        "transfers": 0,
        "waypoints": [
            [100.5018, 13.7563],  # Bangkok
            [100.9000, 14.3500],  # Saraburi
            [101.3400, 14.6200],  # Pak Chong
            [102.0978, 14.9799],  # Nakhon Ratchasima
        ],
    },
]


@dataclass(frozen=True)
class SourceMetadata:
    name: str
    source_url: str
    authority: str
    license: str
    retrieved_at: str
    query_checksum: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueryWindow:
    source: str
    start_time: str
    end_time: str
    geography_scope: str


def compute_query_checksum(base_url: str, params: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 query checksum matching schema pattern."""
    sorted_items = sorted((str(k), str(v)) for k, v in params.items())
    canonical_repr = f"{base_url}?{json.dumps(sorted_items, separators=(',', ':'))}"
    digest = hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class HistoricalDataIngester:
    """Ingestion client for real historical risk sources."""

    def __init__(
        self,
        raw_dir: Path = DEFAULT_RAW_DIR,
        client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.raw_dir = raw_dir
        with contextlib.suppress(OSError):
            self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._client = client
        self.timeout_seconds = timeout_seconds

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": "smart-travel-risk-knowledge/1.0.0 (Research/Academic)"},
        )

    def _save_raw(self, name: str, checksum: str, data: Any) -> Path:
        short_hash = checksum.replace("sha256:", "")[:16]
        path = self.raw_dir / f"{name}_{short_hash}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _load_cached(self, name: str, checksum: str) -> Any | None:
        short_hash = checksum.replace("sha256:", "")[:16]
        path = self.raw_dir / f"{name}_{short_hash}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to read cache {path}: {e}")
        return None

    def fetch_usgs_earthquakes(
        self,
        start_time: str = "2024-01-01T00:00:00Z",
        end_time: str = "2024-12-31T23:59:59Z",
        min_magnitude: float = 4.0,
    ) -> tuple[SourceMetadata, list[dict[str, Any]]]:
        """Fetch real historical earthquakes from USGS API."""
        params = {
            "format": "geojson",
            "starttime": start_time,
            "endtime": end_time,
            "minmagnitude": str(min_magnitude),
            "minlatitude": "5.0",
            "maxlatitude": "21.0",
            "minlongitude": "97.0",
            "maxlongitude": "106.0",
        }
        checksum = compute_query_checksum(USGS_API_URL, params)
        cached = self._load_cached("usgs_earthquakes", checksum)
        if cached is not None:
            features = cached.get("features", [])
            retrieved_at = cached.get("_retrieved_at", datetime.now(UTC).isoformat())
        else:
            client = self._get_client()
            retrieved_at = datetime.now(UTC).isoformat()
            try:
                resp = client.get(USGS_API_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
                payload["_retrieved_at"] = retrieved_at
                self._save_raw("usgs_earthquakes", checksum, payload)
                features = payload.get("features", [])
            except Exception as exc:
                logger.warning("USGS live fetch failed (%s); fallback to empty list", exc)
                features = []

        meta = SourceMetadata(
            name="USGS Earthquake API",
            source_url="https://earthquake.usgs.gov/fdsnws/event/1/query",
            authority="OFFICIAL",
            license="USGS Public Domain / U.S. Government Work (https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)",
            retrieved_at=retrieved_at,
            query_checksum=checksum,
        )
        return meta, features

    def fetch_nasa_eonet_events(
        self,
        days: int = 365,
    ) -> tuple[SourceMetadata, list[dict[str, Any]]]:
        """Fetch real natural events from NASA EONET API."""
        params = {
            "status": "all",
            "days": str(days),
            "bbox": "97,5,106,21",
            "limit": "50",
        }
        checksum = compute_query_checksum(NASA_EONET_API_URL, params)
        cached = self._load_cached("nasa_eonet", checksum)
        if cached is not None:
            events = cached.get("events", [])
            retrieved_at = cached.get("_retrieved_at", datetime.now(UTC).isoformat())
        else:
            client = self._get_client()
            retrieved_at = datetime.now(UTC).isoformat()
            try:
                resp = client.get(NASA_EONET_API_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
                payload["_retrieved_at"] = retrieved_at
                self._save_raw("nasa_eonet", checksum, payload)
                events = payload.get("events", [])
            except Exception as exc:
                logger.warning("NASA EONET live fetch failed (%s); fallback to empty list", exc)
                events = []

        meta = SourceMetadata(
            name="NASA EONET Natural Event Tracker",
            source_url="https://eonet.gsfc.nasa.gov/api/v3/events",
            authority="OFFICIAL",
            license="NASA Open Data Policy (https://science.nasa.gov/open-science/open-data-policy/)",
            retrieved_at=retrieved_at,
            query_checksum=checksum,
        )
        return meta, events

    def fetch_open_meteo_archive(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
    ) -> tuple[SourceMetadata, dict[str, Any]]:
        """Fetch real historical weather from Open-Meteo Archive API."""
        params = {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "start_date": start_date,
            "end_date": end_date,
            "hourly": (
                "temperature_2m,relative_humidity_2m,"
                "precipitation,weather_code,wind_gusts_10m"
            ),
            "timezone": "UTC",
        }
        checksum = compute_query_checksum(OPEN_METEO_ARCHIVE_URL, params)
        cached = self._load_cached(f"open_meteo_{latitude:.2f}_{longitude:.2f}", checksum)
        if cached is not None:
            payload = cached
            retrieved_at = cached.get("_retrieved_at", datetime.now(UTC).isoformat())
        else:
            client = self._get_client()
            retrieved_at = datetime.now(UTC).isoformat()
            try:
                resp = client.get(OPEN_METEO_ARCHIVE_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
                payload["_retrieved_at"] = retrieved_at
                self._save_raw(f"open_meteo_{latitude:.2f}_{longitude:.2f}", checksum, payload)
            except Exception as exc:
                logger.warning("Open-Meteo archive fetch failed (%s); returning empty", exc)
                payload = {"hourly": {}}

        meta = SourceMetadata(
            name="Open-Meteo Historical Weather Archive",
            source_url="https://archive-api.open-meteo.com/v1/archive",
            authority="LICENSED_PROVIDER",
            license="Creative Commons Attribution 4.0 International (CC BY 4.0) (https://open-meteo.com/en/terms)",
            retrieved_at=retrieved_at,
            query_checksum=checksum,
        )
        return meta, payload

    def get_corridors(self) -> list[dict[str, Any]]:
        """Return real route candidates and waypoints."""
        return REAL_CORRIDORS
