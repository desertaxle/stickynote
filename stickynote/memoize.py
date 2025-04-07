from stickynote.backends import Backend
from hashlib import sha256
from typing import Any, Callable, TypeVar
from typing_extensions import ParamSpec
import pickle
import base64

P = ParamSpec("P")
R = TypeVar("R")


def memoize(backend: Backend) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = f"{func.__name__}:{_hash_args_kwargs(args, kwargs)}"
            if backend.exists(key):
                serialized_result = backend.get(key)
                return _deserialize_result(serialized_result)
            result = func(*args, **kwargs)
            serialized_result = _serialize_result(result)
            backend.set(key, serialized_result)
            return result

        return wrapper

    return decorator


def _hash_args_kwargs(args: Any, kwargs: Any) -> str:
    return sha256(f"{args}:{kwargs}".encode()).hexdigest()


def _serialize_result(result: Any) -> str:
    return base64.b64encode(pickle.dumps(result)).decode('utf-8')


def _deserialize_result(serialized_result: str) -> Any:
    return pickle.loads(base64.b64decode(serialized_result.encode('utf-8')))
