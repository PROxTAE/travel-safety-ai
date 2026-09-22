from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory.ingest import ingest_emergency_directory
from app.directory.resolver import resolve_emergency_contacts
from app.directory.validate import validate_sources_manifest
from app.domain.contacts import normalize_phone_number


def test_validate_sources_manifest() -> None:
    manifest_path = Path(__file__).resolve().parent.parent / "emergency-directory" / "sources.yaml"
    entries = validate_sources_manifest(manifest_path)
    assert len(entries) >= 4
    service_types = {e.service_type for e in entries}
    assert "POLICE" in service_types
    assert "AMBULANCE" in service_types
    assert "FIRE" in service_types
    assert "TOURIST_POLICE" in service_types


@pytest.mark.asyncio
async def test_resolve_thailand_contacts(test_db_session: AsyncSession) -> None:
    manifest_path = Path(__file__).resolve().parent.parent / "emergency-directory" / "sources.yaml"
    await ingest_emergency_directory(test_db_session, manifest_path)

    contacts = await resolve_emergency_contacts(
        country_code="TH",
        locale="th-TH",
        session=test_db_session,
    )

    assert len(contacts) >= 4
    phones = {c.phone for c in contacts}
    assert "191" in phones
    assert "1669" in phones
    assert "1155" in phones
    assert "199" in phones

    police = next(c for c in contacts if c.service_type == "POLICE")
    assert police.country_code == "TH"
    assert police.authority == "OFFICIAL"
    assert police.effective_at is not None
    assert police.verified_at is not None


@pytest.mark.asyncio
async def test_resolve_unknown_country_returns_empty_list(test_db_session: AsyncSession) -> None:
    contacts = await resolve_emergency_contacts(
        country_code="ZZ",
        session=test_db_session,
    )
    assert contacts == []


@pytest.mark.asyncio
async def test_expired_contacts_withheld(test_db_session: AsyncSession) -> None:
    # Create temporary manifest with expired review date
    now = datetime.now(UTC)
    expired_date = now - timedelta(days=10)

    temp_manifest = {
        "version": "1.0.0",
        "entries": [
            {
                "country_code": "TH",
                "subdivision": None,
                "service_type": "POLICE",
                "label_i18n": {"th-TH": "ตำรวจ"},
                "phone": "191",
                "source_url": "https://police.go.th",
                "authority": "OFFICIAL",
                "effective_at": (now - timedelta(days=365)).isoformat(),
                "verified_at": (now - timedelta(days=180)).isoformat(),
                "review_due_at": expired_date.isoformat(),
                "reviewer": "test",
                "status": "VERIFIED",
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        yaml.safe_dump(temp_manifest, tf)
        temp_path = tf.name

    try:
        contacts = await resolve_emergency_contacts(
            country_code="TH",
            sources_manifest_path=temp_path,
            now=now,
        )
        # Expired contact should be withheld
        assert contacts == []
    finally:
        Path(temp_path).unlink(missing_ok=True)


def test_phone_normalization() -> None:
    assert normalize_phone_number("191", "TH") == "191"
    assert normalize_phone_number("1669", "TH") == "1669"
    assert normalize_phone_number(" 1155 ", "TH") == "1155"
    assert normalize_phone_number("+66 2 123 4567", "TH") == "+66 2 123 4567"
