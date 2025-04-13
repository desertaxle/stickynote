from __future__ import annotations

from datetime import timezone, datetime
from functools import partial
from typing import (
    Any,
    Callable,
    Generic,
    Iterable,
    Literal,
    Protocol,
    TypeVar,
    cast,
    overload,
)

from typing_extensions import ParamSpec, Self
from exceptiongroup import ExceptionGroup

from stickynote.key_strategies import DEFAULT_STRATEGY, MemoKeyStrategy
from stickynote.serializers import DEFAULT_SERIALIZER_CHAIN, Serializer
from stickynote.storage import DEFAULT_STORAGE, MemoStorage

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)


class OnCacheHitCallback(Protocol, Generic[P, R_co]):
    def __call__(
        self,
        key: str,
        value: R,
        fn: Callable[P, R],
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
    ):
        self.fn = fn
        self.storage = storage
        self.serializer = serializer
        self.key_strategy = key_strategy
        self._on_cache_hit_callbacks: list[OnCacheHitCallback[P, R]] = []

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        with MemoBlock(self.storage, self.serializer) as memo:
            key = self.key_strategy.compute(self.fn, args, kwargs)
            memo.load(key)
            if memo.hit:
                for callback in self._on_cache_hit_callbacks:
                    callback(
                        key,
                        memo.value,
                        self.fn,
                        args,
                        kwargs,
                        datetime.now(timezone.utc),
                    )
                return memo.value
            result = self.fn(*args, **kwargs)
            memo.save(key, result)
            return result

    def on_cache_hit(
        self,
        fn: OnCacheHitCallback[P, R],
    ) -> None:
        self._on_cache_hit_callbacks.append(fn)


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
    on_cache_hit: Callable[
        [str, Any, Callable[..., Any], tuple[Any, ...], dict[str, Any], datetime], None
    ]
    | None = None,
) -> Callable[[Callable[P, R]], MemoizedCallable[P, R]]: ...


def memoize(
    __fn: Callable[P, R] | None = None,
    *,
    storage: MemoStorage = DEFAULT_STORAGE,
    key_strategy: MemoKeyStrategy = DEFAULT_STRATEGY,
    serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
    on_cache_hit: Callable[
        [str, R, Callable[..., R], tuple[Any, ...], dict[str, Any], datetime], None
    ]
    | None = None,
) -> Callable[[Callable[P, R]], MemoizedCallable[P, R]] | MemoizedCallable[P, R]:
    """
    Decorator to memoize the results of a function.
    """

    if __fn is None:
        return cast(
            Callable[[Callable[P, R]], MemoizedCallable[P, R]],
            partial(
                memoize,
                storage=storage,
                key_strategy=key_strategy,
                serializer=serializer,
                on_cache_hit=on_cache_hit,
            ),
        )
    else:
        return MemoizedCallable(__fn, storage, serializer, key_strategy)


class MemoBlock:
    """
    Context manager to load and save the result of a function to a backend.
    """

    def __init__(
        self,
        storage: MemoStorage = DEFAULT_STORAGE,
        serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
    ):
        self.storage = storage
        self.hit: bool = False
        self.value: Any = None
        if isinstance(serializer, Serializer):
            self.serializer: tuple[Serializer, ...] = (serializer,)
        else:
            self.serializer: tuple[Serializer, ...] = tuple(serializer)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def load(self, key: str) -> None:
        """
        Load the result of a function from the backend.
        """
        serializer_exceptions: list[Exception] = []
        if self.storage.exists(key):
            for serializer in self.serializer:
                try:
                    self.value = serializer.deserialize(self.storage.get(key))
                    self.hit = True
                    break
                except Exception as e:
                    serializer_exceptions.append(e)

        if len(serializer_exceptions) == len(self.serializer):
            raise ExceptionGroup(
                "All serializers failed to deserialize the result.",
                serializer_exceptions,
            )

    def save(self, key: str, value: Any) -> None:
        """
        Save the result of a function to the backend.
        """
        serializer_exceptions: list[Exception] = []
        for serializer in self.serializer:
            try:
                self.storage.set(key, serializer.serialize(value))
                break
            except Exception as e:
                serializer_exceptions.append(e)

        if len(serializer_exceptions) == len(self.serializer):
            raise ExceptionGroup(
                "All serializers failed to serialize the result.", serializer_exceptions
            )
