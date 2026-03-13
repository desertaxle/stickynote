# Replay v2: Durable Execution via Memoization

**Date:** 2026-03-13
**Status:** Draft

## Problem

Stickynote's `replay` context manager records and replays function call results within a scope. This works for single-process crash recovery and development caching, but falls short for distributed use cases where execution may resume on a different machine.

The primary motivating use case is FastMCP integration: MCP server tool handlers that call `ctx.elicit()` or `ctx.sample()` may suspend execution waiting for a client response. When the server is load-balanced, the response may arrive at a different machine. That machine needs to reconstruct the handler's state and continue from where it left off.

## Design Principles

- **General-purpose, not MCP-specific.** Stickynote provides durable execution primitives. FastMCP integrates them. Stickynote knows nothing about elicitation, sampling, or MCP.
- **Magic by default, explicit when needed.** Globals patching gives zero-config convenience. `@replayable` gives framework authors precise control.
- **Broad compatibility.** Python 3.10+. Sync and async. No AST transformation, no bytecode manipulation.
- **Deterministic call order required.** Replay relies on a sequence counter to build cache keys. Calls within a replay session must execute in the same order on every run. Concurrent calls (e.g., `asyncio.gather` of replayable functions) are not supported and will produce undefined cache key ordering.

## Architecture

### ContextVar-Based Replay Context

The current implementation patches functions in the caller's frame globals. This works for direct calls to global-scoped functions but cannot intercept method calls (like `ctx.elicit()`), closures, or functions not visible in the caller's frame.

Replay v2 adds a `ContextVar[replay | None]` that holds the active replay session. Two mechanisms use it:

1. **Globals patching (existing, unchanged).** The `with replay(...)` context manager patches the caller's frame globals with wrappers. These wrappers use the ContextVar to find the active session's sequence counter, storage, and serializer chain. This is the "magic" path for simple scripts and pipelines.

2. **`@replayable` decorator (new).** Any callable can be decorated with `@replayable`. When called inside a `replay` context (detected via the ContextVar), the decorator intercepts the call and performs cache lookup/store. When called outside a replay context, it's a pass-through. This works for functions, methods, closures — anything callable.

Both mechanisms share the same ContextVar, so a `@replayable` function called inside a `with replay(...)` block participates in the same session with the same sequence counter.

**Limitation:** The `exclude` parameter on `replay()` only applies to globals-patched functions. A `@replayable`-decorated function always participates in replay when a context is active. To conditionally bypass replay for a `@replayable` function, call the underlying function directly via `func.__wrapped__`.

```python
from stickynote import replay, replayable

@replayable
async def fetch_data(source: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.example.com/{source}")
        return resp.json()

# Both paths work together:
async with replay("pipeline", storage=redis_storage):
    data = await fetch_data("users")      # @replayable, uses ContextVar
    result = await process(data)           # globals-patched, uses same ContextVar
```

### Suspension Protocol

A wrapped function can signal "I don't have a result yet, pause everything" by raising `SuspendExecution`. This is the mechanism that enables distributed resumption.

```python
class SuspendExecution(BaseException):
    """Raised by a wrapped function to signal that execution should pause.

    The `key` and `source_hash` attributes are set by the replay wrapper
    before re-raising, not by the code that constructs the exception.
    """
    def __init__(self, reason: str = ""):
        super().__init__(reason)
        self.key: str | None = None          # Set by replay wrapper (transport-safe string)
        self.source_hash: str | None = None  # Set by replay wrapper (transport-safe string)
```

`SuspendExecution` inherits from `BaseException` (not `Exception`) to avoid being caught by broad `except Exception` handlers in user code. The `key` attribute is `None` when first raised by user/framework code; the replay wrapper sets it to the current cache key before re-raising.

**Flow:**

