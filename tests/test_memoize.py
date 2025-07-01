from __future__ import annotations

import asyncio
import base64
import importlib.util
import pickle
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from exceptiongroup import ExceptionGroup
from freezegun import freeze_time

from stickynote import memoize
from stickynote.key_strategies import (
    Inputs,
    MemoKeyStrategy,
    SourceCode,
)
from stickynote.memoize import AsyncMemoBlock, MemoBlock
from stickynote.serializers import (
    CloudPickleSerializer,
    JsonSerializer,
    PickleSerializer,
    Serializer,
)
from stickynote.storage import MemoryStorage

# Test CloudPickleSerializer only if cloudpickle is available
HAS_CLOUDPICKLE = importlib.util.find_spec("cloudpickle") is not None


class StaticKeyStrategy(MemoKeyStrategy):
    def compute(self, func: Any, args: Any, kwargs: Any) -> str:
        return "test_key"


class Plebian:
    def __init__(self, x: int):
        self.x = x

    def __call__(self, y: int) -> int:
        return self.x + y


class TestMemoize:
    class TestSync:
        def test_basic_memoization(self):
            call_count = 0

            @memoize
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

            @memoize(storage=storage)
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

            @memoize(storage=storage)
            def create_dict(a: int, b: int) -> dict[str, int]:
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

            @memoize(storage=storage)
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

            @memoize(storage=storage)
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

            @memoize(storage=storage)
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

        def test_memoize_with_source_code_strategy(self):
            """Test that memoize works with the SourceCode strategy."""
            storage = MemoryStorage()
            strategy = SourceCode()
            call_count = 0

            @memoize(storage=storage, key_strategy=strategy)
            def add(a: int, b: int) -> int:  # pyright: ignore[reportRedeclaration] this is intentional for the test
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

            # Define a function with identical source code
            @memoize(storage=storage, key_strategy=strategy)
            def add(a: int, b: int) -> int:  # pyright: ignore[reportRedeclaration] this is intentional for the test
                nonlocal call_count
                call_count += 1
                return a + b

            # This should use the cache since the source code is identical
            result3 = add(1, 2)
            assert result3 == 3
            assert call_count == 1  # Call count should still be 1

        def test_memoize_with_inputs_strategy(self):
            """Test that memoize works with the Inputs strategy."""
            storage = MemoryStorage()
            strategy = Inputs()
            call_count = 0

            @memoize(storage=storage, key_strategy=strategy)
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

        def test_memoize_with_custom_strategy(self):
            """Test that memoize works with a custom strategy."""
            storage = MemoryStorage()

            # Create a custom strategy that only uses the function name
            class FunctionNameStrategy(MemoKeyStrategy):
                def compute(self, func: Any, args: Any, kwargs: Any) -> str:
                    return func.__name__

            call_count = 0

            @memoize(storage=storage, key_strategy=FunctionNameStrategy())
            def custom_func(a: int, b: int) -> int:
                nonlocal call_count
                call_count += 1
                return a + b

            # First call
            result1 = custom_func(1, 2)
            assert result1 == 3
            assert call_count == 1

            # Second call with different args should still use cache
            # since our strategy only looks at the function name
            result2 = custom_func(2, 3)
            assert result2 == 3  # Should return cached result
            assert call_count == 1  # Call count should not increase

            # Different function name should not use cache
            @memoize(storage=storage, key_strategy=FunctionNameStrategy())
            def another_func(a: int, b: int) -> int:
                nonlocal call_count
                call_count += 1
                return a + b

            result3 = another_func(1, 2)
            assert result3 == 3
            assert call_count == 2  # Call count should increase

        def test_memoize_with_complex_objects(self):
            """Test that memoize works with complex objects using the Inputs strategy."""
            storage = MemoryStorage()
            strategy = Inputs()
            call_count = 0

            @memoize(storage=storage, key_strategy=strategy)
            def process_list(items: list[int], multiplier: int = 1) -> list[int]:
                nonlocal call_count
                call_count += 1
                return [item * multiplier for item in items]

            # First call
            result1 = process_list([1, 2, 3], multiplier=2)
            assert result1 == [2, 4, 6]
            assert call_count == 1

            # Second call with same args
            result2 = process_list([1, 2, 3], multiplier=2)
            assert result2 == [2, 4, 6]
            assert call_count == 1

            # Different args should not use cache
            result3 = process_list([1, 2, 3], multiplier=3)
            assert result3 == [3, 6, 9]
            assert call_count == 2

        def test_memoize_with_none_result(self):
            """Test that memoize works with None results."""
            storage = MemoryStorage()
            strategy = Inputs()
            call_count = 0

            @memoize(storage=storage, key_strategy=strategy)
            def return_none(x: int) -> int | None:
                nonlocal call_count
                call_count += 1
                return None if x < 0 else x

            # First call
            result1 = return_none(-1)
            assert result1 is None
            assert call_count == 1

            # Second call with same args
            result2 = return_none(-1)
            assert result2 is None
            assert call_count == 1

            # Different args should not use cache
            result3 = return_none(1)
            assert result3 == 1
            assert call_count == 2

        def test_with_non_default_serializer(self):
            storage = MemoryStorage()
            serializer = JsonSerializer()

            call_count = 0

            @memoize(storage=storage, serializer=serializer)
            def add(a: int, b: int) -> int:
                nonlocal call_count
                call_count += 1
                return a + b

            result = add(1, 2)
            assert result == 3
            assert call_count == 1

            result = add(1, 2)
            assert result == 3
            assert call_count == 1

        @pytest.mark.skipif(not HAS_CLOUDPICKLE, reason="cloudpickle not installed")
        def test_with_multiple_serializers(self):
            storage = MemoryStorage()
            serializer = (JsonSerializer(), PickleSerializer(), CloudPickleSerializer())

            call_count = 0

            @memoize(storage=storage, serializer=serializer)
            def add_factory(a: int, b: int):
                def add() -> int:
                    return a + b

                nonlocal call_count
                call_count += 1
                return add

            result = add_factory(1, 2)
            assert result() == 3
            assert call_count == 1

            result = add_factory(1, 2)
            assert result() == 3
            assert call_count == 1

        def test_all_serializers_fail(self):
            storage = MemoryStorage()
            serializer = (JsonSerializer(), PickleSerializer())

            @memoize(storage=storage, serializer=serializer)
            def add_factory(a: int, b: int) -> Callable[[], int]:
                def add() -> int:
                    return a + b

                return add

            with pytest.raises(ExceptionGroup) as e:
                add_factory(1, 2)

            assert len(e.value.exceptions) == 2

        @freeze_time("2025-01-01")
        def test_on_cache_hit_callback(self):
            storage = MemoryStorage()
            spy = MagicMock()

            def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )

            memoized_add.on_cache_hit(spy)

            memoized_add(1, 2)
            spy.assert_not_called()
            memoized_add(1, 2)
            spy.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )

        @freeze_time("2025-01-01")
        def test_on_multiple_on_cache_hit_callbacks(self):
            storage = MemoryStorage()
            spy1 = MagicMock()
            spy2 = MagicMock()

            def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )

            memoized_add.on_cache_hit(spy1)
            memoized_add.on_cache_hit(spy2)

            memoized_add(1, 2)
            spy1.assert_not_called()
            spy2.assert_not_called()

            memoized_add(1, 2)
            spy1.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )
            spy2.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )

        @freeze_time("2025-01-01")
        def test_on_cache_callback_raises_exception(
            self, caplog: pytest.LogCaptureFixture
        ):
            storage = MemoryStorage()
            spy = MagicMock()
            spy.side_effect = Exception("test exception")

            def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )
            memoized_add.on_cache_hit(spy)

            memoized_add(1, 2)
            spy.assert_not_called()

            memoized_add(1, 2)
            spy.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )

            assert (
                "An error occurred while calling on_cache_hit callback" in caplog.text
            )
            assert "test exception" in caplog.text

        def test_before_cache_lookup_callback(self):
            storage = MemoryStorage()
            spy = MagicMock()

            def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )

            memoized_add.before_cache_lookup(spy)

            memoized_add(1, 2)
            spy.assert_called_once_with("test_key", (1, 2), {})

        def test_with_max_age(self):
            storage = MemoryStorage()
            strategy = Inputs()
            call_count = 0

            @memoize(
                storage=storage,
                key_strategy=strategy,
                max_age=timedelta(milliseconds=100),
            )
            def add(a: int, b: int) -> int:
                nonlocal call_count
                call_count += 1
                return a + b

            result = add(1, 2)
            assert result == 3
            assert call_count == 1

            result = add(1, 2)
            assert result == 3
            assert call_count == 1

            sleep(0.1)

            result = add(1, 2)
            assert result == 3
            assert call_count == 2

    class TestAsync:
        async def test_memoize_async_function(self):
            storage = MemoryStorage()

            @memoize(storage=storage)
            async def add(a: int, b: int) -> int:
                return a + b

            result = await add(1, 2)
            assert result == 3

            result = await add(1, 2)
            assert result == 3

        @freeze_time("2025-01-01")
        async def test_on_cache_hit_callback(self):
            storage = MemoryStorage()
            spy = MagicMock()

            async def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )

            memoized_add.on_cache_hit(spy)

            await memoized_add(1, 2)
            spy.assert_not_called()
            await memoized_add(1, 2)
            spy.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )

        @freeze_time("2025-01-01")
        async def test_on_multiple_on_cache_hit_callbacks(self):
            storage = MemoryStorage()
            spy1 = MagicMock()
            spy2 = MagicMock()

            async def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )

            memoized_add.on_cache_hit(spy1)
            memoized_add.on_cache_hit(spy2)

            await memoized_add(1, 2)
            spy1.assert_not_called()
            spy2.assert_not_called()

            await memoized_add(1, 2)
            spy1.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )
            spy2.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )

        @freeze_time("2025-01-01")
        async def test_on_cache_callback_raises_exception(
            self, caplog: pytest.LogCaptureFixture
        ):
            storage = MemoryStorage()
            spy = MagicMock()
            spy.side_effect = Exception("test exception")

            async def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )
            memoized_add.on_cache_hit(spy)

            await memoized_add(1, 2)
            spy.assert_not_called()

            await memoized_add(1, 2)
            spy.assert_called_once_with(
                "test_key", 3, (1, 2), {}, datetime.now(timezone.utc)
            )

            assert (
                "An error occurred while calling on_cache_hit callback" in caplog.text
            )
            assert "test exception" in caplog.text

        async def test_before_cache_lookup_callback(self):
            storage = MemoryStorage()
            spy = MagicMock()

            async def add(a: int, b: int) -> int:
                return a + b

            memoized_add = memoize(storage=storage, key_strategy=StaticKeyStrategy())(
                add
            )

            memoized_add.before_cache_lookup(spy)

            await memoized_add(1, 2)
            spy.assert_called_once_with("test_key", (1, 2), {})

        async def test_with_max_age(self):
            storage = MemoryStorage()
            strategy = Inputs()
            call_count = 0

            @memoize(
                storage=storage,
                key_strategy=strategy,
                max_age=timedelta(milliseconds=100),
            )
            async def add(a: int, b: int) -> int:
                nonlocal call_count
                call_count += 1
                return a + b

            result = await add(1, 2)
            assert result == 3
            assert call_count == 1

            result = await add(1, 2)
            assert result == 3
            assert call_count == 1

            await asyncio.sleep(0.1)

            result = await add(1, 2)
            assert result == 3
            assert call_count == 2


