from __future__ import annotations

from datetime import datetime, timezone
from typing import TypedDict

from .base import ExpiredMemoError, MemoStorage, MissingMemoError


class MemoRecordMetadata(TypedDict):
    created_at: datetime


class MemoryStorage(MemoStorage):
    """
    In-memory storage for storing and retrieving memoized results.
    """

    def __init__(self):
        self.cache: dict[str, str] = {}
        self.metadata: dict[str, MemoRecordMetadata] = {}

    def _is_valid(self, key: str, created_after: datetime | None) -> bool:
        """
        Check if a key is valid according to expiration rules.

        Args:
            key: The key to check
            created_after: Only consider records created at or after this datetime
        """
        created_at = self.metadata[key]["created_at"]

        # Check if created before cutoff
        if created_after and created_at < created_after:
            return False

        return True

    def exists(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the cache and is valid according to expiration rules.

        Args:
            key: The key to check
            created_after: Only consider records created at or after this datetime
        """
        return key in self.cache and self._is_valid(key, created_after)

    async def exists_async(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the cache and is valid according to expiration rules.

        Args:
            key: The key to check
            created_after: Only consider records created at or after this datetime
        """
        return key in self.cache and self._is_valid(key, created_after)

    def get(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the cache if it exists and is valid.

        Args:
            key: The key to get the value for
            created_after: Only consider records created at or after this datetime
        """
        if key not in self.cache:
            raise MissingMemoError(f"Memo for key {key} not found in memory cache")

        if not self._is_valid(key, created_after):
            raise ExpiredMemoError(
                f"Memo for key {key} was created outside the requested time window"
            )

        return self.cache[key]

    async def get_async(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the cache if it exists and is valid.

        Args:
            key: The key to get the value for
            created_after: Only consider records created at or after this datetime
        """
        if key not in self.cache:
            raise MissingMemoError(f"Memo for key {key} not found in memory cache")

        if not self._is_valid(key, created_after):
            raise ExpiredMemoError(
                f"Memo for key {key} was created outside the requested time window"
            )

        return self.cache[key]

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in the cache with current timestamp.

        Args:
            key: The key to set the value for
            value: The value to set
        """
        self.cache[key] = value
        self.metadata[key] = {"created_at": datetime.now(timezone.utc)}

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in the cache with current timestamp.

        Args:
            key: The key to set the value for
            value: The value to set
        """
        self.cache[key] = value
        self.metadata[key] = {"created_at": datetime.now(timezone.utc)}
