from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional, cast

from .base import MemoStorage, MissingMemoError

try:
    import redis
    import redis.asyncio
except ImportError:
    redis = None

if TYPE_CHECKING:
    from redis import Redis as RedisClient  # pragma: no cover
    from redis.asyncio import Redis as AsyncRedisClient  # pragma: no cover


class RedisStorage(MemoStorage):
    """
    Redis-based storage for storing and retrieving memoized results.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        prefix: str = "stickynote:",
        **kwargs: Any,
    ):
        if redis is None:
            raise ImportError(
                "redis-py is required for RedisStorage. "
                "Install it with: pip install 'stickynote[redis]'"
            )

        self.prefix = prefix
        self.client: "RedisClient" = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            **kwargs,
        )
        self.async_client: "AsyncRedisClient" = redis.asyncio.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            **kwargs,
        )

    def _key(self, key: str) -> str:
        """Add prefix to key."""
        return f"{self.prefix}{key}"

    def exists(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in Redis.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for Redis storage"
            )
        return bool(self.client.exists(self._key(key)))

    async def exists_async(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in Redis.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for Redis storage"
            )
        return bool(await self.async_client.exists(self._key(key)))

    def get(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from Redis.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for Redis storage"
            )
        value = cast(Optional[str], self.client.get(self._key(key)))
        if value is None:
            raise MissingMemoError(f"Memo for key {key} not found in Redis")
        return value

    async def get_async(
        self,
        key: str,
        max_age: timedelta | None = None,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from Redis.
        """
        if max_age is not None or created_after is not None:
            raise NotImplementedError(
                "max_age and created_after are not yet supported for Redis storage"
            )
        value = cast(Optional[str], await self.async_client.get(self._key(key)))
        if value is None:
            raise MissingMemoError(f"Memo for key {key} not found in Redis")
        return value

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in Redis.
        """
        self.client.set(self._key(key), value)

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in Redis.
        """
        await self.async_client.set(self._key(key), value)
