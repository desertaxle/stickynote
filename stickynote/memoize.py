from __future__ import annotations

from functools import partial
from typing import Any, Callable, Iterable, Literal, TypeVar, cast, overload

from typing_extensions import ParamSpec, Self
from exceptiongroup import ExceptionGroup

from stickynote.key_strategies import DEFAULT_STRATEGY, MemoKeyStrategy
from stickynote.serializers import DEFAULT_SERIALIZER_CHAIN, Serializer
from stickynote.storage import DEFAULT_STORAGE, MemoStorage

P = ParamSpec("P")
R = TypeVar("R")


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
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def memoize(
    __fn: Callable[P, R] | None = None,
    *,
    storage: MemoStorage = DEFAULT_STORAGE,
    key_strategy: MemoKeyStrategy = DEFAULT_STRATEGY,
    serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
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
            ),
        )
    else:

        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with MemoBlock(storage, serializer) as memo:
                key = key_strategy.compute(__fn, args, kwargs)
                memo.load(key)
                if memo.hit:
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
        if isinstance(serializer, Iterable):
            self.serializer: tuple[Serializer, ...] = tuple(serializer)
        else:
            self.serializer: tuple[Serializer, ...] = (serializer,)

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
