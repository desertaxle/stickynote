# Replay Context Manager Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `replay` context manager that intercepts function calls, caches their return values, and replays cached values on re-invocation — enabling pause/resume of execution across processes.

**Architecture:** A `replay` class in `stickynote/replay.py` that monkeypatches user-defined callables in the calling frame's globals with cache-aware wrappers. Wrappers use existing `MemoBlock`/`AsyncMemoBlock` for cache read/write. Cache keys combine replay identifier, call site, sequence counter, function name, and argument hash.

**Tech Stack:** Python 3.9+, existing stickynote infrastructure (MemoBlock, MemoStorage, Serializer, Inputs key strategy)

---

### Task 1: Core replay class with basic sync record and replay

**Files:**
- Create: `stickynote/replay.py`
- Create: `tests/test_replay.py`

**Step 1: Write the failing test**

```python
# tests/test_replay.py
from stickynote.replay import replay
from stickynote.storage import MemoryStorage

call_counts: dict[str, int] = {}


def fetch_data(source: str) -> dict:
    call_counts["fetch_data"] = call_counts.get("fetch_data", 0) + 1
    return {"source": source, "data": [1, 2, 3]}


def process(data: dict) -> dict:
    call_counts["process"] = call_counts.get("process", 0) + 1
    return {"processed": True, **data}


class TestReplaySync:
    def setup_method(self):
        call_counts.clear()

    def test_basic_record_and_replay(self):
        storage = MemoryStorage()

        # First run: functions execute normally
        with replay("test-pipeline", storage=storage):
            data = fetch_data("users")
            result = process(data)

        assert data == {"source": "users", "data": [1, 2, 3]}
        assert result == {"processed": True, "source": "users", "data": [1, 2, 3]}
        assert call_counts["fetch_data"] == 1
        assert call_counts["process"] == 1

        # Second run: functions return cached values
        call_counts.clear()
        with replay("test-pipeline", storage=storage):
            data = fetch_data("users")
            result = process(data)

        assert data == {"source": "users", "data": [1, 2, 3]}
        assert result == {"processed": True, "source": "users", "data": [1, 2, 3]}
        assert call_counts.get("fetch_data", 0) == 0
        assert call_counts.get("process", 0) == 0

    def test_different_identifiers_do_not_share_cache(self):
        storage = MemoryStorage()

        with replay("pipeline-a", storage=storage):
            data = fetch_data("users")

        assert call_counts["fetch_data"] == 1

        call_counts.clear()
        with replay("pipeline-b", storage=storage):
            data = fetch_data("users")

        assert call_counts["fetch_data"] == 1  # cache miss, different identifier

    def test_different_args_produce_different_cache_entries(self):
        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage):
            data1 = fetch_data("users")
            data2 = fetch_data("orders")

        assert call_counts["fetch_data"] == 2

        call_counts.clear()
        with replay("test-pipeline", storage=storage):
            data1 = fetch_data("users")
            data2 = fetch_data("orders")

        assert call_counts.get("fetch_data", 0) == 0
        assert data1 == {"source": "users", "data": [1, 2, 3]}
        assert data2 == {"source": "orders", "data": [1, 2, 3]}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_replay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'stickynote.replay'`

**Step 3: Write the implementation**

