import json

import pytest

from stickynote.replay import StaleReplayError, ValidationMode, replay
from stickynote.storage import MemoryStorage

call_counts: dict[str, int] = {}


def fetch_data(source: str) -> dict:
    call_counts["fetch_data"] = call_counts.get("fetch_data", 0) + 1
    return {"source": source, "data": [1, 2, 3]}


def process(data: dict) -> dict:
    call_counts["process"] = call_counts.get("process", 0) + 1
    return {"processed": True, **data}


def save(data: dict) -> str:
    call_counts["save"] = call_counts.get("save", 0) + 1
    return json.dumps(data)


def fetch_user(user_id: int) -> dict:
    call_counts["fetch_user"] = call_counts.get("fetch_user", 0) + 1
    return {"id": user_id, "name": f"User {user_id}"}


def fn_with_unhashable(lock: object) -> str:  # noqa: ARG001
    call_counts["fn_with_unhashable"] = call_counts.get("fn_with_unhashable", 0) + 1
    return "done"


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
            fetch_data("users")

        assert call_counts["fetch_data"] == 1

        call_counts.clear()
        with replay("pipeline-b", storage=storage):
            fetch_data("users")

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


class TestReplayLoopsAndRecovery:
    def setup_method(self):
        call_counts.clear()

    def test_loop_produces_distinct_cache_entries(self):
        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage):
            results = [fetch_user(uid) for uid in [1, 2, 3]]

        assert call_counts["fetch_user"] == 3
        assert results == [
            {"id": 1, "name": "User 1"},
            {"id": 2, "name": "User 2"},
            {"id": 3, "name": "User 3"},
        ]

        # Replay: all from cache
        call_counts.clear()
        with replay("test-pipeline", storage=storage):
            results = [fetch_user(uid) for uid in [1, 2, 3]]

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
            results = [await async_fetch_data(str(uid)) for uid in [1, 2, 3]]

        assert call_counts["async_fetch_data"] == 3

        call_counts.clear()
        async with replay("async-pipeline", storage=storage):
            replay_results = [await async_fetch_data(str(uid)) for uid in [1, 2, 3]]

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
            await async_process(data)

        assert call_counts.get("async_fetch_data", 0) == 0
        assert call_counts["async_process"] == 1


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
        with (
            pytest.raises(RuntimeError, match="boom"),
            replay("test-pipeline", storage=storage),
        ):
            fetch_data("users")
            raise RuntimeError("boom")

        # Globals should still be restored
        assert fetch_data is original_fetch

    def test_import_from_package(self):
        from stickynote import replay as replay_import

        assert replay_import is replay

    def test_single_serializer_accepted(self):
        from stickynote.serializers import JsonSerializer

        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage, serializer=JsonSerializer()):
            data = fetch_data("users")

        assert data == {"source": "users", "data": [1, 2, 3]}

        call_counts.clear()
        with replay("test-pipeline", storage=storage, serializer=JsonSerializer()):
            data = fetch_data("users")

        assert call_counts.get("fetch_data", 0) == 0

    def test_callable_without_module_not_patched(self):
        storage = MemoryStorage()

        # Temporarily inject a callable with no __module__ into globals
        import types

        no_module_fn = types.FunctionType(
            (lambda x: x).__code__, globals(), "no_module_fn"
        )
        no_module_fn.__module__ = None  # type: ignore[assignment]
        globals()["no_module_fn"] = no_module_fn
        try:
            with replay("test-pipeline", storage=storage):
                # no_module_fn should be skipped (not patched)
                assert globals()["no_module_fn"] is no_module_fn
        finally:
            del globals()["no_module_fn"]

    def test_builtins_not_patched(self):
        """Directly verify builtins module detection."""
        from stickynote.replay import _is_stdlib_module

        assert _is_stdlib_module("builtins") is True

    def test_unhashable_args_still_work(self):
        """Functions with args that can't be serialized use fallback key."""
        import threading

        storage = MemoryStorage()

        with replay("test-pipeline", storage=storage):
            result = fn_with_unhashable(threading.Lock())

        assert result == "done"
        assert call_counts["fn_with_unhashable"] == 1


