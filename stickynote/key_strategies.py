import abc
import hashlib
import inspect
import json
import logging
import pickle
from typing import Any, Callable

logger: logging.Logger = logging.getLogger("stickynote.key_strategies")


class MemoKeyStrategy(abc.ABC):
    @abc.abstractmethod
    def compute(self, func: Callable[..., Any], args: Any, kwargs: Any) -> str: ...

    def __add__(self, other: "MemoKeyStrategy") -> "CompoundMemoKeyStrategy":
        return CompoundMemoKeyStrategy(self, other)


class Inputs(MemoKeyStrategy):
    def compute(self, func: Callable[..., Any], args: Any, kwargs: Any) -> str:
        # Get the function's signature
        sig = inspect.signature(func)

        # Bind the arguments to the function's parameters
        bound_args = sig.bind(*args, **kwargs)

        # Apply default values for any missing arguments
        bound_args.apply_defaults()

        # Convert to a dictionary with parameter names as keys
        args_dict = dict(bound_args.arguments)

        try:
            # Use JSON to serialize the dictionary with sort_keys=True for consistency
            json_str = json.dumps(args_dict, sort_keys=True)
            sha256 = hashlib.sha256()
            sha256.update(json_str.encode("utf-8"))
            return sha256.hexdigest()
        except Exception as e:
            logger.debug(f"Failed to serialize arguments with JSON: {e}")

        try:
            sha256 = hashlib.sha256()
            sha256.update(pickle.dumps(args_dict))
            return sha256.hexdigest()
        except Exception as e:
            logger.debug(f"Failed to serialize arguments with pickle: {e}")

        raise ValueError("Failed to serialize arguments")


class SourceCode(MemoKeyStrategy):
    def compute(self, func: Callable[..., Any], args: Any, kwargs: Any) -> str:
        sha256 = hashlib.sha256()
        sha256.update(inspect.getsource(func).encode("utf-8"))
        return sha256.hexdigest()


class CompoundMemoKeyStrategy(MemoKeyStrategy):
    def __init__(self, *strategies: MemoKeyStrategy):
        self.strategies: tuple[MemoKeyStrategy, ...] = tuple(
            s
            for strategy in strategies
            for s in (
                strategy.strategies
                if isinstance(strategy, CompoundMemoKeyStrategy)
                else [strategy]
            )
        )

    def compute(self, func: Callable[..., Any], args: Any, kwargs: Any) -> str:
        sha256 = hashlib.sha256()
        for strategy in self.strategies:
            sha256.update(strategy.compute(func, args, kwargs).encode())
        return sha256.hexdigest()

    def __add__(self, other: MemoKeyStrategy) -> "CompoundMemoKeyStrategy":
        if isinstance(other, CompoundMemoKeyStrategy):
            return CompoundMemoKeyStrategy(*self.strategies, *other.strategies)
        else:
            return CompoundMemoKeyStrategy(*self.strategies, other)


DEFAULT_STRATEGY = SourceCode() + Inputs()
