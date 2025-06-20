from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from .base import MemoStorage, MissingMemoError


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

    def exists(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the file.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for file storage"
            )
        return (self.path / key).exists()

    async def exists_async(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in the file.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for file storage"
            )
        return await asyncio.to_thread((self.path / key).exists)

    def get(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the file.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for file storage"
            )
        try:
            return (self.path / key).read_text()
        except FileNotFoundError as e:
            raise MissingMemoError(
                f"Memo for key {key} not found in file storage"
            ) from e

    async def get_async(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from the file.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for file storage"
            )
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