class TestReplayEnvelopeFormat:
    def setup_method(self):
        call_counts.clear()

    def test_stores_json_envelope(self):
        storage = MemoryStorage()
        with replay("test", storage=storage):
            fetch_data("users")

        for value in storage.cache.values():
            envelope = json.loads(value)
            assert envelope["type"] == "value"
            assert "data" in envelope
            assert "source_hash" in envelope

    def test_source_hash_is_sha256_hex(self):
        storage = MemoryStorage()
        with replay("test", storage=storage):
            fetch_data("users")

        for value in storage.cache.values():
            envelope = json.loads(value)
            source_hash = envelope["source_hash"]
            assert len(source_hash) == 64
            assert all(c in "0123456789abcdef" for c in source_hash)

    def test_envelope_data_is_deserializable(self):
        from stickynote.serializers import DEFAULT_SERIALIZER_CHAIN

        storage = MemoryStorage()
        with replay("test", storage=storage):
            fetch_data("users")

        for value in storage.cache.values():
            envelope = json.loads(value)
            deserialized = None
            for s in DEFAULT_SERIALIZER_CHAIN:
                try:
                    deserialized = s.deserialize(envelope["data"])
                    break
                except Exception:
                    continue
            assert deserialized == {"source": "users", "data": [1, 2, 3]}


class TestReplayValidation:
    def setup_method(self):
        call_counts.clear()

    def test_stale_replay_error_on_source_change(self):
        """ENABLED mode raises StaleReplayError when source hash mismatches."""
        storage = MemoryStorage()

        with replay("test", storage=storage, validate=ValidationMode.ENABLED):
            fetch_data("users")

        # Tamper with the source hash in storage to simulate source change
        for key, value in storage.cache.items():
            envelope = json.loads(value)
            envelope["source_hash"] = "0" * 64
            storage.cache[key] = json.dumps(envelope)

        with (
            pytest.raises(StaleReplayError),
            replay("test", storage=storage, validate=ValidationMode.ENABLED),
        ):
            fetch_data("users")

    def test_warn_mode_treats_mismatch_as_cache_miss(self):
        """WARN mode logs and re-executes instead of raising."""
        storage = MemoryStorage()

        with replay("test", storage=storage):
            fetch_data("users")

        assert call_counts["fetch_data"] == 1

        # Tamper with the source hash
        for key, value in storage.cache.items():
            envelope = json.loads(value)
            envelope["source_hash"] = "0" * 64
            storage.cache[key] = json.dumps(envelope)

        call_counts.clear()
        with replay("test", storage=storage, validate=ValidationMode.WARN):
            fetch_data("users")

        assert call_counts["fetch_data"] == 1  # Re-executed (cache miss)

    def test_disabled_mode_ignores_mismatch(self):
        """DISABLED mode returns cached value regardless."""
        storage = MemoryStorage()

        with replay("test", storage=storage):
            data = fetch_data("users")

        # Tamper with the source hash
        for key, value in storage.cache.items():
            envelope = json.loads(value)
            envelope["source_hash"] = "0" * 64
            storage.cache[key] = json.dumps(envelope)

        call_counts.clear()
        with replay("test", storage=storage, validate=ValidationMode.DISABLED):
            data = fetch_data("users")

        assert call_counts.get("fetch_data", 0) == 0  # Cached (no validation)
        assert data == {"source": "users", "data": [1, 2, 3]}

    def test_validate_true_maps_to_enabled(self):
        """validate=True is shorthand for ValidationMode.ENABLED."""
        storage = MemoryStorage()

        with replay("test", storage=storage, validate=True):
            fetch_data("users")

        for key, value in storage.cache.items():
            envelope = json.loads(value)
            envelope["source_hash"] = "0" * 64
            storage.cache[key] = json.dumps(envelope)

        with (
            pytest.raises(StaleReplayError),
            replay("test", storage=storage, validate=True),
        ):
            fetch_data("users")

    def test_validate_false_maps_to_disabled(self):
        """validate=False is shorthand for ValidationMode.DISABLED."""
        storage = MemoryStorage()

        with replay("test", storage=storage):
            fetch_data("users")

        for key, value in storage.cache.items():
            envelope = json.loads(value)
            envelope["source_hash"] = "0" * 64
            storage.cache[key] = json.dumps(envelope)

        call_counts.clear()
        with replay("test", storage=storage, validate=False):
            fetch_data("users")

        assert call_counts.get("fetch_data", 0) == 0

    def test_empty_source_hash_skips_validation(self):
        """When source hash can't be computed, validation is skipped."""
        storage = MemoryStorage()

        # Store an entry with empty source_hash
        with replay("test", storage=storage):
            fetch_data("users")

        for key, value in storage.cache.items():
            envelope = json.loads(value)
            envelope["source_hash"] = ""
            storage.cache[key] = json.dumps(envelope)

        call_counts.clear()
        with replay("test", storage=storage, validate=ValidationMode.ENABLED):
            fetch_data("users")

        assert call_counts.get("fetch_data", 0) == 0  # Cached, validation skipped
