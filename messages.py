"""Version 1 test messages and messaging logic, independent of storage vendors."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from storage import StorageProvider


class MessageValidationError(ValueError):
    """A message does not conform to the supported JSON format."""


def validate_id(value):
    """Require a canonical UUID so identifiers are also safe filename components."""
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise MessageValidationError("message_id must be a canonical UUID.") from exc


@dataclass(frozen=True)
class TestMessage:
    """A text test message with an explicit format version and UTC creation time."""

    version: int
    message_id: str
    timestamp: str
    text: str

    def __post_init__(self):
        """Validate both locally created and decoded messages."""
        if type(self.version) is not int or self.version != 1:
            raise MessageValidationError("Only message version 1 is supported.")
        validate_id(self.message_id)
        try:
            if not isinstance(self.timestamp, str) or not self.timestamp.endswith("Z"):
                raise ValueError
            datetime.fromisoformat(self.timestamp[:-1] + "+00:00")
        except ValueError as exc:
            raise MessageValidationError("timestamp must be an ISO 8601 UTC datetime ending in Z.") from exc
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 10000:
            raise MessageValidationError("text must contain 1–10000 characters and cannot be blank.")

    @classmethod
    def create(cls, text: str):
        """Create a validated message with a new UUID and the current UTC timestamp."""
        return cls(1, str(uuid4()), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), text)

    def to_bytes(self) -> bytes:
        """Serialize the message as UTF-8 JSON."""
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes):
        """Decode JSON and reject malformed, missing, extra, or unsupported fields."""
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise MessageValidationError(f"Duplicate field: {key}")
                result[key] = value
            return result

        try:
            value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise MessageValidationError("Message must be valid UTF-8 JSON.") from exc
        if not isinstance(value, dict) or set(value) != {"version", "message_id", "timestamp", "text"}:
            raise MessageValidationError("Expected exactly version, message_id, timestamp, and text.")
        return cls(**value)


class MessageTransport:
    """Send, receive, list, and delete messages through any StorageProvider."""

    def __init__(self, storage: StorageProvider):
        self.storage = storage

    @staticmethod
    def _path(message_id: str) -> str:
        validate_id(message_id)
        return f"/message-{message_id}.json"

    def send(self, text: str) -> TestMessage:
        """Create and store a message without overwriting an existing message."""
        message = TestMessage.create(text)
        self.storage.put(self._path(message.message_id), message.to_bytes())
        return message

    def receive(self, message_id: str) -> TestMessage:
        """Read and validate a message without deleting it."""
        message = TestMessage.from_bytes(self.storage.get(self._path(message_id)))
        if message.message_id != message_id:
            raise MessageValidationError("Stored message ID does not match the requested ID.")
        return message

    def list_ids(self) -> list[str]:
        """List message identifiers, ignoring unrelated files in storage."""
        ids = []
        for path in self.storage.list_files():
            if path.startswith("/message-") and path.endswith(".json"):
                candidate = path[len("/message-"):-len(".json")]
                try:
                    validate_id(candidate)
                except MessageValidationError:
                    continue
                ids.append(candidate)
        return sorted(ids)

    def delete(self, message_id: str) -> None:
        """Explicitly remove a message by its identifier."""
        self.storage.delete(self._path(message_id))
