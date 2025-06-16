from __future__ import annotations

from .base import MemoStorage, MissingMemoError


class MemoryStorage(MemoStorage):
    """
    In-memory storage for storing and retrieving memoized results.
    """

    def __init__(self):
        self.cache: dict[str, str] = {}

    def exists(self, key: str) -> bool:
        """
        Check if a key exists in the cache.
        """
        return key in self.cache

    async def exists_async(self, key: str) -> bool:
        """
        Check if a key exists in the cache.
        """
        return key in self.cache

    def get(self, key: str) -> str:
        """
        Get the value of a key from the cache.
        """
        value = self.cache.get(key)
        if value is None:
            raise MissingMemoError(f"Memo for key {key} not found in memory cache")
        return value

    async def get_async(self, key: str) -> str:
        """
        Get the value of a key from the cache.
        """
        value = self.cache.get(key)
        if value is None:
            raise MissingMemoError(f"Memo for key {key} not found in memory cache")
        return value

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in the cache.
        """
        self.cache[key] = value

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in the cache.
        """
        self.cache[key] = value