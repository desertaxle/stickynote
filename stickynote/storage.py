from __future__ import annotations

import asyncio
from pathlib import Path
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


class FileStorage(MemoStorage):
    """
    Disk-based storage for storing and retrieving memoized results.
    """

    def __init__(self, path: Path | str = Path.home() / ".stickynote"):
        self.path: Path = Path(path)

    def _ensure_directory_exists(self) -> None:
        """
        Ensure the storage directory exists, creating it if necessary.
        """
        if not self.path.exists():
            self.path.mkdir(parents=True, exist_ok=True)

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

    def get(self, key: str) -> str:
        """
        Get the value of a key from the file.
        """
        try:
            return (self.path / key).read_text()
        except FileNotFoundError as e:
            raise MissingMemoError(
                f"Memo for key {key} not found in file storage"
            ) from e

    async def get_async(self, key: str) -> str:
        """
        Get the value of a key from the file.
        """
        try:
            return await asyncio.to_thread((self.path / key).read_text)
        except FileNotFoundError as e:
            raise MissingMemoError(
                f"Memo for key {key} not found in file storage"
            ) from e

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in the file.
        """
        self._ensure_directory_exists()
        (self.path / key).write_text(value)

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in the file.
        """
        self._ensure_directory_exists()
        await asyncio.to_thread((self.path / key).write_text, value)


DEFAULT_STORAGE: MemoStorage = MemoryStorage()
