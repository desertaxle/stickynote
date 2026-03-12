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
