from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional, Union, cast

from .base import ExpiredMemoError, MemoStorage, MissingMemoError

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
        self.client: RedisClient = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            **kwargs,
        )
        self.async_client: AsyncRedisClient = redis.asyncio.Redis(
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

    def _created_at_key(self, key: str) -> str:
        """Add created_at to key."""
        return f"{self.prefix}{key}:created_at"

    def _is_valid(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key is valid according to expiration rules.

        Args:
            key: The key to check
            created_after: Only consider records created at or after this datetime
        """
        created_at_timestamp = cast(
            Union[str, None], self.client.get(self._created_at_key(key))
        )
        if created_at_timestamp is None:
            return False
        created_at = datetime.fromisoformat(created_at_timestamp)
        return not (created_after is not None and created_at < created_after)

    async def _is_valid_async(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key is valid according to expiration rules.

        Args:
            key: The key to check
            created_after: Only consider records created at or after this datetime
        """
        created_at_timestamp = cast(
            Union[str, None], await self.async_client.get(self._created_at_key(key))
        )
        if created_at_timestamp is None:
            return False
        created_at = datetime.fromisoformat(created_at_timestamp)
        return not (created_after is not None and created_at < created_after)

    def exists(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in Redis.
        """
        return bool(self.client.exists(self._key(key))) and self._is_valid(
            key, created_after
        )

    async def exists_async(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> bool:
        """
        Check if a key exists in Redis.
        """
        return bool(
            await self.async_client.exists(self._key(key))
        ) and await self._is_valid_async(key, created_after)

    def get(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from Redis.
        """
        value = cast(Optional[str], self.client.get(self._key(key)))
        if value is None:
            raise MissingMemoError(f"Memo for key {key} not found in Redis")
        if not self._is_valid(key, created_after):
            raise ExpiredMemoError(
                f"Memo for key {key} is not valid in the requested time window"
            )
        return value

    async def get_async(
        self,
        key: str,
        created_after: datetime | None = None,
    ) -> str:
        """
        Get the value of a key from Redis.
        """
        value = cast(Optional[str], await self.async_client.get(self._key(key)))
        if value is None:
            raise MissingMemoError(f"Memo for key {key} not found in Redis")
        if not await self._is_valid_async(key, created_after):
            raise ExpiredMemoError(
                f"Memo for key {key} is not valid in the requested time window"
            )
        return value

    def set(self, key: str, value: str) -> None:
        """
        Set the value of a key in Redis.

        Args:
            key: The key to set the value for
            value: The value to set
        """
        pipe = self.client.pipeline()  # pyright: ignore[reportUnknownMemberType]
        pipe.set(self._key(key), value)
        pipe.set(self._created_at_key(key), datetime.now(timezone.utc).isoformat())
        pipe.execute()

    async def set_async(self, key: str, value: str) -> None:
        """
        Set the value of a key in Redis.

        Args:
            key: The key to set the value for
            value: The value to set
        """
        pipe = self.async_client.pipeline()  # pyright: ignore[reportUnknownMemberType]
        pipe.set(self._key(key), value)
        pipe.set(self._created_at_key(key), datetime.now(timezone.utc).isoformat())
        await pipe.execute()
