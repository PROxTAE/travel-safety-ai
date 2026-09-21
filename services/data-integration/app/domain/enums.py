"""Storage lifecycle enums."""

from enum import StrEnum


class QuarantineStatus(StrEnum):
    OPEN = "OPEN"
    REVIEWED = "REVIEWED"
    DISCARDED = "DISCARDED"
