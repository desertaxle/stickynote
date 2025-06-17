import pytest

from stickynote.storage import MemoryStorage, MissingMemoError


class TestMemoryStorage:
    @pytest.fixture
    def storage(self):
        return MemoryStorage()

    @pytest.fixture
    def existing_key(self, storage: MemoryStorage):
        storage.set("test", "test")
        return "test"

    def test_exists(self, storage: MemoryStorage, existing_key: str):
        assert storage.exists(existing_key)

    async def test_exists_async(self, storage: MemoryStorage):
        assert not await storage.exists_async("test")

    def test_exists_nonexistent(self, storage: MemoryStorage):
        assert not storage.exists("test")

    async def test_exists_async_nonexistent(self, storage: MemoryStorage):
        assert not await storage.exists_async("test")

    def test_get(self, storage: MemoryStorage, existing_key: str):
        assert storage.get(existing_key) == "test"

    async def test_get_async(self, storage: MemoryStorage, existing_key: str):
        assert await storage.get_async(existing_key) == "test"

    def test_get_nonexistent(self, storage: MemoryStorage):
        with pytest.raises(MissingMemoError):
            storage.get("test")

    async def test_get_async_nonexistent(self, storage: MemoryStorage):
        with pytest.raises(MissingMemoError):
            await storage.get_async("test")

    def test_set(self, storage: MemoryStorage):
        storage.set("test", "test")
        assert storage.get("test") == "test"

    async def test_set_async(self, storage: MemoryStorage):
        await storage.set_async("test", "test")
        assert await storage.get_async("test") == "test"
