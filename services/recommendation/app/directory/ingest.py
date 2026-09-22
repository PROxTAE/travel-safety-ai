from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory.validate import validate_sources_manifest
from app.models import EmergencyContactModel


async def ingest_emergency_directory(
    session: AsyncSession,
    manifest_path: str | Path,
) -> int:
    """Ingests verified emergency directory manifest entries into the PostgreSQL database."""
    entries = validate_sources_manifest(manifest_path)
    count = 0

    for entry in entries:
        # Check if existing entry exists for country_code + subdivision + service_type
        query = select(EmergencyContactModel).where(
            EmergencyContactModel.country_code == entry.country_code,
            EmergencyContactModel.subdivision == entry.subdivision,
            EmergencyContactModel.service_type == entry.service_type,
        )
        res = await session.execute(query)
        existing = res.scalar_one_or_none()

        if existing is None:
            db_entry = EmergencyContactModel(
                id=uuid.UUID(entry.contact_id) if entry.contact_id else uuid.uuid4(),
                country_code=entry.country_code,
                subdivision=entry.subdivision,
                service_type=entry.service_type,
                label_i18n=entry.label_i18n,
                phone=entry.phone,
                source_url=entry.source_url,
                authority=entry.authority,
                effective_at=entry.effective_at,
                verified_at=entry.verified_at,
                review_due_at=entry.review_due_at,
                reviewer=entry.reviewer,
                checksum=entry.checksum,
                status=entry.status,
            )
            session.add(db_entry)
            count += 1
        else:
            # Update fields
            existing.label_i18n = entry.label_i18n
            existing.phone = entry.phone
            existing.source_url = entry.source_url
            existing.authority = entry.authority
            existing.effective_at = entry.effective_at
            existing.verified_at = entry.verified_at
            existing.review_due_at = entry.review_due_at
            existing.reviewer = entry.reviewer
            existing.checksum = entry.checksum
            existing.status = entry.status
            count += 1

    await session.commit()
    return count
