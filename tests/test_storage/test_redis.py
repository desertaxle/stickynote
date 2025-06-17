from __future__ import annotations

import builtins
import importlib
import sys
from typing import Any

import pytest

from stickynote.storage import MissingMemoError, RedisStorage

try:
    import redis  # type: ignore

    redis_available = True
except ImportError:
    redis_available = False


@pytest.mark.skipif(not redis_available, reason="redis-py not available")
class TestRedisStorage:
    @pytest.fixture
    def storage(self) -> RedisStorage:
        storage = RedisStorage(db=15)  # Use a separate test database
        return storage

    @pytest.fixture
    def existing_key(self, storage: RedisStorage):
        storage.set("test", "test")
        return "test"

    def test_exists(self, storage: RedisStorage, existing_key: str):
        assert storage.exists(existing_key)

    async def test_exists_async(self, storage: RedisStorage, existing_key: str):
        assert await storage.exists_async(existing_key)

    def test_exists_nonexistent(self, storage: RedisStorage):
        assert not storage.exists("nonexistent")

    async def test_exists_async_nonexistent(self, storage: RedisStorage):
        assert not await storage.exists_async("nonexistent")

    def test_get(self, storage: RedisStorage, existing_key: str):
        assert storage.get(existing_key) == "test"

    async def test_get_async(self, storage: RedisStorage, existing_key: str):
        assert await storage.get_async(existing_key) == "test"

    def test_get_nonexistent(self, storage: RedisStorage):
        with pytest.raises(MissingMemoError):
            storage.get("nonexistent")

    async def test_get_async_nonexistent(self, storage: RedisStorage):
        with pytest.raises(MissingMemoError):
            await storage.get_async("nonexistent")

    def test_set(self, storage: RedisStorage):
        storage.set("test", "test")
        assert storage.get("test") == "test"

    async def test_set_async(self, storage: RedisStorage):
        await storage.set_async("test", "test")
        assert await storage.get_async("test") == "test"

    def test_prefix(self, storage: RedisStorage):
        # Test that keys are properly prefixed
        storage.set("test", "value")
        assert storage.client.exists("stickynote:test")

    def test_custom_prefix(self, storage: RedisStorage):
        try:
            storage = RedisStorage(db=15, prefix="custom:")
            storage.set("test", "value")
            assert storage.client.exists("custom:test")
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")


def test_redis_import_error():
    """Test that RedisStorage raises ImportError when redis-py is not available."""
    # Temporarily remove redis from sys.modules
    redis_module = sys.modules.get("redis")
    if "redis" in sys.modules:
        del sys.modules["redis"]

    # Mock the import to fail
    original_import = builtins.__import__

    def mock_import(name: str, *args: Any) -> Any:
        if name == "redis":
            raise ImportError("No module named 'redis'")
        return original_import(name, *args)

    builtins.__import__ = mock_import

    try:
        # Re-import the module to trigger the ImportError
        from stickynote.storage import redis as redis_module_local

        importlib.reload(redis_module_local)

        with pytest.raises(ImportError, match="redis-py is required for RedisStorage"):
            redis_module_local.RedisStorage()
    finally:
        # Restore the original import function
        builtins.__import__ = original_import
        # Restore redis module if it was there
        if redis_module is not None:
            sys.modules["redis"] = redis_module