1. Wrapped function is called, cache miss.
2. Original function executes and raises `SuspendExecution`.
3. The **innermost** replay wrapper catches it and sets `exc.key` to the current cache key **only if `exc.key is None`**. This prevents outer wrappers from overwriting the key when `@replayable` calls are nested inside globals-patched functions. The wrapper also sets `self._suspended = True` on the replay session and **pre-registers the pending key** in the key list (writing it to `{identifier}:__keys__` in storage). This ensures cleanup can find the entry even though no cached value exists yet. The wrapper also attaches `exc.source_hash` (SHA-256 of the suspended function's source). Both `key` and `source_hash` are plain strings — transport-safe for persistence across machines.
4. Outer wrappers see `exc.key is not None`, so they propagate without modification.
5. `SuspendExecution` propagates up to the caller (the framework catches it).
6. Later, the framework stores the result using `replay.complete_suspended()` (see below).
7. On resume (possibly a different machine): a new `replay` context is created with the same identifier and shared storage. Re-execution from the top begins. All prior calls hit cache. The formerly-suspended call now has a cached result. Execution continues.

**Suspension detection in `__aexit__`/`__exit__`:** The framework typically catches `SuspendExecution` inside the `with replay(...)` block, so `__aexit__` sees a normal exit (no exception). The replay session uses the `_suspended` flag (set in step 3) rather than the exception type to detect suspension. When `_suspended` is `True`, the session skips writing the key list on exit (since the session is incomplete and will be resumed later).

**Note on checkpoints:** The replay engine does not store or use an explicit checkpoint sequence number. The cache entries themselves define the fast-path — on resume, each call either hits cache (prior work) or misses (new work). No additional checkpoint metadata is needed because the memoization-based approach naturally handles partial progress: cached calls replay, uncached calls execute fresh.

**Completing a suspended call:** When the framework receives the response for a suspended call, it must store the result in the correct envelope format. The framework provides `storage` and `serializer` explicitly — it already knows these because it configures the `replay` session on both machines with the same settings:

```python
@classmethod
async def complete_suspended_async(
    cls,
    key: str,
    value: Any,
    storage: MemoStorage,
    serializer: Serializer | Iterable[Serializer] = DEFAULT_SERIALIZER_CHAIN,
    source_hash: str = "",
) -> None:
    """Store a result for a previously suspended call, in the correct envelope format."""
```

Only `key` and `source_hash` need to cross the wire (both are plain strings from the `SuspendExecution` exception). The framework is responsible for using the same `storage` and `serializer` configuration on the completing machine as on the suspending machine — this is natural since the framework configures both sides. A sync `complete_suspended()` variant is also provided.

**FastMCP integration example:**

```python
# Inside FastMCP's tool execution engine (not user code):
async def run_tool_handler(handler, request, ctx):
    storage = redis_storage  # shared across machines
    identifier = request.id  # unique per request

    async with replay(identifier, storage=storage):
        try:
            return await handler(request, ctx)
        except SuspendExecution as exc:
            # Persist only the transport-safe strings
            await store_pending(request.id, exc.key, exc.source_hash)
            return PendingResponse()

# When the elicitation response arrives (possibly different machine):
async def handle_elicitation_response(request_id, response):
    key, source_hash = await load_pending(request_id)
    # Framework provides storage/serializer — same config as the replay session
    await replay.complete_suspended_async(
        key=key,
        value=response,
        storage=redis_storage,
        source_hash=source_hash,
    )
    # Re-run the handler — replay will fast-path through cached calls
    await run_tool_handler(handler, original_request, ctx)

# The user's tool handler is completely unaware of replay:
@mcp.tool
async def my_tool(query: str, ctx: Context = CurrentContext()) -> str:
    data = await fetch_data(query)
    pref = await ctx.elicit("Format?", response_type=Format)
    return await process(data, pref.data)
```

### Exception Recording

Currently replay only caches successful return values. Replay v2 also caches exceptions. If a function raised on the first run, the second run raises the same exception without re-executing.

**Storage format:** Cached entries use an envelope to distinguish values from exceptions and to support per-entry validation. The envelope is a JSON object wrapping the serialized payload:

```json
{"type": "value", "data": "<serialized>", "source_hash": "<sha256>"}
{"type": "exception", "data": "<serialized>", "source_hash": "<sha256>"}
```

The `data` field contains the output of whichever serializer in the chain succeeded at write time. The `source_hash` is the SHA-256 hash of the function's source code at the time the entry was written. The envelope itself is always JSON.

**Deserialization** uses the existing chain-based approach: try each serializer in the configured chain until one succeeds. This is the same fallback mechanism already used by `@memoize`. The framework is responsible for configuring the same serializer chain on both the suspending and resuming machines.

The wrapper logic becomes:

```
1. Check cache → hit?
   a. Envelope type "value" → deserialize and return
   b. Envelope type "exception" → deserialize and raise
2. Cache miss → execute original
   a. Returns → cache as {"type": "value", ...}, return
   b. Raises SuspendExecution (BaseException) → don't cache, propagate
   c. Raises Exception subclass → cache as {"type": "exception", ...}, re-raise
   d. Raises other BaseException (KeyboardInterrupt, SystemExit, etc.) → don't cache, propagate
```

Only `Exception` subclasses are cached. `BaseException` subclasses that are not `Exception` (including `SuspendExecution`, `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`) are never cached — they represent control flow or process-level signals, not function-level failures.

Exceptions are serialized using the same serializer chain. JSON typically fails for exceptions, so pickle/cloudpickle handles them via the fallback chain.

**Configuration:** `cache_exceptions=True` parameter on `replay()` (default `True`). Set to `False` if you want failed calls to retry on replay rather than replaying the failure.

**Backwards compatibility:** The envelope format is a breaking change to the storage format. Existing cached values (plain serialized strings without an envelope) will fail to parse as JSON envelopes and will be treated as cache misses, causing re-execution. This is acceptable for a v2 release.

### Deterministic Time

Code between cached calls re-executes on replay. If that code captures timestamps, the replayed run produces different values, breaking downstream cache keys and making replays non-deterministic.

**Configuration:** `deterministic_time=False` parameter on `replay()` (opt-in).

When enabled:
- On first run: record the real time at each call to a time function, keyed by a time-specific sequence counter, stored alongside other cached values.
- On replay: return the recorded times in the same order.

**Patching mechanism:** The `datetime` and `time` module names in the caller's frame globals are replaced with proxy objects that intercept time-reading calls:

- The `datetime` name is replaced with a proxy module whose `datetime` attribute is a subclass that overrides `now()` and `utcnow()` class methods. All other attributes delegate to the real `datetime` module.
- The `time` name is replaced with a proxy module that overrides `time()` and `monotonic()` functions. All other attributes delegate to the real `time` module.

**Scope limitations:** The proxy approach only patches the caller's frame globals. This means:

- Time reads inside `@replayable` functions in **other modules** are **not** frozen — the proxy doesn't reach into those modules' globals.
- The `from datetime import datetime` or `from time import time` import style places the class/function directly in globals rather than the module, so the proxy cannot intercept attribute access.

In practice, `deterministic_time` is useful for glue code in the caller's module (timestamps assigned between cached calls). For cross-module time determinism, stickynote provides an explicit API:

```python
from stickynote import replay_time

# Returns recorded time during replay, real time otherwise.
# Works from any module, any import style.
timestamp = replay_time.now(timezone.utc)
elapsed = replay_time.monotonic()
```

`replay_time` checks the ContextVar for an active session and delegates to the time recording/replay mechanism. `@replayable` functions that need deterministic timestamps should use `replay_time` instead of `datetime`/`time` directly.

**What does NOT get patched:** `time.sleep`, `asyncio.sleep` — these are side effects, not time reads.

**Why opt-in:** Deterministic time is powerful but surprising. A framework like FastMCP could enable it by default for tool handlers, but general users should consciously choose it.

### Observability Hooks

```python
class ReplayHooks:
    """Base class for replay observability hooks. Override only the methods you need."""
    def on_cache_hit(self, key: str, seq: int, func_name: str) -> None: ...
    def on_cache_miss(self, key: str, seq: int, func_name: str) -> None: ...
    def on_suspend(self, key: str, seq: int, func_name: str) -> None: ...
    def on_resume(self, identifier: str, seq: int) -> None: ...
    def on_exception_cached(self, key: str, seq: int, func_name: str, exc: BaseException) -> None: ...
```

`ReplayHooks` is a base class (not a Protocol) with no-op default implementations. Users subclass it and override only the methods they care about. The replay internals call hook methods directly without guards.

**Configuration:** `hooks` parameter on `replay()`.

```python
class LoggingHooks(ReplayHooks):
    def on_cache_hit(self, key, seq, func_name):
        logger.info(f"Replay hit: {func_name} (seq={seq})")

    def on_suspend(self, key, seq, func_name):
        logger.warning(f"Suspending at: {func_name} (seq={seq})")

async with replay("pipeline", storage=storage, hooks=LoggingHooks()):
    ...
```

### Side-Effect Guards (Deferred)

Suppressing `print`/`logging` during replay would require patching builtins and tracking whether the current execution has passed the checkpoint. The complexity is high and the benefit is low for the primary use case (MCP handlers are short).

Instead, expose an `is_replaying()` function that checks the ContextVar. It returns `True` if there is an active replay session **and** no cache miss has occurred yet in the current session (i.e., all wrapped calls so far have been cache hits). Once any wrapped call results in a cache miss (including a miss that leads to `SuspendExecution`), `is_replaying()` returns `False` for the remainder of the session. If there is no active replay session, it returns `False`.

**Behavior across runs:**
- **First run (no cached data):** The very first wrapped call is a cache miss, so `is_replaying()` is `False` for the entire run.
- **Resume after suspension:** All prior calls hit cache, so `is_replaying()` is `True`. The formerly-suspended call now hits cache too (response was stored by the framework). `is_replaying()` remains `True` until a genuinely new call is reached.
- **Full replay (all calls cached):** `is_replaying()` is `True` for the entire run.

```python
from stickynote import is_replaying

if not is_replaying():
    logger.info(f"Fetched {len(data)} records")
```

### Source Hash Validation

Validation happens **per cache entry at read time**, not at session exit. Each cache envelope includes the source hash of the function that produced it:

```json
{"type": "value", "data": "<serialized>", "source_hash": "<sha256>"}
```

On cache hit, the wrapper computes the current function's source hash and compares it to the stored `source_hash`. If they don't match:
- `ENABLED` mode: raise `StaleReplayError` immediately, before the stale value can drive any downstream work
- `WARN` mode: log a warning, treat as cache miss (re-execute the function)
- `DISABLED` mode: return the cached value regardless

```python
class StaleReplayError(Exception):
    """Raised when a cached entry's source hash doesn't match the current function."""
```

This per-entry approach catches staleness at the point of use rather than post-hoc on session exit, preventing stale values from silently driving fresh work and side effects.

**Configuration:** `validate` parameter on `replay()` (default `True`). Accepts a `ValidationMode` enum:

```python
class ValidationMode(Enum):
    ENABLED = "enabled"    # Raise StaleReplayError on source hash mismatch
    WARN = "warn"          # Log warning, treat as cache miss
    DISABLED = "disabled"  # Skip validation entirely
```

For convenience, `validate=True` maps to `ENABLED`, `validate=False` maps to `DISABLED`. To use `WARN` mode, pass the enum value explicitly: `validate=ValidationMode.WARN`.

### Session Data Lifecycle

Replay sessions store cached results and deterministic time entries in the configured storage backend. This data accumulates over time and must be managed.

**Cleanup is the caller's responsibility.** Stickynote does not automatically delete session data because:
- In the distributed case, only the framework knows when a session is truly complete (all suspensions resolved, handler returned).
- TTL/expiry policies vary by deployment.

To support cleanup, the replay session tracks all storage keys it writes during execution in an internal `_keys: list[str]` attribute. This includes cache entry keys and any deterministic time keys. The key list is stored in storage under `{identifier}:__keys__` (SHA-256 hashed like all other special keys) and is **updated incrementally** — after each new cache write, the key list in storage is updated to include the new key.

**Crash window:** There is an inherent race between writing a cache entry and updating the key list. If the process crashes between these two operations, the orphaned entry will not appear in the key list and `cleanup()` will not delete it. This is a fundamental limitation of non-transactional storage backends. For production deployments, use TTL/expiry at the storage level (e.g., Redis key expiry) as a fallback to catch orphaned entries.

The `MemoStorage` protocol is extended with `delete` methods. This is a **breaking change** for third-party `MemoStorage` implementations — they will need to add `delete`/`delete_async` methods. The built-in backends (`MemoryStorage`, `FileStorage`, `RedisStorage`) will be updated as part of this work.

```python
class MemoStorage(Protocol):
    # ... existing methods ...

    def delete(self, key: str) -> None: ...
    async def delete_async(self, key: str) -> None: ...
```

**`delete` / `delete_async` must be idempotent.** Deleting a key that does not exist is a no-op (no exception). This is required because `cleanup()` may encounter pre-registered keys for suspended calls that were never completed (abandoned sessions, crashes before `complete_suspended()`).

The `replay` class exposes `cleanup()` and `cleanup_async()` class methods for convenience:

```python
# Delete all cached data for a session (sync)
replay.cleanup("request-123", storage=redis_storage)

# Async version
await replay.cleanup_async("request-123", storage=redis_storage)
```

`cleanup()` / `cleanup_async()` reads the key list from `{identifier}:__keys__`, deletes each key individually, then deletes the key list entry itself. Frameworks like FastMCP would call this after a tool handler completes successfully.

**Special key hashing:** Internal keys (e.g., `{identifier}:__keys__`) are SHA-256 hashed before storage, consistent with how cache entry keys are hashed. This avoids filesystem-safety issues with colons or other special characters in storage backends like `FileStorage`.

### Concurrency

Calls within a replay session must be **sequential**. The sequence counter is a simple integer that increments on each wrapped call. Concurrent calls (e.g., `asyncio.gather` of multiple `@replayable` functions within the same session) will produce non-deterministic sequence numbering, causing cache key mismatches on replay.

This is a fundamental property of the memoization-based approach: cache keys depend on call order, so call order must be deterministic.

If concurrent execution is needed, use separate `replay` sessions with distinct identifiers for each concurrent branch.

## New Public API Surface

### New exports from `stickynote`:

| Symbol | Type | Description |
|--------|------|-------------|
| `replayable` | Decorator | Marks a callable for replay participation via ContextVar |
| `SuspendExecution` | Exception (BaseException) | Raised to signal suspension; `key` and `source_hash` (transport-safe strings) set by replay wrapper |
| `StaleReplayError` | Exception | Raised when a cached entry's source hash doesn't match the current function |
| `ReplayHooks` | Base class | Subclass and override for observability callbacks |
| `ValidationMode` | Enum | `ENABLED`, `WARN`, `DISABLED` for per-entry source hash validation |
| `is_replaying()` | Function | Returns `True` if in replay mode (all calls so far are cache hits) |
| `replay_time` | Module | Explicit API for deterministic time reads from any module |

### New parameters on `replay()`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cache_exceptions` | `bool` | `True` | Cache raised exceptions alongside return values |
| `deterministic_time` | `bool` | `False` | Record and replay time function results |
| `validate` | `bool \| ValidationMode` | `True` | Per-entry source hash validation mode |
| `hooks` | `ReplayHooks \| None` | `None` | Observability callbacks |

### Extended `MemoStorage` protocol:

| Method | Description |
|--------|-------------|
| `delete(key)` | Delete a single key from storage (idempotent — missing keys are a no-op) |
| `delete_async(key)` | Async version of delete |

### New class methods on `replay`:

| Method | Description |
|--------|-------------|
| `replay.cleanup(identifier, storage)` | Deletes all cached data for a session using the stored key list |
| `replay.cleanup_async(identifier, storage)` | Async version of cleanup |
| `replay.complete_suspended(key, value, storage, serializer, source_hash)` | Stores a result for a suspended call in correct envelope format |
| `replay.complete_suspended_async(key, value, storage, serializer, source_hash)` | Async version of complete_suspended |

### Unchanged:

- `replay()` constructor: `identifier`, `storage`, `serializer`, `exclude` parameters
- `@memoize` decorator
- Storage backends: `MemoryStorage`, `FileStorage`, `RedisStorage` (updated to add `delete`/`delete_async`)
- Serializer chain: `JsonSerializer`, `PickleSerializer`, `CloudPickleSerializer`
- Python 3.10+ support, sync + async support

### Breaking changes:

- `MemoStorage` protocol gains `delete`/`delete_async` methods — third-party implementations must add these
- Storage format changes from plain serialized strings to JSON envelopes — existing cached data will be treated as cache misses
