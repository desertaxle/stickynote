from .base import MemoStorage, MissingMemoError
from .memory import MemoryStorage

DEFAULT_STORAGE: MemoStorage = MemoryStorage()

__all__ = ["MemoStorage", "MissingMemoError", "DEFAULT_STORAGE"]