```python
# stickynote/replay.py
from __future__ import annotations

import functools
import hashlib
import inspect
import sys
from collections.abc import Iterable
from typing import Any, Callable

from stickynote.key_strategies import Inputs
from stickynote.memoize import AsyncMemoBlock, MemoBlock
from stickynote.serializers import DEFAULT_SERIALIZER_CHAIN, Serializer
from stickynote.storage import DEFAULT_STORAGE, MemoStorage


def _is_stdlib_module(module_name: str) -> bool:
    """Check if a module name belongs to the standard library or builtins."""
    top_level = module_name.split(".")[0]

    if top_level == "builtins":
        return True

    if hasattr(sys, "stdlib_module_names"):
        # Python 3.10+
        return top_level in sys.stdlib_module_names

    # Fallback for Python 3.9
    import sysconfig

    try:
        spec = __import__("importlib.util", fromlist=["find_spec"]).find_spec(top_level)
    except (ModuleNotFoundError, ValueError):
        return True

    if spec is None or spec.origin is None:
        return True  # Built-in C module

    stdlib_path = sysconfig.get_path("stdlib")
    if stdlib_path and spec.origin.startswith(stdlib_path):
        return True

    return False


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
        self._call_counter: dict[str, int] = {}
        self._originals: dict[str, Any] = {}
        self._frame_globals: dict[str, Any] | None = None
        self._inputs = Inputs()

    def __enter__(self):
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        self._frame_globals = frame.f_back.f_globals
        self._patch()
        return self

    def __exit__(self, *args: Any) -> None:
        self._unpatch()

    async def __aenter__(self):
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
        self._call_counter.clear()

    def _build_key(
        self,
        name: str,
        call_site: str,
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
        raw_key = f"{self.identifier}:{call_site}:{seq}:{qualname}:{args_hash}"
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def _make_sync_wrapper(
        self, name: str, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            frame = inspect.currentframe()
            assert frame is not None and frame.f_back is not None
            caller = frame.f_back
            call_site = f"{caller.f_code.co_filename}:{caller.f_lineno}"

            self._call_counter[call_site] = (
                self._call_counter.get(call_site, 0) + 1
            )
            seq = self._call_counter[call_site]

            key = self._build_key(name, call_site, seq, original, args, kwargs)

            with MemoBlock(
                key=key, storage=self.storage, serializer=self.serializer
            ) as memo:
                if memo.hit:
                    return memo.value
                result = original(*args, **kwargs)
                memo.stage(result)
                return result

        return wrapper

    def _make_async_wrapper(
        self, name: str, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        @functools.wraps(original)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            frame = inspect.currentframe()
            assert frame is not None and frame.f_back is not None
            caller = frame.f_back
            call_site = f"{caller.f_code.co_filename}:{caller.f_lineno}"

            self._call_counter[call_site] = (
                self._call_counter.get(call_site, 0) + 1
            )
            seq = self._call_counter[call_site]

            key = self._build_key(name, call_site, seq, original, args, kwargs)

            async with AsyncMemoBlock(
                key=key, storage=self.storage, serializer=self.serializer
            ) as memo:
                if memo.hit:
                    return memo.value
                result = await original(*args, **kwargs)
                memo.stage(result)
                return result

        return wrapper
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_replay.py -v`
Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add stickynote/replay.py tests/test_replay.py
git commit -m "feat: add replay context manager with basic sync record/replay"
```

---

### Task 2: Stdlib/builtin filtering and exclude parameter

**Files:**
- Modify: `tests/test_replay.py`

**Step 1: Write the failing tests**

Add to `tests/test_replay.py`:

```python
import json


def save(data: dict) -> str:
    call_counts["save"] = call_counts.get("save", 0) + 1
    return json.dumps(data)


class TestReplayFiltering:
    def setup_method(self):
        call_counts.clear()

    def test_builtins_are_not_patched(self):
        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage):
            result = len([1, 2, 3])

        assert result == 3
        # len should not be in the storage (no cache entries for builtins)
        assert len(storage.cache) == 0

    def test_stdlib_is_not_patched(self):
        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage):
            result = json.dumps({"a": 1})

        assert result == '{"a": 1}'
        # json.dumps should not create cache entries
        assert len(storage.cache) == 0

    def test_exclude_prevents_caching(self):
        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage, exclude=[save]):
            result = save({"key": "value"})

        assert result == '{"key": "value"}'
        assert call_counts["save"] == 1

        call_counts.clear()
        with replay("test-pipeline", storage=storage, exclude=[save]):
            result = save({"key": "value"})

        # save should execute again because it was excluded
        assert call_counts["save"] == 1
        assert result == '{"key": "value"}'
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_replay.py::TestReplayFiltering -v`
Expected: FAIL (tests should fail if filtering is broken; if they pass, the filtering already works from Task 1)

**Step 3: Fix any issues (if tests fail)**

The implementation in Task 1 already includes `_should_patch` with stdlib/builtin filtering and exclude support. If tests pass, no changes needed. If not, fix `_should_patch`.

**Step 4: Run all tests**

Run: `uv run pytest tests/test_replay.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add tests/test_replay.py
git commit -m "test: add filtering and exclude tests for replay context manager"
```

---

### Task 3: Loop handling and crash recovery

**Files:**
- Modify: `tests/test_replay.py`

**Step 1: Write the failing tests**

Add to `tests/test_replay.py`:

```python
def fetch_user(user_id: int) -> dict:
    call_counts["fetch_user"] = call_counts.get("fetch_user", 0) + 1
    return {"id": user_id, "name": f"User {user_id}"}


