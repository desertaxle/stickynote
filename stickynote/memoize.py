from __future__ import annotations

import inspect
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from functools import partial, update_wrapper
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Literal,
    Protocol,
    TypeVar,
    cast,
    overload,
)

from exceptiongroup import ExceptionGroup
from typing_extensions import ParamSpec, Self

from stickynote.key_strategies import DEFAULT_STRATEGY, MemoKeyStrategy
from stickynote.serializers import DEFAULT_SERIALIZER_CHAIN, Serializer
from stickynote.storage import DEFAULT_STORAGE, MemoStorage
from stickynote.storage.base import ExpiredMemoError

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", contravariant=True)

logger: logging.Logger = logging.getLogger("stickynote.memoize")


class BeforeCacheLookupCallback(Protocol):
    def __call__(
        self, key: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None: ...


class OnCacheHitCallback(Protocol, Generic[R_co]):
    def __call__(
        self,
        key: str,
        value: R_co,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        timestamp: datetime,
    ) -> None: ...


class MemoizedCallable(Generic[P, R]):
    """Protocol for memoized callables."""

    def __init__(
        self,
        fn: Callable[P, R],
        storage: MemoStorage,
        serializer: Serializer | Iterable[Serializer],
        key_strategy: MemoKeyStrategy,
        max_age: timedelta | None = None,
    ):
        self.fn = fn
        update_wrapper(self, fn)
        self.storage = storage
        self.serializer = serializer
        self.key_strategy = key_strategy
        self.max_age = max_age
        self.on_cache_hit_callbacks: list[OnCacheHitCallback[R]] = []
        self.before_cache_lookup_callbacks: list[BeforeCacheLookupCallback] = []

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        if inspect.iscoroutinefunction(self.fn):
            return self._call_async(*args, **kwargs)  # pyright: ignore[reportReturnType] need to return a coroutine if the wrapped function is async
        key = self.key_strategy.compute(self.fn, args, kwargs)
        for callback in self.before_cache_lookup_callbacks:
            callback(key, args, kwargs)
        with MemoBlock(
            key=key,
            storage=self.storage,
            serializer=self.serializer,
            max_age=self.max_age,
        ) as memo:
            if memo.hit:
                for callback in self.on_cache_hit_callbacks:
                    try:
                        callback(
                            key,
                            memo.value,
                            args,
                            kwargs,
                            datetime.now(timezone.utc),
                        )
                    except Exception:
                        logger.warning(
                            "An error occurred while calling on_cache_hit callback",
                            exc_info=True,
                        )
                return memo.value
            result = self.fn(*args, **kwargs)
            memo.stage(result)
            return result

    async def _call_async(self, *args: P.args, **kwargs: P.kwargs) -> R:
        key = self.key_strategy.compute(self.fn, args, kwargs)
        for callback in self.before_cache_lookup_callbacks:
            callback(key, args, kwargs)
        async with AsyncMemoBlock(
            key=key,
            storage=self.storage,
            serializer=self.serializer,
            max_age=self.max_age,
        ) as memo:
            if memo.hit:
                for callback in self.on_cache_hit_callbacks:
                    try:
                        callback(
                            key,
                            memo.value,
                            args,
                            kwargs,
                            datetime.now(timezone.utc),
                        )
                    except Exception:
                        logger.warning(
                            "An error occurred while calling on_cache_hit callback",
                            exc_info=True,
                        )
                return memo.value
            if TYPE_CHECKING:
                assert inspect.iscoroutinefunction(self.fn)  # pragma: no cover
            result = await self.fn(*args, **kwargs)
            memo.stage(result)
            return result

    def before_cache_lookup(self, fn: BeforeCacheLookupCallback) -> None:
        self.before_cache_lookup_callbacks.append(fn)

    def on_cache_hit(
        self,
        fn: OnCacheHitCallback[R],
    ) -> None:
        self.on_cache_hit_callbacks.append(fn)


@overload
def memoize(
    __fn: Callable[P, R],
) -> MemoizedCallable[P, R]: ...


@overload
def memoize(
    __fn: Literal[None] = None,
    *,
    storage: MemoStorage = DEFAULT_STORAGE,
    key_strategy: MemoKeyStrategy = DEFAULT_STRATEGY,
    serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
    max_age: timedelta | None = None,
) -> Callable[[Callable[P, R]], MemoizedCallable[P, R]]: ...


def memoize(
    __fn: Callable[P, R] | None = None,
    *,
    storage: MemoStorage = DEFAULT_STORAGE,
    key_strategy: MemoKeyStrategy = DEFAULT_STRATEGY,
    serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
    max_age: timedelta | None = None,
) -> (
    MemoizedCallable[P, R]
    | Callable[
        [Callable[P, R]],
        MemoizedCallable[P, R],
    ]
):
    """
    Decorator to memoize the results of a function.

    Args:
        storage: A `Storage` object to use to store memoized results.
        key_strategy: The key strategy to use for memoization.
        serializer: The serializer to use for memoization.
        max_age: The maximum age of the cached result.
    """

    if __fn is None:
        return cast(
            Callable[
                [Callable[P, R]],
                MemoizedCallable[P, R],
            ],
            partial(
                memoize,
                storage=storage,
                key_strategy=key_strategy,
                serializer=serializer,
                max_age=max_age,
            ),
        )
    return MemoizedCallable(
        __fn,
        storage=storage,
        serializer=serializer,
        key_strategy=key_strategy,
        max_age=max_age,
    )


_UNSET = object()


class BaseMemoBlock:
    """
    Base class for memoization blocks.
    """

    def __init__(
        self,
        key: str,
        storage: MemoStorage = DEFAULT_STORAGE,
        serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
        max_age: timedelta | None = None,
    ):
        self.key = key
        self.storage = storage
        self.max_age = max_age

        self.hit: bool = False
        self.value: Any = None
        if isinstance(serializer, Serializer):
            self.serializer: tuple[Serializer, ...] = (serializer,)
        else:
            self.serializer: tuple[Serializer, ...] = tuple(serializer)

        self.staged_value: Any = _UNSET

    def stage(self, value: Any) -> None:
        """
        Stage the result of a function to be saved.
        """
        self.staged_value = value


class MemoBlock(BaseMemoBlock):
    """
    Context manager to load and save the result of a function to a backend.
    """

    def __enter__(self) -> Self:
        self.load()
        return self

    def __exit__(self, *args: Any) -> None:
        self.save()

        self.staged_value = _UNSET

    def load(self) -> None:
        """
        Load the result of a function from the backend.
        """
        serializer_exceptions: list[Exception] = []
        if self.storage.exists(self.key):
            for serializer in self.serializer:
                try:
                    created_after = (
                        datetime.now(timezone.utc) - self.max_age
                        if self.max_age
                        else None
                    )
                    self.value: Any = serializer.deserialize(
                        self.storage.get(key=self.key, created_after=created_after)
                    )
                    self.hit = True
                    break
                except ExpiredMemoError:
                    break
                except Exception as e:
                    serializer_exceptions.append(e)

        if len(serializer_exceptions) == len(self.serializer):
            raise ExceptionGroup(
                "All serializers failed to deserialize the result.",
                serializer_exceptions,
            )

    def save(self) -> None:
        """
        Save the result of a function to the backend.
        """
        if self.staged_value is _UNSET:
            return

        serializer_exceptions: list[Exception] = []
        serialized_value = _UNSET
        for serializer in self.serializer:
            try:
                serialized_value = serializer.serialize(self.staged_value)
                break
            except Exception as e:
                serializer_exceptions.append(e)

        if not isinstance(serialized_value, str):
            raise ExceptionGroup(
                "All serializers failed to serialize the result.", serializer_exceptions
            )

        self.storage.set(self.key, serialized_value)


class AsyncMemoBlock(BaseMemoBlock):
    """
    Context manager to load and save the result of a function to a backend.
    """

    async def __aenter__(self) -> Self:
        await self.load()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.save()

    async def load(self) -> None:
        """
        Load the result of a function from the backend.
        """
        serializer_exceptions: list[Exception] = []
        if await self.storage.exists_async(self.key):
            for serializer in self.serializer:
                try:
                    created_after = (
                        datetime.now(timezone.utc) - self.max_age
                        if self.max_age
                        else None
                    )
                    self.value: Any = serializer.deserialize(
                        await self.storage.get_async(
                            key=self.key, created_after=created_after
                        )
                    )
                    self.hit = True
                    break
                except ExpiredMemoError:
                    break
                except Exception as e:
                    serializer_exceptions.append(e)

        if len(serializer_exceptions) == len(self.serializer):
            raise ExceptionGroup(
                "All serializers failed to deserialize the result.",
                serializer_exceptions,
            )

    async def save(self) -> None:
        """
        Save the result of a function to the backend.
        """
        if self.staged_value is _UNSET:
            return

        serializer_exceptions: list[Exception] = []
        serialized_value = _UNSET
        for serializer in self.serializer:
            try:
                serialized_value = serializer.serialize(self.staged_value)
                break
            except Exception as e:
                serializer_exceptions.append(e)

        if not isinstance(serialized_value, str):
            raise ExceptionGroup(
                "All serializers failed to serialize the result.", serializer_exceptions
            )

        await self.storage.set_async(self.key, serialized_value)
