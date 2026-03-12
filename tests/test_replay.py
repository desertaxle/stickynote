import json

from stickynote.replay import replay
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
