import threading
from typing import Any

import pytest

from stickynote.key_strategies import (
    DEFAULT_STRATEGY,
    CompoundMemoKeyStrategy,
    Inputs,
    SourceCode,
)


def test_inputs_strategy():
    """Test the Inputs strategy for computing memoization keys."""
    strategy = Inputs()

    # Define a test function
    def test_func(a: Any, b: Any, c: int = 10) -> Any:
        return a + b + c

    # Test with positional arguments
    key1 = strategy.compute(test_func, (1, 2), {})
    key2 = strategy.compute(test_func, (1, 2), {})
    assert key1 == key2  # Same arguments should produce same key

    # Test with keyword arguments
    key3 = strategy.compute(test_func, (), {"a": 1, "b": 2})
    assert key1 == key3  # Equivalent arguments should produce same key

    # Test with mixed arguments
    key4 = strategy.compute(test_func, (1,), {"b": 2})
    assert key1 == key4  # Equivalent arguments should produce same key

    # Test with different order of keyword arguments
    key5 = strategy.compute(test_func, (), {"b": 2, "a": 1})
    assert key1 == key5  # Order of keyword arguments shouldn't matter

    # Test with different values
    key6 = strategy.compute(test_func, (1, 3), {})
    assert key1 != key6  # Different arguments should produce different keys

    # Test with default value
    key7 = strategy.compute(test_func, (1, 2, 10), {})
    assert key1 == key7  # Explicit default value should be equivalent


def test_source_code_strategy():
    """Test the SourceCode strategy for computing memoization keys."""
    strategy = SourceCode()

    # Define a test function
    def test_func(a: Any, b: Any) -> Any:  # pyright: ignore[reportRedeclaration] this is intentional for the test
        return a + b

    # Get the key for the function
    key1 = strategy.compute(test_func, (), {})

    # Define the same function again with a different name
    def test_func(a: Any, b: Any) -> Any:  # pyright: ignore[reportRedeclaration] this is intentional for the test
        return a + b

    # Get the key for the second function
    key2 = strategy.compute(test_func, (), {})

    # The keys should be the same since the source code is identical
    assert key1 == key2

    # Define a different function with the same name
    def test_func(a: Any, b: Any) -> Any:
        return a * b  # Different implementation

    # Get the key for the third function
    key3 = strategy.compute(test_func, (), {})

    # The key should be different since the source code is different
    assert key1 != key3


def test_compound_strategy():
    """Test the CompoundMemoKeyStrategy for combining multiple strategies."""
    inputs = Inputs()
    source_code = SourceCode()

    # Create a compound strategy
    compound = CompoundMemoKeyStrategy(inputs, source_code)

    # Define a test function
    def test_func(a: Any, b: Any) -> Any:
        return a + b

    # Get the key for the function
    key1 = compound.compute(test_func, (1, 2), {})

    # Get the keys from the individual strategies
    inputs_key = inputs.compute(test_func, (1, 2), {})
    source_code_key = source_code.compute(test_func, (1, 2), {})

    # The compound key should be different from both individual keys
    assert key1 != inputs_key
    assert key1 != source_code_key

    # The compound key should be consistent for the same function and arguments
    key2 = compound.compute(test_func, (1, 2), {})
    assert key1 == key2

    # The compound key should change if either the function or arguments change
    key3 = compound.compute(test_func, (1, 3), {})
    assert key1 != key3

    def different_func(a: Any, b: Any) -> Any:
        return a + b

    key4 = compound.compute(different_func, (1, 2), {})
    assert key1 != key4


