"""Domain errors."""


class SnapshotConflictError(ValueError):
    """The same idempotency key was used for differing immutable content."""


class SnapshotNotFoundError(LookupError):
    """A referenced snapshot does not exist."""
