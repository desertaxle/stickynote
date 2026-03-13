from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import sys
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from enum import Enum
from typing import Any

from exceptiongroup import ExceptionGroup

from stickynote.key_strategies import Inputs
from stickynote.serializers import DEFAULT_SERIALIZER_CHAIN, Serializer
from stickynote.storage import DEFAULT_STORAGE, MemoStorage
from stickynote.storage.base import MissingMemoError

logger: logging.Logger = logging.getLogger("stickynote.replay")


class SuspendExecution(BaseException):
    """Raised by a wrapped function to signal that execution should pause.

    The ``key`` and ``source_hash`` attributes are set by the replay wrapper
    before re-raising, not by the code that constructs the exception.
    """

    def __init__(self, reason: str = ""):
        super().__init__(reason)
        self.key: str | None = None
        self.source_hash: str | None = None


class ValidationMode(Enum):
    ENABLED = "enabled"
    WARN = "warn"
    DISABLED = "disabled"


class StaleReplayError(Exception):
    """Raised when a cached entry's source hash doesn't match the current function."""


class ReplayHooks:
    """Base class for replay observability hooks. Override only the methods you need."""

    def on_cache_hit(self, key: str, seq: int, func_name: str) -> None: ...
    def on_cache_miss(self, key: str, seq: int, func_name: str) -> None: ...
    def on_suspend(self, key: str, seq: int, func_name: str) -> None: ...
    def on_resume(self, identifier: str, cached_keys: int) -> None: ...
    def on_exception_cached(
        self, key: str, seq: int, func_name: str, exc: BaseException
    ) -> None: ...


