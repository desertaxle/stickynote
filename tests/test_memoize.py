import base64
import pickle
from stickynote import memoize
from stickynote.backends import MemoryStorage
from stickynote.memoize import MemoBlock
from typing import Dict


class TestMemoize:
    def test_basic_memoization(self):
        storage = MemoryStorage()
        call_count = 0

        @memoize(storage)
        def add(a: int, b: int) -> int:
            nonlocal call_count
            call_count += 1
            return a + b

        # First call should execute the function
        result1 = add(1, 2)
        assert result1 == 3
        assert call_count == 1

        # Second call with same args should use cache
        result2 = add(1, 2)
        assert result2 == 3
        assert call_count == 1  # Call count should not increase

    def test_kwargs_memoization(self):
        storage = MemoryStorage()
        call_count = 0

        @memoize(storage)
        def greet(name: str, prefix: str = "Hello") -> str:
            nonlocal call_count
            call_count += 1
            return f"{prefix}, {name}!"

        # First call
        result1 = greet("Alice", prefix="Hi")
        assert result1 == "Hi, Alice!"
        assert call_count == 1

        # Second call with same kwargs
        result2 = greet("Alice", prefix="Hi")
        assert result2 == "Hi, Alice!"
        assert call_count == 1

        # Different kwargs should not use cache
        result3 = greet("Alice", prefix="Hello")
        assert result3 == "Hello, Alice!"
        assert call_count == 2

    def test_complex_object_memoization(self):
        storage = MemoryStorage()
        call_count = 0

        @memoize(storage)
        def create_dict(a: int, b: int) -> Dict[str, int]:
            nonlocal call_count
            call_count += 1
            return {"sum": a + b, "product": a * b}

        # First call
        result1 = create_dict(2, 3)
        assert result1 == {"sum": 5, "product": 6}
        assert call_count == 1

        # Second call with same args
        result2 = create_dict(2, 3)
        assert result2 == {"sum": 5, "product": 6}
        assert call_count == 1

    def test_none_result_memoization(self):
        storage = MemoryStorage()
        call_count = 0

        @memoize(storage)
        def return_none(x: int) -> None:
            nonlocal call_count
            call_count += 1
            return None

        # First call
        result1 = return_none(1)
        assert result1 is None
        assert call_count == 1

        # Second call
        result2 = return_none(1)
        assert result2 is None
        assert call_count == 1

    def test_backend_interaction(self):
        storage = MemoryStorage()
        call_count = 0

        @memoize(storage)
        def multiply(a: int, b: int) -> int:
            nonlocal call_count
            call_count += 1
            return a * b

        # First call
        result1 = multiply(2, 3)
        assert result1 == 6
        assert call_count == 1

        # Verify backend storage
        key = next(iter(storage.cache.keys()))
        assert storage.exists(key)
        assert storage.get(key) is not None

        # Second call should use backend cache
        result2 = multiply(2, 3)
        assert result2 == 6
        assert call_count == 1

    def test_different_args_not_cached(self):
        storage = MemoryStorage()
        call_count = 0

        @memoize(storage)
        def power(base: int, exponent: int) -> int:
            nonlocal call_count
            call_count += 1
            return base**exponent

        # First call
        result1 = power(2, 3)
        assert result1 == 8
        assert call_count == 1

        # Different args should not use cache
        result2 = power(2, 4)
        assert result2 == 16
        assert call_count == 2

        # Same args should use cache
        result3 = power(2, 3)
        assert result3 == 8
        assert call_count == 2


class TestMemoBlock:
    def test_context_manager(self):
        storage = MemoryStorage()
        with MemoBlock(storage) as memo:
            assert memo.storage == storage
            assert not memo.hit
            assert memo.value is None

    def test_load_existing_value(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"
        storage.set(key, base64.b64encode(pickle.dumps(test_value)).decode("utf-8"))

        with MemoBlock(storage) as memo:
            memo.load(key)
            assert memo.hit
            assert memo.value == test_value

    def test_load_nonexistent_value(self):
        storage = MemoryStorage()
        with MemoBlock(storage) as memo:
            memo.load("nonexistent_key")
            assert not memo.hit
            assert memo.value is None

    def test_save_value(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"

        with MemoBlock(storage) as memo:
            memo.save(key, test_value)
            assert storage.exists(key)
            assert storage.get(key) == base64.b64encode(
                pickle.dumps(test_value)
            ).decode("utf-8")

    def test_save_and_load(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"

        # Save value
        with MemoBlock(storage) as memo:
            memo.save(key, test_value)

        # Load value
        with MemoBlock(storage) as memo:
            memo.load(key)
            assert memo.hit
            assert memo.value == test_value

    def test_complex_value_serialization(self):
        storage = MemoryStorage()
        test_value = {
            "string": "hello",
            "number": 42,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "none": None,
        }
        key = "test_key"

        with MemoBlock(storage) as memo:
            memo.save(key, test_value)
            assert storage.exists(key)

        with MemoBlock(storage) as memo:
            memo.load(key)
            assert memo.hit
            assert memo.value == test_value
