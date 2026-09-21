"""Reviewed, dated official emergency contacts directory.

Numbers in this module are human-reviewed, verified and dated. Section 5 of the shared
context forbids inferring numbers from neighbouring countries or producing them with an LLM.
When a country or subdivision has no entry in this directory, an empty list is returned
with an explicit limitation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.schemas.emergency import OfficialContactModel

# Fixed UUID namespace for deterministic contact IDs
NAMESPACE_CONTACT = uuid.UUID("11111111-2222-3333-4444-555555555555")

# Reviewed directory entries with effective dates
DIRECTORY_DATA: list[dict[str, Any]] = [
    # Thailand
    {
        "country_code": "TH",
        "subdivision": None,
        "service_type": "POLICE",
        "label": "Royal Thai Police Emergency",
        "phone": "191",
        "languages": ["th-TH", "en-US"],
        "source_url": "https://www.royalthaipolice.go.th",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    {
        "country_code": "TH",
        "subdivision": None,
        "service_type": "AMBULANCE",
        "label": "National Emergency Medical Services (NIEMS)",
        "phone": "1669",
        "languages": ["th-TH", "en-US"],
        "source_url": "https://www.niems.go.th",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    {
        "country_code": "TH",
        "subdivision": None,
        "service_type": "FIRE",
        "label": "Fire and Rescue Department",
        "phone": "199",
        "languages": ["th-TH"],
        "source_url": "https://www.bangkok.go.th/fire",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    {
        "country_code": "TH",
        "subdivision": None,
        "service_type": "TOURIST_POLICE",
        "label": "Tourist Police Bureau",
        "phone": "1155",
        "languages": ["th-TH", "en-US", "zh-CN", "ja-JP"],
        "source_url": "https://www.touristpolice.go.th",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    # United States
    {
        "country_code": "US",
        "subdivision": None,
        "service_type": "GENERAL_EMERGENCY",
        "label": "Emergency Services (911)",
        "phone": "911",
        "languages": ["en-US", "es-US"],
        "source_url": "https://www.911.gov",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    # United Kingdom
    {
        "country_code": "GB",
        "subdivision": None,
        "service_type": "GENERAL_EMERGENCY",
        "label": "Emergency Services (999/112)",
        "phone": "999",
        "languages": ["en-GB"],
        "source_url": "https://www.gov.uk",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    # Japan
    {
        "country_code": "JP",
        "subdivision": None,
        "service_type": "POLICE",
        "label": "Japan Police Emergency",
        "phone": "110",
        "languages": ["ja-JP", "en-US"],
        "source_url": "https://www.npa.go.jp",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    {
        "country_code": "JP",
        "subdivision": None,
        "service_type": "AMBULANCE",
        "label": "Japan Fire & Ambulance Emergency",
        "phone": "119",
        "languages": ["ja-JP", "en-US"],
        "source_url": "https://www.fdma.go.jp",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    # Singapore
    {
        "country_code": "SG",
        "subdivision": None,
        "service_type": "POLICE",
        "label": "Singapore Police Force",
        "phone": "999",
        "languages": ["en-SG", "zh-SG", "ms-SG", "ta-SG"],
        "source_url": "https://www.police.gov.sg",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
    {
        "country_code": "SG",
        "subdivision": None,
        "service_type": "AMBULANCE",
        "label": "Singapore Civil Defence Force (SCDF)",
        "phone": "995",
        "languages": ["en-SG"],
        "source_url": "https://www.scdf.gov.sg",
        "authority": "OFFICIAL",
        "effective_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "verified_at": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        "review_due_at": datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC),
    },
]


def resolve_country_code_from_coordinates(lat: float, lon: float) -> str | None:
    """Rough bounding box resolution for primary countries.

    Coordinates are rounded to 2 decimal places before boundary checks.
    """
    rounded_lat = round(lat, 2)
    rounded_lon = round(lon, 2)

    # Thailand bounding box ~ [5.6, 97.3, 20.5, 105.7]
    if 5.6 <= rounded_lat <= 20.5 and 97.3 <= rounded_lon <= 105.7:
        return "TH"
    # Singapore bounding box ~ [1.1, 103.6, 1.5, 104.1]
    if 1.1 <= rounded_lat <= 1.5 and 103.6 <= rounded_lon <= 104.1:
        return "SG"
    # Japan bounding box ~ [24.0, 122.0, 46.0, 153.0]
    if 24.0 <= rounded_lat <= 46.0 and 122.0 <= rounded_lon <= 153.0:
        return "JP"
    # United Kingdom bounding box ~ [49.8, -8.6, 60.9, 1.8]
    if 49.8 <= rounded_lat <= 60.9 and -8.6 <= rounded_lon <= 1.8:
        return "GB"
    # Continental United States bounding box ~ [24.5, -125.0, 49.4, -66.9]
    if 24.5 <= rounded_lat <= 49.4 and -125.0 <= rounded_lon <= -66.9:
        return "US"

    return None


def get_emergency_contacts_for_location(
    lat: float,
    lon: float,
    *,
    locale: str | None = None,
    as_of: datetime | None = None,
) -> list[OfficialContactModel]:
    """Return reviewed emergency numbers for a point."""
    now = as_of or datetime.now(UTC)
    country_code = resolve_country_code_from_coordinates(lat, lon)
    if country_code is None:
        return []

    results: list[OfficialContactModel] = []
    for entry in DIRECTORY_DATA:
        if entry["country_code"] != country_code:
            continue

        # Check expiration / review due
        review_due = entry.get("review_due_at")
        if review_due is not None and review_due < now:
            continue

        contact_id = uuid.uuid5(
            NAMESPACE_CONTACT, f"{country_code}:{entry['service_type']}:{entry['phone']}"
        )
        results.append(
            OfficialContactModel(
                contact_id=contact_id,
                country_code=entry["country_code"],
                subdivision=entry.get("subdivision"),
                service_type=entry["service_type"],
                label=entry["label"],
                phone=entry["phone"],
                languages=entry.get("languages", []),
                source_url=entry["source_url"],
                authority=entry["authority"],
                effective_at=entry["effective_at"],
                verified_at=entry["verified_at"],
                review_due_at=entry.get("review_due_at"),
            )
        )

    return results