class TestReplayLoopsAndRecovery:
    def setup_method(self):
        call_counts.clear()

    def test_loop_produces_distinct_cache_entries(self):
        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage):
            results = []
            for uid in [1, 2, 3]:
                results.append(fetch_user(uid))

        assert call_counts["fetch_user"] == 3
        assert results == [
            {"id": 1, "name": "User 1"},
            {"id": 2, "name": "User 2"},
            {"id": 3, "name": "User 3"},
        ]

        # Replay: all from cache
        call_counts.clear()
        with replay("test-pipeline", storage=storage):
            results = []
            for uid in [1, 2, 3]:
                results.append(fetch_user(uid))

        assert call_counts.get("fetch_user", 0) == 0
        assert results == [
            {"id": 1, "name": "User 1"},
            {"id": 2, "name": "User 2"},
            {"id": 3, "name": "User 3"},
        ]

    def test_same_function_same_args_different_calls(self):
        """Two calls to the same function with same args at different call sites."""
        storage = MemoryStorage()
        results = []

        with replay("test-pipeline", storage=storage):
            results.append(fetch_user(1))
            results.append(fetch_user(1))  # same args, different line

        assert call_counts["fetch_user"] == 2
        # Both should be cached on replay
        call_counts.clear()
        with replay("test-pipeline", storage=storage):
            replay_results = []
            replay_results.append(fetch_user(1))
            replay_results.append(fetch_user(1))

        assert call_counts.get("fetch_user", 0) == 0
        assert replay_results == results

    def test_crash_recovery_seamless_transition(self):
        """Simulate a crash: first run caches some calls, second run replays
        cached and executes uncached."""
        storage = MemoryStorage()

        # First run: only fetch_data runs, then we "crash" before process
        with replay("test-pipeline", storage=storage):
            data = fetch_data("users")
            # Simulate crash: don't call process()

        assert call_counts["fetch_data"] == 1

        # Second run: fetch_data should be cached, process should execute
        call_counts.clear()
        with replay("test-pipeline", storage=storage):
            data = fetch_data("users")
            result = process(data)

        assert call_counts.get("fetch_data", 0) == 0  # cached
        assert call_counts["process"] == 1  # executed fresh
        assert data == {"source": "users", "data": [1, 2, 3]}
        assert result == {"processed": True, "source": "users", "data": [1, 2, 3]}
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_replay.py::TestReplayLoopsAndRecovery -v`
Expected: Should pass if Task 1 implementation is correct. If any fail, debug and fix.

**Step 3: Fix any issues**

Likely no fixes needed — the sequence counter and MemoBlock miss behavior should handle these cases.

**Step 4: Run all tests**

Run: `uv run pytest tests/test_replay.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add tests/test_replay.py
git commit -m "test: add loop handling and crash recovery tests for replay"
```

---

### Task 4: Async support

**Files:**
- Modify: `tests/test_replay.py`

**Step 1: Write the failing tests**

Add to `tests/test_replay.py`:

```python
async def async_fetch_data(source: str) -> dict:
    call_counts["async_fetch_data"] = call_counts.get("async_fetch_data", 0) + 1
    return {"source": source, "data": [1, 2, 3]}


async def async_process(data: dict) -> dict:
    call_counts["async_process"] = call_counts.get("async_process", 0) + 1
    return {"processed": True, **data}