def test_strategy_addition():
    """Test the addition operator for combining strategies."""
    inputs = Inputs()
    source_code = SourceCode()

    # Combine strategies using the addition operator
    compound1 = inputs + source_code

    # This should be equivalent to creating a CompoundMemoKeyStrategy directly
    compound2 = CompoundMemoKeyStrategy(inputs, source_code)

    # Define a test function
    def test_func(a: Any, b: Any) -> Any:
        return a + b

    # Get the keys using both compound strategies
    key1 = compound1.compute(test_func, (1, 2), {})
    key2 = compound2.compute(test_func, (1, 2), {})

    # The keys should be the same
    assert key1 == key2

    # Test chaining multiple additions
    another = SourceCode()
    compound3 = inputs + source_code + another

    # This should be equivalent to
    compound4 = CompoundMemoKeyStrategy(inputs, source_code, another)

    # Get the keys using both compound strategies
    key3 = compound3.compute(test_func, (1, 2), {})
    key4 = compound4.compute(test_func, (1, 2), {})

    # The keys should be the same
    assert key3 == key4

    # Test adding two compound strategies
    compound5 = compound1 + compound2

    # This should be equivalent to
    compound6 = CompoundMemoKeyStrategy(inputs, source_code, inputs, source_code)
    compound7 = CompoundMemoKeyStrategy(compound1, compound2)

    # Get the keys using both compound strategies
    key5 = compound5.compute(test_func, (1, 2), {})
    key6 = compound6.compute(test_func, (1, 2), {})
    key7 = compound7.compute(test_func, (1, 2), {})

    # The keys should be the same
    assert key5 == key6 == key7


def test_default_strategy():
    """Test the DEFAULT_STRATEGY."""

    # Define a test function
    def test_func(a: Any, b: Any) -> Any:
        return a + b

    # Get the key using the default strategy
    key1 = DEFAULT_STRATEGY.compute(test_func, (1, 2), {})

    # The default strategy is SourceCode() + Inputs()
    source_code = SourceCode()
    inputs = Inputs()
    manual_compound = source_code + inputs

    # Get the key using the manual compound strategy
    key2 = manual_compound.compute(test_func, (1, 2), {})

    # The keys should be the same
    assert key1 == key2


def test_inputs_strategy_with_complex_objects():
    """Test the Inputs strategy with complex objects."""
    strategy = Inputs()

    # Define a test function
    def test_func(a: Any, b: Any, _c: Any = None) -> Any:
        return a + b

    # Test with a list
    key1 = strategy.compute(test_func, ([1, 2, 3], 2), {})
    key2 = strategy.compute(test_func, ([1, 2, 3], 2), {})
    assert key1 == key2

    # Test with a dictionary
    key3 = strategy.compute(test_func, ({"x": 1, "y": 2}, 2), {})
    key4 = strategy.compute(test_func, ({"y": 2, "x": 1}, 2), {})
    assert key3 == key4  # Order of dictionary keys shouldn't matter

    # Test with None
    key5 = strategy.compute(test_func, (1, 2, None), {})
    key6 = strategy.compute(test_func, (1, 2), {})
    assert key5 == key6  # Explicit None should be equivalent to default


class CanNotBeSerializedToJson:
    def __init__(self, value: Any) -> None:
        self.value = value


def test_inputs_strategy_with_json_serialization_failure():
    """Test the Inputs strategy when JSON serialization fails."""
    strategy = Inputs()

    # Define a test function
    def test_func(a: Any, b: Any) -> Any:
        return a + b

    # This should fall back to pickle serialization
    key1 = strategy.compute(test_func, (CanNotBeSerializedToJson(1), 2), {})
    key2 = strategy.compute(test_func, (CanNotBeSerializedToJson(1), 2), {})
    assert key1 == key2

    # Different values should produce different keys
    key3 = strategy.compute(test_func, (CanNotBeSerializedToJson(2), 2), {})
    assert key1 != key3


def test_inputs_strategy_with_pickle_serialization_failure():
    """Test the Inputs strategy when pickle serialization fails."""
    strategy = Inputs()

    # Define a test function
    def test_func(a: Any) -> Any:
        return a

    # Pass in a thread (which is not picklable)
    with pytest.raises(ValueError):
        strategy.compute(test_func, (threading.Thread(),), {})
