from __future__ import annotations

from .base import MemoStorage, MissingMemoError
from .file import FileStorage
from .memory import MemoryStorage

try:
    from .redis import RedisStorage
except ImportError:
    RedisStorage = None  # type: ignore

DEFAULT_STORAGE: MemoStorage = MemoryStorage()

__all__ = ["MemoStorage", "MissingMemoError", "FileStorage", "MemoryStorage", "DEFAULT_STORAGE"]
if RedisStorage is not None:
    __all__.append("RedisStorage")