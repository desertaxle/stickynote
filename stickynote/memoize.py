from stickynote.backends import MemoStorage
from hashlib import sha256
from typing import Any, Callable, Self, TypeVar
from typing_extensions import ParamSpec
import pickle
import base64

P = ParamSpec("P")
R = TypeVar("R")


def memoize(storage: MemoStorage) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator to memoize the results of a function.
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with MemoBlock(storage) as memo:
                key = f"{func.__name__}:{_hash_args_kwargs(args, kwargs)}"
                memo.load(key)
                if memo.hit:
                    return memo.value
                result = func(*args, **kwargs)
                memo.save(key, result)
                return result

        return wrapper

    return decorator


class MemoBlock:
    """
    Context manager to load and save the result of a function to a backend.
    """
    def __init__(self, storage: MemoStorage):
        self.storage = storage
        self.hit: bool = False
        self.value: Any = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def load(self, key: str) -> None:
        """
        Load the result of a function from the backend.
        """
        if self.storage.exists(key):
            self.value = _deserialize_result(self.storage.get(key))
            self.hit = True

    def save(self, key: str, value: Any) -> None:
        """
        Save the result of a function to the backend.
        """
        self.storage.set(key, _serialize_result(value))


def _hash_args_kwargs(args: Any, kwargs: Any) -> str:
    """
    Hash the arguments and keyword arguments of a function.
    """
    return sha256(f"{args}:{kwargs}".encode()).hexdigest()


def _serialize_result(result: Any) -> str:
    return base64.b64encode(pickle.dumps(result)).decode("utf-8")


def _deserialize_result(serialized_result: str) -> Any:
    return pickle.loads(base64.b64decode(serialized_result.encode("utf-8")))