class TestReplayAsync:
    def setup_method(self):
        call_counts.clear()

    async def test_async_record_and_replay(self):
        storage = MemoryStorage()

        async with replay("async-pipeline", storage=storage):
            data = await async_fetch_data("users")
            result = await async_process(data)

        assert data == {"source": "users", "data": [1, 2, 3]}
        assert result == {"processed": True, "source": "users", "data": [1, 2, 3]}
        assert call_counts["async_fetch_data"] == 1
        assert call_counts["async_process"] == 1

        call_counts.clear()
        async with replay("async-pipeline", storage=storage):
            data = await async_fetch_data("users")
            result = await async_process(data)

        assert data == {"source": "users", "data": [1, 2, 3]}
        assert result == {"processed": True, "source": "users", "data": [1, 2, 3]}
        assert call_counts.get("async_fetch_data", 0) == 0
        assert call_counts.get("async_process", 0) == 0

    async def test_async_loop_handling(self):
        storage = MemoryStorage()

        async with replay("async-pipeline", storage=storage):
            results = []
            for uid in [1, 2, 3]:
                results.append(await async_fetch_data(str(uid)))

        assert call_counts["async_fetch_data"] == 3

        call_counts.clear()
        async with replay("async-pipeline", storage=storage):
            replay_results = []
            for uid in [1, 2, 3]:
                replay_results.append(await async_fetch_data(str(uid)))

        assert call_counts.get("async_fetch_data", 0) == 0
        assert replay_results == results

    async def test_async_crash_recovery(self):
        storage = MemoryStorage()

        async with replay("async-pipeline", storage=storage):
            data = await async_fetch_data("users")

        assert call_counts["async_fetch_data"] == 1

        call_counts.clear()
        async with replay("async-pipeline", storage=storage):
            data = await async_fetch_data("users")
            result = await async_process(data)

        assert call_counts.get("async_fetch_data", 0) == 0
        assert call_counts["async_process"] == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_replay.py::TestReplayAsync -v`
Expected: Should pass since Task 1 includes async implementation. If not, debug and fix.

**Step 3: Fix any issues**

If async wrappers aren't being generated (e.g. `iscoroutinefunction` check fails), fix `_patch`.

**Step 4: Run all tests**

Run: `uv run pytest tests/test_replay.py -v`
Expected: All 12 tests PASS

**Step 5: Commit**

```bash
git add tests/test_replay.py
git commit -m "test: add async support tests for replay context manager"
```

---

### Task 5: Edge cases, globals restoration, and public export

**Files:**
- Modify: `tests/test_replay.py`
- Modify: `stickynote/__init__.py`

**Step 1: Write the failing tests**

Add to `tests/test_replay.py`:

```python
class TestReplayEdgeCases:
    def setup_method(self):
        call_counts.clear()

    def test_globals_restored_after_normal_exit(self):
        storage = MemoryStorage()

        original_fetch = fetch_data
        with replay("test-pipeline", storage=storage):
            fetch_data("users")

        # After exiting, the original function should be restored
        assert fetch_data is original_fetch

    def test_globals_restored_after_exception(self):
        storage = MemoryStorage()

        original_fetch = fetch_data
        with pytest.raises(RuntimeError, match="boom"):
            with replay("test-pipeline", storage=storage):
                fetch_data("users")
                raise RuntimeError("boom")

        # Globals should still be restored
        assert fetch_data is original_fetch

    def test_import_from_package(self):
        from stickynote import replay as replay_import

        assert replay_import is replay
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_replay.py::TestReplayEdgeCases -v`
Expected: `test_import_from_package` will FAIL since `replay` is not yet exported from `__init__.py`

**Step 3: Update `__init__.py`**

Modify `stickynote/__init__.py`:

```python
from .memoize import memoize
from .replay import replay

__all__ = ["memoize", "replay"]
```

**Step 4: Run all tests**

Run: `uv run pytest tests/test_replay.py -v`
Expected: All 15 tests PASS

**Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: All existing tests still pass, plus 15 new replay tests

**Step 6: Run linting**

Run: `uv run ruff check stickynote/replay.py tests/test_replay.py`
Expected: No errors

**Step 7: Commit**

```bash
git add stickynote/__init__.py stickynote/replay.py tests/test_replay.py
git commit -m "feat: export replay from stickynote package and add edge case tests"
```
