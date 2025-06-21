from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .base import ExpiredMemoError, MemoStorage, MissingMemoError


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

    def _is_valid(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> bool:
        path = self.path / key
        if not path.exists():
            return False
        stat_result = path.stat()
        if max_age is not None:
            created_at = datetime.fromtimestamp(stat_result.st_mtime)
            if (datetime.now() - created_at) > max_age:
                return False
        if created_after is not None:
            created_at = datetime.fromtimestamp(stat_result.st_mtime)
            created_at = created_at.astimezone(tz=timezone.utc)
            if created_at < created_after:
                return False
        return True

    def exists(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the file.
        """
        return self._is_valid(key, max_age, created_after)

    async def exists_async(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the file.
        """
        return await asyncio.to_thread(
            self.exists, key=key, max_age=max_age, created_after=created_after
        )

    def get(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the file.
        """
        try:
            value = (self.path / key).read_text()
        except FileNotFoundError as e:
            raise MissingMemoError(
                f"Memo for key {key} not found in file storage"
            ) from e
        if not self._is_valid(key, max_age, created_after):
            raise ExpiredMemoError(f"Memo for key {key} has expired in file storage")
        return value

    async def get_async(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the file.
        """
        return await asyncio.to_thread(
            self.get, key=key, max_age=max_age, created_after=created_after
        )

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
