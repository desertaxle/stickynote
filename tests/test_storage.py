from pathlib import Path

import pytest

from stickynote.storage import FileStorage, MemoryStorage, MissingMemoError


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


class TestFileStorage:
    @pytest.fixture
    def storage(self, tmp_path: Path):
        return FileStorage(tmp_path)

    @pytest.fixture
    def existing_file(self, storage: FileStorage):
        path = storage.path / "test"
        path.write_text("test")
        return path

    def test_default_path(self):
        assert FileStorage().path == Path.home() / ".stickynote"

    def test_custom_path(self, tmp_path: Path):
        assert FileStorage(tmp_path).path == tmp_path

    def test_exists(self, storage: FileStorage, existing_file: Path):
        assert storage.exists(existing_file.name)

    async def test_exists_async(self, storage: FileStorage, existing_file: Path):
        assert await storage.exists_async(existing_file.name)

    def test_exists_nonexistent(self, storage: FileStorage):
        assert not storage.exists("test")

    async def test_exists_async_nonexistent(self, storage: FileStorage):
        assert not await storage.exists_async("test")

    def test_get(self, storage: FileStorage, existing_file: Path):
        assert storage.get(existing_file.name) == "test"

    async def test_get_async(self, storage: FileStorage, existing_file: Path):
        assert await storage.get_async(existing_file.name) == "test"

    def test_get_nonexistent(self, storage: FileStorage):
        with pytest.raises(MissingMemoError):
            storage.get("test")

    async def test_get_async_nonexistent(self, storage: FileStorage):
        with pytest.raises(MissingMemoError):
            await storage.get_async("test")

    def test_set(self, storage: FileStorage):
        storage.set("test", "test")
        assert storage.get("test") == "test"

    async def test_set_async(self, storage: FileStorage):
        await storage.set_async("test", "test")
        assert await storage.get_async("test") == "test"
