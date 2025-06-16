from __future__ import annotations

from typing import Protocol


class MissingMemoError(Exception):
    """
    Exception raised when a memoized result is not found in the storage backend.
    """


class MemoStorage(Protocol):
    """
    Protocol for a storage backend to store and retrieve memoized results.
    """

    def exists(self, key: str) -> bool:
        """
        Check if a key exists in the backend.
        """
        ...  # pragma: no cover

    async def exists_async(self, key: str) -> bool:
        """
        Check if a key exists in the backend.
        """
        ...  # pragma: no cover

    def get(self, key: str) -> str:
        """
        Get the value of a key from the backend.
        """
        ...  # pragma: no cover

    async def get_async(self, key: str) -> str:
        """
        Get the value of a key from the backend.
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