class TestMemoBlock:
    def test_context_manager(self):
        storage = MemoryStorage()
        with MemoBlock(key="test_key", storage=storage) as memo:
            assert memo.storage == storage
            assert not memo.hit
            assert memo.value is None

    def test_load_existing_value(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"
        storage.set(key, base64.b64encode(pickle.dumps(test_value)).decode("utf-8"))

        with MemoBlock(key=key, storage=storage) as memo:
            memo.load()
            assert memo.hit
            assert memo.value == test_value

    def test_load_nonexistent_value(self):
        storage = MemoryStorage()
        with MemoBlock(key="nonexistent_key", storage=storage) as memo:
            memo.load()
            assert not memo.hit
            assert memo.value is None

    def test_save_value(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"

        with MemoBlock(key=key, storage=storage) as memo:
            memo.stage(test_value)

        assert storage.exists(key)
        assert storage.get(key) == JsonSerializer().serialize({"key": "value"})

    def test_save_and_load(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"

        # Save value
        with MemoBlock(key=key, storage=storage) as memo:
            memo.stage(test_value)

        # Load value
        with MemoBlock(key=key, storage=storage) as memo:
            memo.load()
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

        with MemoBlock(key=key, storage=storage) as memo:
            memo.stage(test_value)
        assert storage.exists(key)

        with MemoBlock(key=key, storage=storage) as memo:
            memo.load()
            assert memo.hit
            assert memo.value == test_value

    def test_with_non_default_serializer(self):
        storage = MemoryStorage()
        serializer = JsonSerializer()
        key = "test_key"
        with MemoBlock(key=key, storage=storage, serializer=serializer) as memo:
            memo.stage({"key": "value"})

        assert storage.exists(key)
        assert storage.get(key) == serializer.serialize({"key": "value"})

    @pytest.mark.skipif(not HAS_CLOUDPICKLE, reason="cloudpickle not installed")
    @pytest.mark.parametrize(
        "serializer",
        [
            (JsonSerializer(), PickleSerializer(), CloudPickleSerializer()),
            [JsonSerializer(), CloudPickleSerializer()],
        ],
    )
    def test_with_multiple_serializers(
        self, serializer: list[Serializer] | tuple[Serializer, ...]
    ):
        storage = MemoryStorage()

        def outer(x: int) -> Callable[[int], int]:
            y = x * 2

            def inner(z: int) -> int:
                return y + z

            return inner

        closure_func = outer(5)

        with MemoBlock(key="test_key", storage=storage, serializer=serializer) as memo:
            memo.stage(closure_func)

        assert storage.exists("test_key")
        assert storage.get("test_key") == serializer[-1].serialize(closure_func)

    def test_all_serializers_fail(self):
        storage = MemoryStorage()
        serializer = (JsonSerializer(), PickleSerializer())

        def outer(x: int) -> Callable[[int], int]:
            y = x * 2

            def inner(z: int) -> int:
                return y + z

            return inner

        closure_func = outer(5)
        with pytest.raises(ExceptionGroup) as e:
            with MemoBlock(
                key="test_key", storage=storage, serializer=serializer
            ) as memo:
                memo.stage(closure_func)

        assert len(e.value.exceptions) == 2

    def test_all_deserialization_attempts_fail(self):
        storage = MemoryStorage()
        serializer = (JsonSerializer(), PickleSerializer())
        deserializer = (JsonSerializer(),)

        def class_factory(x: int) -> Callable[[int], int]:
            return Plebian(x)

        with MemoBlock(key="test_key", storage=storage, serializer=serializer) as memo:
            memo.stage(class_factory(1))

        with pytest.raises(ExceptionGroup) as e:
            with MemoBlock(
                key="test_key", storage=storage, serializer=deserializer
            ) as memo:
                pass

        assert len(e.value.exceptions) == 1


class TestAsyncMemoBlock:
    async def test_context_manager(self):
        storage = MemoryStorage()
        async with AsyncMemoBlock(key="test_key", storage=storage) as memo:
            assert memo.storage == storage
            assert not memo.hit
            assert memo.value is None

    async def test_load_existing_value(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"
        storage.set(key, base64.b64encode(pickle.dumps(test_value)).decode("utf-8"))

        async with AsyncMemoBlock(key=key, storage=storage) as memo:
            await memo.load()
            assert memo.hit
            assert memo.value == test_value

    async def test_load_nonexistent_value(self):
        storage = MemoryStorage()
        async with AsyncMemoBlock(key="nonexistent_key", storage=storage) as memo:
            await memo.load()
            assert not memo.hit
            assert memo.value is None

    async def test_save_value(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"

        async with AsyncMemoBlock(key=key, storage=storage) as memo:
            memo.stage(test_value)

        assert storage.exists(key)
        assert storage.get(key) == JsonSerializer().serialize({"key": "value"})

    async def test_save_and_load(self):
        storage = MemoryStorage()
        test_value = {"key": "value"}
        key = "test_key"

        # Save value
        async with AsyncMemoBlock(key=key, storage=storage) as memo:
            memo.stage(test_value)

        # Load value
        async with AsyncMemoBlock(key=key, storage=storage) as memo:
            await memo.load()
            assert memo.hit
            assert memo.value == test_value

    async def test_complex_value_serialization(self):
        storage = MemoryStorage()
        test_value = {
            "string": "hello",
            "number": 42,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "none": None,
        }
        key = "test_key"

        async with AsyncMemoBlock(key=key, storage=storage) as memo:
            memo.stage(test_value)
        assert storage.exists(key)

        async with AsyncMemoBlock(key=key, storage=storage) as memo:
            await memo.load()
            assert memo.hit
            assert memo.value == test_value

    async def test_with_non_default_serializer(self):
        storage = MemoryStorage()
        serializer = JsonSerializer()
        key = "test_key"
        async with AsyncMemoBlock(
            key=key, storage=storage, serializer=serializer
        ) as memo:
            memo.stage({"key": "value"})

        assert storage.exists(key)
        assert storage.get(key) == serializer.serialize({"key": "value"})

    @pytest.mark.skipif(not HAS_CLOUDPICKLE, reason="cloudpickle not installed")
    @pytest.mark.parametrize(
        "serializer",
        [
            (JsonSerializer(), PickleSerializer(), CloudPickleSerializer()),
            [JsonSerializer(), CloudPickleSerializer()],
        ],
    )
    async def test_with_multiple_serializers(
        self, serializer: list[Serializer] | tuple[Serializer, ...]
    ):
        storage = MemoryStorage()

        def outer(x: int) -> Callable[[int], int]:
            y = x * 2

            def inner(z: int) -> int:
                return y + z

            return inner

        closure_func = outer(5)

        async with AsyncMemoBlock(
            key="test_key", storage=storage, serializer=serializer
        ) as memo:
            memo.stage(closure_func)

        assert storage.exists("test_key")
        assert storage.get("test_key") == serializer[-1].serialize(closure_func)

    async def test_all_serializers_fail(self):
        storage = MemoryStorage()
        serializer = (JsonSerializer(), PickleSerializer())

        def outer(x: int) -> Callable[[int], int]:
            y = x * 2

            def inner(z: int) -> int:
                return y + z

            return inner

        closure_func = outer(5)
        with pytest.raises(ExceptionGroup) as e:
            async with AsyncMemoBlock(
                key="test_key", storage=storage, serializer=serializer
            ) as memo:
                memo.stage(closure_func)

        assert len(e.value.exceptions) == 2

    async def test_all_deserialization_attempts_fail(self):
        storage = MemoryStorage()
        serializer = (JsonSerializer(), PickleSerializer())
        deserializer = (JsonSerializer(),)

        async def class_factory(x: int) -> Callable[[int], int]:
            return Plebian(x)

        async with AsyncMemoBlock(
            key="test_key", storage=storage, serializer=serializer
        ) as memo:
            memo.stage(await class_factory(1))

        with pytest.raises(ExceptionGroup) as e:
            async with AsyncMemoBlock(
                key="test_key", storage=storage, serializer=deserializer
            ) as memo:
                pass

        assert len(e.value.exceptions) == 1
