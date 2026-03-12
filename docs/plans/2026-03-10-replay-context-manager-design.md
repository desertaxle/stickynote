# Replay Context Manager Design

## Overview

A context manager that intercepts function calls within its block, caching their return values. On re-invocation with the same identifier, cached values are returned instead of executing the functions. This enables pausing and resuming execution across processes.

## API

```python
from stickynote import replay

with replay("etl-pipeline"):
    data = fetch_data("users")
    cleaned = clean(data)
    result = transform(cleaned)
    save(result)
```

First run: all functions execute normally, return values are cached under the `"etl-pipeline"` namespace. Second run (same or different process): cached values are returned. If a previous run crashed mid-execution, cached calls return cached values and uncached calls execute normally (seamless transition).

Constructor accepts the same options as `memoize`:

```python
with replay(
    "etl-pipeline",
    storage=RedisStorage(...),
    serializer=JSONSerializer(),
    exclude=[save],  # never cache these, always execute
):
    ...
```

Supports both sync and async:

```python
async with replay("etl-pipeline"):
    data = await fetch_data()
    await save(await process(data))
```

## Patching Mechanism

On `__enter__` / `__aenter__`:

1. Capture the calling frame via `inspect.currentframe().f_back`
2. Scan `frame.f_globals` for callable objects
3. Filter out builtins, stdlib (`sys.stdlib_module_names`), and stickynote internals via `callable.__module__`
4. Replace each qualifying callable with a cache-aware wrapper
5. Store originals for restoration

On `__exit__` / `__aexit__`:

- Restore all original callables to `frame.f_globals`

### What gets patched

- Module-level functions defined in user code
- Imported functions from user packages
- Classes (constructor calls)

### What does NOT get patched

- Builtins (`len`, `print`, `range`, etc.)
- Stdlib (`os.path.join`, `json.loads`, etc.)
- Methods called on objects (method resolution happens at attribute access, not via globals)
- Lambdas or functions assigned to local variables
- Anything in the `exclude` list

### Patching depth

Shallow only — callables visible in the `with` block's `f_globals`. Nested calls inside those functions are not individually cached. If a top-level function is a cache miss, it re-executes entirely including its internal calls.

## Cache Key Strategy

Each call gets a composite key from:

1. **Replay identifier** — string passed to `replay()` (e.g. `"etl-pipeline"`)
2. **Call site** — `filename:lineno` from the caller's stack frame
3. **Sequence counter** — per-call-site counter, handles loops
4. **Function identity** — the function's qualified name
5. **Arguments** — hash of args/kwargs (reusing stickynote's `Inputs` key strategy)

Example for a loop:

```python
with replay("etl-pipeline"):
    for user_id in [1, 2, 3]:
        fetch_user(user_id)
```

Produces three keys:
- `etl-pipeline:app.py:4:1:fetch_user:<hash of (1,)>`
- `etl-pipeline:app.py:4:2:fetch_user:<hash of (2,)>`
- `etl-pipeline:app.py:4:3:fetch_user:<hash of (3,)>`

Call-site is the primary identifier; sequence counter is a tiebreaker for loops. Counter resets on each entry to the context manager.

**Constraint:** Assumes deterministic control flow. If call order changes between runs, sequence counters won't align — results in cache misses (safe but inefficient), not incorrect values.

## Wrapper Function

```python
def make_wrapper(self, name, original):
    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        frame = inspect.currentframe().f_back
        call_site = f"{frame.f_code.co_filename}:{frame.f_lineno}"

        self._call_counter[call_site] = self._call_counter.get(call_site, 0) + 1
        seq = self._call_counter[call_site]

        key = self._build_key(name, call_site, seq, original, args, kwargs)

        with MemoBlock(key=key, storage=self.storage, serializer=self.serializer) as memo:
            if memo.hit:
                return memo.value
            result = original(*args, **kwargs)
            memo.stage(result)
            return result

    return wrapper
```

For async callables (detected via `inspect.iscoroutinefunction`), an async wrapper using `AsyncMemoBlock` is generated instead.

If the original raises an exception, nothing is staged — the exception propagates, and the next replay re-executes that call.

## Module Structure

New file: `stickynote/replay.py`

Reuses existing infrastructure:
- `MemoBlock` / `AsyncMemoBlock` for cache read/write
- `MemoStorage` backends (file, Redis)
- `Serializer` chain
- `Inputs` key strategy for argument hashing

Public API addition to `stickynote/__init__.py`:

```python
from .memoize import memoize
from .replay import replay

__all__ = ["memoize", "replay"]
```

## Testing

- Basic record/replay cycle (run twice, second returns cached)
- Async record/replay cycle
- Loop handling (sequence counter produces distinct keys)
- Crash recovery (partial cache, seamless transition on re-run)
- `exclude` parameter
- Builtins/stdlib are not patched
- Globals are properly restored on exit (including on exception)
