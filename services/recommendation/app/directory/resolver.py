from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory.validate import validate_sources_manifest
from app.domain.contacts import EmergencyContactEntry, normalize_phone_number
from app.domain.recommendation import OfficialContact
from app.models import EmergencyContactModel
from app.settings import get_settings

logger = structlog.get_logger()


async def resolve_emergency_contacts(
    country_code: str,
    subdivision: str | None = None,
    service_type: str | None = None,
    locale: str = "th-TH",
    session: AsyncSession | None = None,
    sources_manifest_path: str | Path | None = None,
    now: datetime | None = None,
) -> list[OfficialContact]:
    """Resolves verified official emergency contacts for a location.

    Guarantees:
    - Never generates or estimates contacts via LLM.
    - Expired records (past review_due_at) or unverified records are withheld.
    - If country is unknown or has no verified coverage, returns an empty list.
    """
    country_code = country_code.upper().strip()
    current_time = now or datetime.now(UTC)
    results: list[OfficialContact] = []

    if session is not None:
        try:
            query = select(EmergencyContactModel).where(
                EmergencyContactModel.country_code == country_code,
                EmergencyContactModel.status == "VERIFIED",
                EmergencyContactModel.effective_at <= current_time,
            )
            if subdivision:
                query = query.where(
                    (EmergencyContactModel.subdivision == subdivision)
                    | (EmergencyContactModel.subdivision.is_(None))
                )
            if service_type:
                query = query.where(EmergencyContactModel.service_type == service_type)

            db_res = await session.execute(query)
            db_entries = db_res.scalars().all()

            for row in db_entries:
                if row.review_due_at and row.review_due_at < current_time:
                    # Withhold expired contacts
                    continue

                entry = EmergencyContactEntry(
                    contact_id=str(row.id),
                    country_code=row.country_code,
                    subdivision=row.subdivision,
                    service_type=row.service_type,
                    label_i18n=row.label_i18n,
                    phone=row.phone,
                    source_url=row.source_url,
                    authority=row.authority,
                    effective_at=row.effective_at,
                    verified_at=row.verified_at,
                    review_due_at=row.review_due_at,
                    reviewer=row.reviewer,
                    checksum=row.checksum,
                    status=cast(Any, row.status),
                )

                results.append(
                    OfficialContact(
                        contact_id=entry.contact_id,
                        country_code=entry.country_code,
                        subdivision=entry.subdivision,
                        service_type=entry.service_type,
                        label=entry.get_localized_label(locale),
                        phone=normalize_phone_number(entry.phone, entry.country_code),
                        languages=["th-TH", "en-US"] if entry.country_code == "TH" else ["en-US"],
                        source_url=entry.source_url,
                        authority=entry.authority,
                        effective_at=entry.effective_at,
                        verified_at=entry.verified_at,
                        review_due_at=entry.review_due_at,
                    )
                )
            if results:
                return results
        except Exception as exc:
            # Fall back to manifest if database query fails
            logger.debug("Database contact lookup failed, falling back to manifest", error=str(exc))

    # Fallback / Direct Manifest Resolution
    manifest_file = sources_manifest_path or get_settings().EMERGENCY_DIRECTORY_PATH
    try:
        entries = validate_sources_manifest(manifest_file)
        for entry in entries:
            if entry.country_code != country_code:
                continue
            if not entry.is_valid_and_current(current_time):
                continue
            if subdivision and entry.subdivision and entry.subdivision != subdivision:
                continue
            if service_type and entry.service_type != service_type:
                continue

            results.append(
                OfficialContact(
                    contact_id=entry.contact_id,
                    country_code=entry.country_code,
                    subdivision=entry.subdivision,
                    service_type=entry.service_type,
                    label=entry.get_localized_label(locale),
                    phone=normalize_phone_number(entry.phone, entry.country_code),
                    languages=["th-TH", "en-US"] if entry.country_code == "TH" else ["en-US"],
                    source_url=entry.source_url,
                    authority=entry.authority,
                    effective_at=entry.effective_at,
                    verified_at=entry.verified_at,
                    review_due_at=entry.review_due_at,
                )
            )
    except Exception as exc:
        logger.debug("Manifest fallback contact lookup failed", error=str(exc))

    return results
