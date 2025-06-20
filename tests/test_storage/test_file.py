from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stickynote.storage import FileStorage, MissingMemoError


class TestFileStorage:
    @pytest.fixture
    def storage(self, tmp_path: Path):
        return FileStorage(tmp_path / ".stickynote")

    @pytest.fixture
    def existing_file(self, storage: FileStorage):
        path = storage.path / "test"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test")
        return path

    def test_default_path(self):
        assert FileStorage().path == Path.home() / ".stickynote"

    def test_custom_path(self, tmp_path: Path):
        assert FileStorage(tmp_path).path == tmp_path

    def test_exists(self, storage: FileStorage, existing_file: Path):
        assert storage.exists(existing_file.name)

    def test_exists_nonexistent(self, storage: FileStorage):
        assert not storage.exists("test")

    def test_exists_with_max_age(self, storage: FileStorage, existing_file: Path):
        with pytest.raises(NotImplementedError):
            storage.exists(existing_file.name, max_age=timedelta(seconds=10))

    def test_exists_with_created_after(self, storage: FileStorage, existing_file: Path):
        with pytest.raises(NotImplementedError):
            storage.exists(
                existing_file.name,
                created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
            )

    async def test_exists_async(self, storage: FileStorage, existing_file: Path):
        assert await storage.exists_async(existing_file.name)

    async def test_exists_async_with_max_age(
        self, storage: FileStorage, existing_file: Path
    ):
        with pytest.raises(NotImplementedError):
            await storage.exists_async(
                existing_file.name, max_age=timedelta(seconds=10)
            )

    async def test_exists_async_with_created_after(
        self, storage: FileStorage, existing_file: Path
    ):
        with pytest.raises(NotImplementedError):
            await storage.exists_async(
                existing_file.name,
                created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
            )

    async def test_exists_async_nonexistent(self, storage: FileStorage):
        assert not await storage.exists_async("test")

    def test_get(self, storage: FileStorage, existing_file: Path):
        assert storage.get(existing_file.name) == "test"

    def test_get_nonexistent(self, storage: FileStorage):
        with pytest.raises(MissingMemoError):
            storage.get("test")

    def test_get_with_max_age(self, storage: FileStorage, existing_file: Path):
        with pytest.raises(NotImplementedError):
            storage.get(existing_file.name, max_age=timedelta(seconds=10))

    def test_get_with_created_after(self, storage: FileStorage, existing_file: Path):
        with pytest.raises(NotImplementedError):
            storage.get(
                existing_file.name,
                created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
            )

    async def test_get_async(self, storage: FileStorage, existing_file: Path):
        assert await storage.get_async(existing_file.name) == "test"

    async def test_get_async_with_max_age(
        self, storage: FileStorage, existing_file: Path
    ):
        with pytest.raises(NotImplementedError):
            await storage.get_async(existing_file.name, max_age=timedelta(seconds=10))

    async def test_get_async_with_created_after(
        self, storage: FileStorage, existing_file: Path
    ):
        with pytest.raises(NotImplementedError):
            await storage.get_async(
                existing_file.name,
                created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
            )

    async def test_get_async_nonexistent(self, storage: FileStorage):
        with pytest.raises(MissingMemoError):
            await storage.get_async("test")

    def test_set(self, storage: FileStorage):
        storage.set("test", "test")
        assert storage.get("test") == "test"

    async def test_set_async(self, storage: FileStorage):
        await storage.set_async("test", "test")
        assert await storage.get_async("test") == "test"
