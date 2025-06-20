from datetime import datetime, timedelta, timezone

import pytest

from stickynote.storage import MemoryStorage, MissingMemoError
from stickynote.storage.base import ExpiredMemoError


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

    def test_exists_with_max_age(self, storage: MemoryStorage, existing_key: str):
        assert storage.exists(existing_key, max_age=timedelta(seconds=10))
        # a valid record isn't found becuase the existing one is more than 1 microsecond old
        assert not storage.exists(existing_key, max_age=timedelta(microseconds=1))

    def test_exists_with_created_after(self, storage: MemoryStorage, existing_key: str):
        assert storage.exists(
            existing_key,
            created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        assert not storage.exists(
            existing_key,
            created_after=datetime.now(timezone.utc) + timedelta(microseconds=1),
        )

    async def test_exists_async(self, storage: MemoryStorage):
        assert not await storage.exists_async("test")

    async def test_exists_async_with_max_age(
        self, storage: MemoryStorage, existing_key: str
    ):
        assert await storage.exists_async(existing_key, max_age=timedelta(seconds=10))
        assert not await storage.exists_async(
            existing_key, max_age=timedelta(microseconds=1)
        )

    async def test_exists_async_with_created_after(
        self, storage: MemoryStorage, existing_key: str
    ):
        assert await storage.exists_async(
            existing_key,
            created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        assert not await storage.exists_async(
            existing_key,
            created_after=datetime.now(timezone.utc) + timedelta(microseconds=1),
        )

    def test_exists_nonexistent(self, storage: MemoryStorage):
        assert not storage.exists("test")

    async def test_exists_async_nonexistent(self, storage: MemoryStorage):
        assert not await storage.exists_async("test")

    def test_get(self, storage: MemoryStorage, existing_key: str):
        assert storage.get(existing_key) == "test"

    def test_get_with_max_age(self, storage: MemoryStorage, existing_key: str):
        assert storage.get(existing_key, max_age=timedelta(seconds=10)) == "test"
        with pytest.raises(ExpiredMemoError):
            storage.get(existing_key, max_age=timedelta(microseconds=1))

    def test_get_with_created_after(self, storage: MemoryStorage, existing_key: str):
        assert (
            storage.get(
                existing_key,
                created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
            )
            == "test"
        )
        with pytest.raises(ExpiredMemoError):
            storage.get(
                existing_key,
                created_after=datetime.now(timezone.utc) + timedelta(microseconds=1),
            )

    async def test_get_async(self, storage: MemoryStorage, existing_key: str):
        assert await storage.get_async(existing_key) == "test"

    async def test_get_async_with_max_age(
        self, storage: MemoryStorage, existing_key: str
    ):
        assert (
            await storage.get_async(existing_key, max_age=timedelta(seconds=10))
            == "test"
        )
        with pytest.raises(ExpiredMemoError):
            await storage.get_async(existing_key, max_age=timedelta(microseconds=1))

    async def test_get_async_with_created_after(
        self, storage: MemoryStorage, existing_key: str
    ):
        assert (
            await storage.get_async(
                existing_key,
                created_after=datetime.now(timezone.utc) - timedelta(seconds=10),
            )
            == "test"
        )
        with pytest.raises(ExpiredMemoError):
            await storage.get_async(
                existing_key,
                created_after=datetime.now(timezone.utc) + timedelta(microseconds=1),
            )

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