_replay_context: ContextVar[replay | None] = ContextVar("_replay_context", default=None)


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
        validate: bool | ValidationMode = True,
        cache_exceptions: bool = True,
        hooks: ReplayHooks | None = None,
        deterministic_time: bool = False,
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
        self._cache_exceptions = cache_exceptions
        self._hooks = hooks
        self._context_token: Any = None
        self._all_hits: bool = True
        self._keys: list[str] = []
        self._suspended: bool = False
        self._deterministic_time = deterministic_time
        self._time_seq: int = 0

        if isinstance(validate, bool):
            self._validate = (
                ValidationMode.ENABLED if validate else ValidationMode.DISABLED
            )
        else:
            self._validate = validate

    def _next_time_seq(self) -> int:
        self._time_seq += 1
        return self._time_seq

    def _time_key(self, seq: int) -> str:
        raw = f"{self.identifier}:__time__:{seq}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _record_time(self, seq: int, value: float | str) -> None:
        key = self._time_key(seq)
        self.storage.set(key, json.dumps(value))
        self._track_key(key)

    def _replay_time(self) -> tuple[int, float | str | None]:
        seq = self._next_time_seq()
        key = self._time_key(seq)
        if not self.storage.exists(key):
            return seq, None
        try:
            raw = self.storage.get(key)
            return seq, json.loads(raw)
        except (MissingMemoError, json.JSONDecodeError):
            return seq, None

    def _keys_storage_key(self) -> str:
        """Compute the storage key for the session's key list."""
        return hashlib.sha256(f"{self.identifier}:__keys__".encode()).hexdigest()

    def _track_key(self, key: str) -> None:
        """Track a key and update the key list in storage."""
        self._keys.append(key)
        keys_key = self._keys_storage_key()
        self.storage.set(keys_key, json.dumps(self._keys))

    async def _track_key_async(self, key: str) -> None:
        """Async version of _track_key."""
        self._keys.append(key)
        keys_key = self._keys_storage_key()
        await self.storage.set_async(keys_key, json.dumps(self._keys))

    def _load_existing_keys(self) -> None:
        """Load existing key list from storage if resuming a session."""
        keys_key = self._keys_storage_key()
        if self.storage.exists(keys_key):
            try:
                self._keys = json.loads(self.storage.get(keys_key))
                if self._hooks is not None and self._keys:
                    self._hooks.on_resume(self.identifier, len(self._keys))
            except (MissingMemoError, json.JSONDecodeError):
                self._keys = []
        else:
            self._keys = []

    async def _load_existing_keys_async(self) -> None:
        """Async version of _load_existing_keys."""
        keys_key = self._keys_storage_key()
        if await self.storage.exists_async(keys_key):
            try:
                self._keys = json.loads(await self.storage.get_async(keys_key))
                if self._hooks is not None and self._keys:
                    self._hooks.on_resume(self.identifier, len(self._keys))
            except (MissingMemoError, json.JSONDecodeError):
                self._keys = []
        else:
            self._keys = []

    @classmethod
    def cleanup(cls, identifier: str, storage: MemoStorage) -> None:
        """Delete all cached data for a session using the stored key list."""
        keys_key = hashlib.sha256(f"{identifier}:__keys__".encode()).hexdigest()
        if not storage.exists(keys_key):
            return
        try:
            key_list = json.loads(storage.get(keys_key))
        except (MissingMemoError, json.JSONDecodeError):
            return
        for key in key_list:
            storage.delete(key)
        storage.delete(keys_key)

    @classmethod
    async def cleanup_async(cls, identifier: str, storage: MemoStorage) -> None:
        """Async version of cleanup."""
        keys_key = hashlib.sha256(f"{identifier}:__keys__".encode()).hexdigest()
        if not await storage.exists_async(keys_key):
            return
        try:
            key_list = json.loads(await storage.get_async(keys_key))
        except (MissingMemoError, json.JSONDecodeError):
            return
        for key in key_list:
            await storage.delete_async(key)
        await storage.delete_async(keys_key)

    @classmethod
    def complete_suspended(
        cls,
        key: str,
        value: Any,
        storage: MemoStorage,
        serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
        source_hash: str = "",
    ) -> None:
        """Store a result for a previously suspended call, in the correct envelope format."""
        if isinstance(serializer, Serializer):
            serializer_chain: tuple[Serializer, ...] = (serializer,)
        else:
            serializer_chain = tuple(serializer)

        exceptions: list[Exception] = []
        for s in serializer_chain:
            try:
                data = s.serialize(value)
                break
            except Exception as e:
                exceptions.append(e)
        else:
            raise ExceptionGroup(
                "All serializers failed to serialize the result.", exceptions
            )

        envelope = json.dumps(
            {"type": "value", "data": data, "source_hash": source_hash}
        )
        storage.set(key, envelope)

    @classmethod
    async def complete_suspended_async(
        cls,
        key: str,
        value: Any,
        storage: MemoStorage,
        serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
        source_hash: str = "",
    ) -> None:
        """Async version of complete_suspended."""
        if isinstance(serializer, Serializer):
            serializer_chain: tuple[Serializer, ...] = (serializer,)
        else:
            serializer_chain = tuple(serializer)

        exceptions: list[Exception] = []
        for s in serializer_chain:
            try:
                data = s.serialize(value)
                break
            except Exception as e:
                exceptions.append(e)
        else:
            raise ExceptionGroup(
                "All serializers failed to serialize the result.", exceptions
            )

        envelope = json.dumps(
            {"type": "value", "data": data, "source_hash": source_hash}
        )
        await storage.set_async(key, envelope)

    def __enter__(self) -> replay:
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        self._frame_globals = frame.f_back.f_globals
        self._context_token = _replay_context.set(self)
        self._load_existing_keys()
        self._patch()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._unpatch()
        if self._context_token is not None:
            _replay_context.reset(self._context_token)
            self._context_token = None
        if isinstance(exc_val, SuspendExecution) and not self._suspended:
            # SuspendExecution raised from an unpatched (local) function — handle here
            if exc_val.key is None:
                seq = self._next_seq()
                key = hashlib.sha256(
                    f"{self.identifier}:{seq}:__suspend__".encode()
                ).hexdigest()
                exc_val.key = key
                exc_val.source_hash = ""
            self._track_key(exc_val.key)
            self._suspended = True
            if self._hooks is not None:
                self._hooks.on_suspend(exc_val.key, self._seq, "__suspend__")

    async def __aenter__(self) -> replay:
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        self._frame_globals = frame.f_back.f_globals
        self._context_token = _replay_context.set(self)
        await self._load_existing_keys_async()
        self._patch()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._unpatch()
        if self._context_token is not None:
            _replay_context.reset(self._context_token)
            self._context_token = None
        if isinstance(exc_val, SuspendExecution) and not self._suspended:
            # SuspendExecution raised from an unpatched (local) function — handle here
            if exc_val.key is None:
                seq = self._next_seq()
                key = hashlib.sha256(
                    f"{self.identifier}:{seq}:__suspend__".encode()
                ).hexdigest()
                exc_val.key = key
                exc_val.source_hash = ""
            await self._track_key_async(exc_val.key)
            self._suspended = True
            if self._hooks is not None:
                self._hooks.on_suspend(exc_val.key, self._seq, "__suspend__")

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
        self._time_seq = 0

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
        """Serialize value, wrap in JSON envelope, write to storage, track key."""
        data = self._serialize_value(value)
        envelope = json.dumps({"type": type_, "data": data, "source_hash": source_hash})
        self.storage.set(key, envelope)
        self._track_key(key)

    async def _write_cache_async(
        self, key: str, value: Any, type_: str, source_hash: str
    ) -> None:
        """Async version of _write_cache."""
        data = self._serialize_value(value)
        envelope = json.dumps({"type": type_, "data": data, "source_hash": source_hash})
        await self.storage.set_async(key, envelope)
        await self._track_key_async(key)

    def _validate_entry(
        self, envelope: dict[str, str], source_hash: str, func_name: str
    ) -> bool:
        """Validate source hash of a cache entry. Returns True if entry is valid.

        In ENABLED mode, raises StaleReplayError on mismatch.
        In WARN mode, logs a warning and returns False (treat as cache miss).
        In DISABLED mode, always returns True.
        """
        if self._validate == ValidationMode.DISABLED:
            return True
        stored_hash = envelope.get("source_hash", "")
        if not stored_hash or not source_hash:
            return True
        if stored_hash == source_hash:
            return True
        if self._validate == ValidationMode.ENABLED:
            raise StaleReplayError(
                f"Cached entry for {func_name!r} has stale source hash "
                f"(stored={stored_hash[:8]}..., current={source_hash[:8]}...)"
            )
        # WARN mode
        logger.warning(
            "Stale cache entry for %r (source hash mismatch), re-executing",
            func_name,
        )
        return False

    def _make_sync_wrapper(
        self, name: str, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            seq = self._next_seq()
            key = self._build_key(name, seq, original, args, kwargs)
            source_hash = self._compute_source_hash(original)
            func_name = getattr(original, "__qualname__", name)

            envelope = self._read_cache(key)
            if envelope is not None and self._validate_entry(
                envelope, source_hash, func_name
            ):
                if self._hooks is not None:
                    self._hooks.on_cache_hit(key, seq, func_name)
                value = self._deserialize_value(envelope["data"])
                if envelope["type"] == "exception":
                    raise value
                return value

            if self._hooks is not None:
                self._hooks.on_cache_miss(key, seq, func_name)
            self._all_hits = False

            try:
                result = original(*args, **kwargs)
            except SuspendExecution as exc:
                if exc.key is None:
                    exc.key = key
                    exc.source_hash = source_hash
                self._suspended = True
                self._track_key(key)  # Pre-register pending key
                if self._hooks is not None:
                    self._hooks.on_suspend(key, seq, func_name)
                raise
            except Exception as exc:
                if self._cache_exceptions:
                    self._write_cache(key, exc, "exception", source_hash)
                    if self._hooks is not None:
                        self._hooks.on_exception_cached(key, seq, func_name, exc)
                raise
            else:
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
            source_hash = self._compute_source_hash(original)
            func_name = getattr(original, "__qualname__", name)

            envelope = await self._read_cache_async(key)
            if envelope is not None and self._validate_entry(
                envelope, source_hash, func_name
            ):
                if self._hooks is not None:
                    self._hooks.on_cache_hit(key, seq, func_name)
                value = self._deserialize_value(envelope["data"])
                if envelope["type"] == "exception":
                    raise value
                return value

            if self._hooks is not None:
                self._hooks.on_cache_miss(key, seq, func_name)
            self._all_hits = False

            try:
                result = await original(*args, **kwargs)
            except SuspendExecution as exc:
                if exc.key is None:
                    exc.key = key
                    exc.source_hash = source_hash
                self._suspended = True
                await self._track_key_async(key)  # Pre-register pending key
                if self._hooks is not None:
                    self._hooks.on_suspend(key, seq, func_name)
                raise
            except Exception as exc:
                if self._cache_exceptions:
                    await self._write_cache_async(key, exc, "exception", source_hash)
                    if self._hooks is not None:
                        self._hooks.on_exception_cached(key, seq, func_name, exc)
                raise
            else:
                await self._write_cache_async(key, result, "value", source_hash)
                return result

        return wrapper


def is_replaying() -> bool:
    """Returns True if inside an active replay session where all calls so far hit cache.

    Returns False if no session is active or any cache miss has occurred.
    """
    session = _replay_context.get(None)
    if session is None:
        return False
    return session._all_hits


def replayable(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that marks a callable for replay participation via ContextVar.

    When called inside a replay context, the decorator intercepts the call and
    performs cache lookup/store. When called outside a replay context, it's a
    pass-through.
    """
    source_hash = ""
    try:
        source = inspect.getsource(func)
        source_hash = hashlib.sha256(source.encode()).hexdigest()
    except (OSError, TypeError):
        pass

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            session = _replay_context.get(None)
            if session is None:
                return await func(*args, **kwargs)

            func_name = getattr(
                func, "__qualname__", getattr(func, "__name__", repr(func))
            )
            seq = session._next_seq()
            key = session._build_key(func_name, seq, func, args, kwargs)

            envelope = await session._read_cache_async(key)
            if envelope is not None and session._validate_entry(
                envelope, source_hash, func_name
            ):
                if session._hooks is not None:
                    session._hooks.on_cache_hit(key, seq, func_name)
                value = session._deserialize_value(envelope["data"])
                if envelope["type"] == "exception":
                    raise value
                return value

            if session._hooks is not None:
                session._hooks.on_cache_miss(key, seq, func_name)
            session._all_hits = False

            try:
                result = await func(*args, **kwargs)
            except SuspendExecution as exc:
                if exc.key is None:
                    exc.key = key
                    exc.source_hash = source_hash
                session._suspended = True
                await session._track_key_async(key)  # Pre-register pending key
                if session._hooks is not None:
                    session._hooks.on_suspend(key, seq, func_name)
                raise
            except Exception as exc:
                if session._cache_exceptions:
                    await session._write_cache_async(key, exc, "exception", source_hash)
                    if session._hooks is not None:
                        session._hooks.on_exception_cached(key, seq, func_name, exc)
                raise
            else:
                await session._write_cache_async(key, result, "value", source_hash)
                return result

        async_wrapper.__wrapped__ = func
        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        session = _replay_context.get(None)
        if session is None:
            return func(*args, **kwargs)

        func_name = getattr(func, "__qualname__", getattr(func, "__name__", repr(func)))
        seq = session._next_seq()
        key = session._build_key(func_name, seq, func, args, kwargs)

        envelope = session._read_cache(key)
        if envelope is not None and session._validate_entry(
            envelope, source_hash, func_name
        ):
            if session._hooks is not None:
                session._hooks.on_cache_hit(key, seq, func_name)
            value = session._deserialize_value(envelope["data"])
            if envelope["type"] == "exception":
                raise value
            return value

        if session._hooks is not None:
            session._hooks.on_cache_miss(key, seq, func_name)
        session._all_hits = False

        try:
            result = func(*args, **kwargs)
        except SuspendExecution as exc:
            if exc.key is None:
                exc.key = key
                exc.source_hash = source_hash
            session._suspended = True
            session._track_key(key)  # Pre-register pending key
            if session._hooks is not None:
                session._hooks.on_suspend(key, seq, func_name)
            raise
        except Exception as exc:
            if session._cache_exceptions:
                session._write_cache(key, exc, "exception", source_hash)
                if session._hooks is not None:
                    session._hooks.on_exception_cached(key, seq, func_name, exc)
            raise
        else:
            session._write_cache(key, result, "value", source_hash)
            return result

    sync_wrapper.__wrapped__ = func
    return sync_wrapper
