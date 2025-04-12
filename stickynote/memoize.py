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
R = TypeVar("R", contravariant=True)


class OnCacheHitCallback(Protocol, Generic[P, R]):
    """Callback function for when a cache hit occurs."""

    def __call__(
        self,
        key: str,
        value: R,
        function: Callable[P, R],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        hit_time: datetime,
    ) -> None: ...


@overload
def memoize(
    __fn: Callable[P, R],
) -> Callable[P, R]: ...


@overload
def memoize(
    __fn: Literal[None] = None,
    *,
    storage: MemoStorage = DEFAULT_STORAGE,
    key_strategy: MemoKeyStrategy = DEFAULT_STRATEGY,
    serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
    on_cache_hit: OnCacheHitCallback[P, R] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def memoize(
    __fn: Callable[P, R] | None = None,
    *,
    storage: MemoStorage = DEFAULT_STORAGE,
    key_strategy: MemoKeyStrategy = DEFAULT_STRATEGY,
    serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
    on_cache_hit: OnCacheHitCallback[P, R] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
    """
    Decorator to memoize the results of a function.
    """

    if __fn is None:
        return cast(
            Callable[[Callable[P, R]], Callable[P, R]],
            partial(
                memoize,
                storage=storage,
                key_strategy=key_strategy,
                serializer=serializer,
                on_cache_hit=on_cache_hit,
            ),
        )
    else:

        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with MemoBlock(storage, serializer) as memo:
                key = key_strategy.compute(__fn, args, kwargs)
                memo.load(key)
                if memo.hit:
                    if on_cache_hit is not None:
                        on_cache_hit(
                            key,
                            memo.value,
                            __fn,
                            args,
                            kwargs,
                            datetime.now(timezone.utc),
                        )
                    return memo.value
                result = __fn(*args, **kwargs)
                memo.save(key, result)
                return result

        return wrapper


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
