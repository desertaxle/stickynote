from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol


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

    def get(self, key: str) -> str | None:
        """
        Get the value of a key from the backend.
        """
        ...  # pragma: no cover

    async def get_async(self, key: str) -> str | None:
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

    def get(self, key: str) -> str | None:
        """
        Get the value of a key from the cache.
        """
        return self.cache.get(key)

    async def get_async(self, key: str) -> str | None:
        """
        Get the value of a key from the cache.
        """
        return self.cache.get(key)

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


class FileStorage(MemoStorage):
    """
    Disk-based storage for storing and retrieving memoized results.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def exists(self, key: str) -> bool:
        """
        Check if a key exists in the file.
        """
        return (self.path / key).exists()

    async def exists_async(self, key: str) -> bool:
        """
        Check if a key exists in the file.
        """
        return await asyncio.to_thread((self.path / key).exists)

    def get(self, key: str) -> str | None:
        """
        Get the value of a key from the file.
        """
        try:
            return (self.path / key).read_text()
        except FileNotFoundError:
            return None

    async def get_async(self, key: str) -> str | None:
        """
        Get the value of a key from the file.
        """
        try:
            return await asyncio.to_thread((self.path / key).read_text)
        except FileNotFoundError:
            return None

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in the file.
        """
        (self.path / key).write_text(value)

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in the file.
        """
        await asyncio.to_thread((self.path / key).write_text, value)


DEFAULT_STORAGE: MemoStorage = MemoryStorage()
