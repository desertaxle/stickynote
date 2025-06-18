from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import ExpiredMemoError, MemoStorage, MissingMemoError


class MemoryStorage(MemoStorage):
    """
    In-memory storage for storing and retrieving memoized results.
    """

    def __init__(self):
        self.cache: dict[str, str] = {}
        self.metadata: dict[str, datetime] = {}  # Separate metadata storage

    def _is_valid(
        self, key: str, max_age: timedelta | None, since: datetime | None
    ) -> bool:
        """Check if a key is valid according to expiration rules."""
        if key not in self.metadata:
            return True  # Backward compatibility for records without metadata

        created_at = self.metadata[key]
        now = datetime.now(timezone.utc)

        # Check if too old
        if max_age and (now - created_at) > max_age:
            return False

        # Check if created before cutoff
        if since and created_at < since:
            return False

        return True

    def exists(
        self, key: str, max_age: timedelta | None = None, since: datetime | None = None
    ) -> bool:
        """
        Check if a key exists in the cache and is valid according to expiration rules.
        """
        return key in self.cache and self._is_valid(key, max_age, since)

    async def exists_async(
        self, key: str, max_age: timedelta | None = None, since: datetime | None = None
    ) -> bool:
        """
        Check if a key exists in the cache and is valid according to expiration rules.
        """
        return key in self.cache and self._is_valid(key, max_age, since)

    def get(
        self, key: str, max_age: timedelta | None = None, since: datetime | None = None
    ) -> str:
        """
        Get the value of a key from the cache if it exists and is valid.
        """
        if key not in self.cache:
            raise MissingMemoError(f"Memo for key {key} not found in memory cache")

        if not self._is_valid(key, max_age, since):
            raise ExpiredMemoError(
                f"Memo for key {key} was created outside the requested time window"
            )

        return self.cache[key]

    async def get_async(
        self, key: str, max_age: timedelta | None = None, since: datetime | None = None
    ) -> str:
        """
        Get the value of a key from the cache if it exists and is valid.
        """
        if key not in self.cache:
            raise MissingMemoError(f"Memo for key {key} not found in memory cache")

        if not self._is_valid(key, max_age, since):
            raise ExpiredMemoError(
                f"Memo for key {key} was created outside the requested time window"
            )

        return self.cache[key]

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in the cache with current timestamp.
        """
        self.cache[key] = value
        self.metadata[key] = datetime.now(timezone.utc)

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in the cache with current timestamp.
        """
        self.cache[key] = value
        self.metadata[key] = datetime.now(timezone.utc)
