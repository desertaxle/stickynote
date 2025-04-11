from __future__ import annotations

import importlib.util
import json
import base64
from typing import Any, Callable
import pytest

from stickynote.serializers import (
    JsonSerializer,
    PickleSerializer,
    CloudPickleSerializer,
    DEFAULT_SERIALIZER_CHAIN,
)


def test_json_serializer():
    serializer = JsonSerializer()

    # Test with simple data types
    test_data = {
        "string": "hello",
        "number": 42,
        "boolean": True,
        "list": [1, 2, 3],
        "dict": {"a": 1, "b": 2},
        "null": None,
    }

    serialized = serializer.serialize(test_data)
    assert isinstance(serialized, str)
    assert json.loads(serialized) == test_data

    deserialized = serializer.deserialize(serialized)
    assert deserialized == test_data


def test_pickle_serializer():
    serializer = PickleSerializer()

    # Test with Python objects
    test_data = {
        "string": "hello",
        "number": 42,
        "boolean": True,
        "list": [1, 2, 3],
        "dict": {"a": 1, "b": 2},
        "null": None,
    }

    serialized = serializer.serialize(test_data)
    assert isinstance(serialized, str)

    # Verify it's base64 encoded
    try:
        base64.b64decode(serialized)
    except Exception:
        pytest.fail("Serialized data is not valid base64")

    deserialized = serializer.deserialize(serialized)
    assert deserialized == test_data


@pytest.mark.parametrize(
    "test_data",
    [
        {"string": "hello", "number": 42},
        [1, 2, 3, 4, 5],
        "simple string",
        42,
        True,
        None,
    ],
)
def test_serializer_chain(test_data: Any):
    """Test that the default serializer chain can handle various data types"""
    for serializer in DEFAULT_SERIALIZER_CHAIN:
        serialized = serializer.serialize(test_data)
        assert isinstance(serialized, str)

        deserialized = serializer.deserialize(serialized)
        assert deserialized == test_data


# Test CloudPickleSerializer only if cloudpickle is available
HAS_CLOUDPICKLE = importlib.util.find_spec("cloudpickle") is not None


@pytest.mark.skipif(not HAS_CLOUDPICKLE, reason="cloudpickle not installed")
def test_cloudpickle_serializer():
    serializer = CloudPickleSerializer()

    # Test with more complex Python objects
    class TestClass:
        def __init__(self, value: Any):
            self.value = value

        def __eq__(self, other: Any) -> bool:
            return isinstance(other, TestClass) and self.value == other.value

    test_data: dict[str, str | int | TestClass | Callable[[int], int]] = {
        "string": "hello",
        "number": 42,
        "object": TestClass("test"),
        "lambda": lambda x: x * 2,
    }

    serialized = serializer.serialize(test_data)
    assert isinstance(serialized, str)

    # Verify it's base64 encoded
    try:
        base64.b64decode(serialized)
    except Exception:
        pytest.fail("Serialized data is not valid base64")

    deserialized = serializer.deserialize(serialized)
    assert deserialized["string"] == test_data["string"]
    assert deserialized["number"] == test_data["number"]
    assert deserialized["object"] == test_data["object"]
    assert deserialized["lambda"](5) == test_data["lambda"](5)  # pyright: ignore[reportCallIssue]


@pytest.mark.skipif(HAS_CLOUDPICKLE, reason="cloudpickle is installed")
def test_cloudpickle_serializer_import_error():
    serializer = CloudPickleSerializer()

    with pytest.raises(ImportError) as excinfo:
        serializer.serialize({"test": "data"})

    assert "Unable to import cloudpickle" in str(excinfo.value)
    assert "install 'stickynote[cloudpickle]'" in str(excinfo.value)
