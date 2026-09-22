from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ContactStatus = Literal["VERIFIED", "EXPIRED", "UNVERIFIED", "SUSPENDED"]


class EmergencyContactEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    country_code: str = Field(..., min_length=2, max_length=2)
    subdivision: str | None = None
    service_type: str
    label_i18n: dict[str, str] = Field(default_factory=dict)
    phone: str
    sms: str | None = None
    website: str | None = None
    availability: str = "24/7"
    source_url: str
    authority: str = "OFFICIAL"
    effective_at: datetime
    verified_at: datetime
    review_due_at: datetime | None = None
    reviewer: str = "system"
    checksum: str = ""
    status: ContactStatus = "VERIFIED"

    def is_valid_and_current(self, now: datetime | None = None) -> bool:
        if self.status != "VERIFIED":
            return False
        current_time = now or datetime.now(UTC)
        if self.effective_at > current_time:
            return False
        return not (self.review_due_at and self.review_due_at < current_time)

    def get_localized_label(self, locale: str = "th-TH") -> str:
        # Match exact locale, then language prefix, then fallback to English or first label
        if locale in self.label_i18n:
            return self.label_i18n[locale]
        lang = locale.split("-")[0]
        for k, v in self.label_i18n.items():
            if k.startswith(lang):
                return v
        if "en-US" in self.label_i18n:
            return self.label_i18n["en-US"]
        if "en" in self.label_i18n:
            return self.label_i18n["en"]
        if self.label_i18n:
            return next(iter(self.label_i18n.values()))
        return self.service_type.replace("_", " ").title()


def normalize_phone_number(raw_phone: str, country_code: str = "TH") -> str:
    """Normalizes phone string for dialing while preserving national short codes."""
    cleaned = re.sub(r"[^\d+]", "", raw_phone.strip())
    # Short emergency numbers (2 to 4 digits) should be preserved as-is
    if len(cleaned) <= 4:
        return cleaned
    return raw_phone.strip()
