from typing import Protocol


class Backend(Protocol):
    def exists(self, key: str) -> bool: ...
    def get(self, key: str) -> str: ...
    def set(self, key: str, value: str) -> None: ...


class MemoryBackend(Backend):
    def __init__(self):
        self.cache: dict[str, str] = {}

    def exists(self, key: str) -> bool:
        return key in self.cache

    def get(self, key: str) -> str:
        return self.cache[key]

    def set(self, key: str, value: str) -> None:
        self.cache[key] = value
