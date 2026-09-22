from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmergencyContactModel


class ContactsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_contacts(
        self,
        country_code: str,
        subdivision: str | None = None,
        service_type: str | None = None,
        status: str = "VERIFIED",
    ) -> list[EmergencyContactModel]:
        now = datetime.now(UTC)
        query = select(EmergencyContactModel).where(
            EmergencyContactModel.country_code == country_code.upper(),
            EmergencyContactModel.status == status,
            EmergencyContactModel.effective_at <= now,
        )
        if subdivision:
            query = query.where(
                (EmergencyContactModel.subdivision == subdivision)
                | (EmergencyContactModel.subdivision.is_(None))
            )
        if service_type:
            query = query.where(EmergencyContactModel.service_type == service_type)

        res = await self.session.execute(query)
        return list(res.scalars().all())
