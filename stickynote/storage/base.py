from __future__ import annotations

from datetime import datetime
from typing import Protocol


class MissingMemoError(Exception):
    """
    Exception raised when a memoized result is not found in the storage backend.
    """


class ExpiredMemoError(MissingMemoError):
    """
    Exception raised when a memoized result is found but falls outside the requested time window.
    """


class MemoStorage(Protocol):
    """
    Protocol for a storage backend to store and retrieve memoized results.
    """

    def exists(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the backend and is valid according to expiration rules.

        Args:
            key: The key to check
            created_after: Only consider records created at or after this datetime
        """
        ...  # pragma: no cover

    async def exists_async(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the backend and is valid according to expiration rules.

        Args:
            key: The key to check
            created_after: Only consider records created at or after this datetime
        """
        ...  # pragma: no cover

    def get(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the backend if it exists and is valid.

        Args:
            key: The key to retrieve
            created_after: Only consider records created at or after this datetime

        Raises:
            MissingMemoError: If the key doesn't exist or is expired
        """
        ...  # pragma: no cover

    async def get_async(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the backend if it exists and is valid.

        Args:
            key: The key to retrieve
            created_after: Only consider records created at or after this datetime

        Raises:
            MissingMemoError: If the key doesn't exist or is expired
        """
        ...  # pragma: no cover

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in the backend.
        """
        ...  # pragma: no cover

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in the backend.
        """
        ...  # pragma: no cover
