from typing import Protocol


class MemoStorage(Protocol):
    """
    Protocol for a storage backend to store and retrieve memoized results.
    """

    def exists(self, key: str) -> bool:
        """
        Check if a key exists in the backend.
        """
        ...

    async def exists_async(self, key: str) -> bool:
        """
        Check if a key exists in the backend.
        """
        ...

    def get(self, key: str) -> str:
        """
        Get the value of a key from the backend.
        """
        ...

    async def get_async(self, key: str) -> str:
        """
        Get the value of a key from the backend.
        """
        ...

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in the backend.
        """
        ...

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in the backend.
        """
        ...


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
        return self.cache[key]

    async def get_async(self, key: str) -> str:
        """
        Get the value of a key from the cache.
        """
        return self.cache[key]

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


DEFAULT_STORAGE: MemoStorage = MemoryStorage()
