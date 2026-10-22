"""Provider-independent byte storage contract used by application messaging."""

# works like an interface

from typing import Protocol


class StorageError(Exception):
    """A storage operation failed; provider-specific details are chained as the cause."""

    def __init__(self, message, *, code="storage", retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class StorageProvider(Protocol):
    """Paths are absolute, slash-separated file paths; list_files lists direct children."""

    def put(self, path: str, data: bytes, *, overwrite: bool = False) -> None:
        """Store bytes, rejecting an existing destination unless overwrite is enabled."""
        ...

    def get(self, path: str) -> bytes:
        """Read a file's bytes."""
        ...

    def list_files(self, folder: str = "") -> list[str]:
        """Return direct child file paths; an empty folder means the storage root."""
        ...

    def delete(self, path: str) -> None:
        """Delete a file, raising StorageError if it cannot be deleted."""
        ...
