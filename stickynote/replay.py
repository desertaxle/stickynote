from __future__ import annotations

import functools
import hashlib
import inspect
import json
import sys
from collections.abc import Callable, Iterable
from typing import Any

from exceptiongroup import ExceptionGroup

from stickynote.key_strategies import Inputs
from stickynote.serializers import DEFAULT_SERIALIZER_CHAIN, Serializer
from stickynote.storage import DEFAULT_STORAGE, MemoStorage
from stickynote.storage.base import MissingMemoError


def _is_stdlib_module(module_name: str) -> bool:
    """Check if a module name belongs to the standard library or builtins."""
    top_level = module_name.split(".")[0]
    if top_level == "builtins":
        return True
    return top_level in sys.stdlib_module_names


class replay:
    """Context manager that records and replays function call results."""

    def __init__(
        self,
        identifier: str,
        storage: MemoStorage = DEFAULT_STORAGE,
        serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
        exclude: list[Callable[..., Any]] | None = None,
    ):
        self.identifier = identifier
        self.storage = storage
        if isinstance(serializer, Serializer):
            self.serializer: tuple[Serializer, ...] = (serializer,)
        else:
            self.serializer = tuple(serializer)
        self._exclude_ids: set[int] = {id(fn) for fn in (exclude or [])}
        self._seq: int = 0
        self._originals: dict[str, Any] = {}
        self._frame_globals: dict[str, Any] | None = None
        self._inputs = Inputs()

    def __enter__(self) -> replay:
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        self._frame_globals = frame.f_back.f_globals
        self._patch()
        return self

    def __exit__(self, *args: Any) -> None:
        self._unpatch()

    async def __aenter__(self) -> replay:
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        self._frame_globals = frame.f_back.f_globals
        self._patch()
        return self

    async def __aexit__(self, *args: Any) -> None:
        self._unpatch()

    def _should_patch(self, obj: Any) -> bool:
        if not callable(obj):
            return False
        if id(obj) in self._exclude_ids:
            return False
        module = getattr(obj, "__module__", None)
        if module is None:
            return False
        if module.startswith("stickynote"):
            return False
        return not _is_stdlib_module(module)

    def _patch(self) -> None:
        assert self._frame_globals is not None
        for name, obj in list(self._frame_globals.items()):
            if self._should_patch(obj):
                self._originals[name] = obj
                if inspect.iscoroutinefunction(obj):
                    self._frame_globals[name] = self._make_async_wrapper(name, obj)
                else:
                    self._frame_globals[name] = self._make_sync_wrapper(name, obj)

    def _unpatch(self) -> None:
        if self._frame_globals is not None:
            for name, obj in self._originals.items():
                self._frame_globals[name] = obj
            self._originals.clear()
            self._frame_globals = None
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _build_key(
        self,
        name: str,
        seq: int,
        original: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> str:
        qualname = getattr(original, "__qualname__", name)
        try:
            args_hash = self._inputs.compute(original, args, kwargs)
        except (ValueError, TypeError):
            args_hash = "unhashable"
        raw_key = f"{self.identifier}:{seq}:{qualname}:{args_hash}"
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def _compute_source_hash(self, func: Callable[..., Any]) -> str:
        """Compute SHA-256 hash of function source code."""
        try:
            source = inspect.getsource(func)
            return hashlib.sha256(source.encode()).hexdigest()
        except (OSError, TypeError):
            return ""

    def _serialize_value(self, value: Any) -> str:
        """Serialize a value using the first successful serializer in the chain."""
        exceptions: list[Exception] = []
        for s in self.serializer:
            try:
                return s.serialize(value)
            except Exception as e:
                exceptions.append(e)
        raise ExceptionGroup(
            "All serializers failed to serialize the result.", exceptions
        )

    def _deserialize_value(self, data: str) -> Any:
        """Deserialize a value using the first successful serializer in the chain."""
        exceptions: list[Exception] = []
        for s in self.serializer:
            try:
                return s.deserialize(data)
            except Exception as e:
                exceptions.append(e)
        raise ExceptionGroup(
            "All serializers failed to deserialize the result.", exceptions
        )

    def _read_cache(self, key: str) -> dict[str, str] | None:
        """Read and parse a cache envelope. Returns the envelope dict or None."""
        if not self.storage.exists(key):
            return None
        try:
            raw = self.storage.get(key)
        except MissingMemoError:
            return None
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(envelope, dict) and all(
            k in envelope for k in ("type", "data", "source_hash")
        ):
            return envelope
        return None

    async def _read_cache_async(self, key: str) -> dict[str, str] | None:
        """Async version of _read_cache."""
        if not await self.storage.exists_async(key):
            return None
        try:
            raw = await self.storage.get_async(key)
        except MissingMemoError:
            return None
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(envelope, dict) and all(
            k in envelope for k in ("type", "data", "source_hash")
        ):
            return envelope
        return None

    def _write_cache(self, key: str, value: Any, type_: str, source_hash: str) -> None:
        """Serialize value, wrap in JSON envelope, write to storage."""
        data = self._serialize_value(value)
        envelope = json.dumps({"type": type_, "data": data, "source_hash": source_hash})
        self.storage.set(key, envelope)

    async def _write_cache_async(
        self, key: str, value: Any, type_: str, source_hash: str
    ) -> None:
        """Async version of _write_cache."""
        data = self._serialize_value(value)
        envelope = json.dumps({"type": type_, "data": data, "source_hash": source_hash})
        await self.storage.set_async(key, envelope)

    def _make_sync_wrapper(
        self, name: str, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            seq = self._next_seq()
            key = self._build_key(name, seq, original, args, kwargs)

            envelope = self._read_cache(key)
            if envelope is not None:
                return self._deserialize_value(envelope["data"])

            source_hash = self._compute_source_hash(original)
            result = original(*args, **kwargs)
            self._write_cache(key, result, "value", source_hash)
            return result

        return wrapper

    def _make_async_wrapper(
        self, name: str, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        @functools.wraps(original)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            seq = self._next_seq()
            key = self._build_key(name, seq, original, args, kwargs)

            envelope = await self._read_cache_async(key)
            if envelope is not None:
                return self._deserialize_value(envelope["data"])

            source_hash = self._compute_source_hash(original)
            result = await original(*args, **kwargs)
            await self._write_cache_async(key, result, "value", source_hash)
            return result

        return wrapper
