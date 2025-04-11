import base64
import json
import pickle
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Serializer(Protocol):
    def serialize(self, obj: Any) -> str: ...

    def deserialize(self, data: str) -> Any: ...


class JsonSerializer(Serializer):
    def serialize(self, obj: Any) -> str:
        return json.dumps(obj)

    def deserialize(self, data: str) -> Any:
        return json.loads(data)


class PickleSerializer(Serializer):
    def serialize(self, obj: Any) -> str:
        return base64.b64encode(pickle.dumps(obj)).decode("utf-8")

    def deserialize(self, data: str) -> Any:
        return pickle.loads(base64.b64decode(data.encode("utf-8")))


class CloudPickleSerializer(Serializer):
    def serialize(self, obj: Any) -> str:
        try:
            import cloudpickle  # pyright: ignore[reportMissingTypeStubs]
        except ImportError:
            raise ImportError(
                "Unable to import cloudpickle. Please install 'stickynote[cloudpickle]' to use this serializer."
            )
        return base64.b64encode(cloudpickle.dumps(obj)).decode("utf-8")  # pyright: ignore[reportUnknownMemberType]

    def deserialize(self, data: str) -> Any:
        try:
            import cloudpickle  # pyright: ignore[reportMissingTypeStubs]
        except ImportError:
            raise ImportError(
                "Unable to import cloudpickle. Please install 'stickynote[cloudpickle]' to use this serializer."
            )

        return cloudpickle.loads(base64.b64decode(data.encode("utf-8")))


DEFAULT_SERIALIZER_CHAIN: tuple[Serializer, ...] = (
    JsonSerializer(),
    PickleSerializer(),
)
