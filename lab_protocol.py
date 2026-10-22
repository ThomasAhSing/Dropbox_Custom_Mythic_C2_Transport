"""Strict v2 envelopes for harmless heartbeat/acknowledgement experiments only."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from uuid import uuid4, uuid5, NAMESPACE_URL

from messages import MessageValidationError, validate_id


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Envelope:
    version: int
    run_id: str
    message_id: str
    timestamp: str
    sender: str
    recipient: str
    kind: str
    correlation_id: str | None

    def __post_init__(self):
        if type(self.version) is not int or self.version != 2:
            raise MessageValidationError("Expected envelope version 2.")
        validate_id(self.run_id)
        validate_id(self.message_id)
        if self.sender not in ("node-a", "node-b") or self.recipient not in ("node-a", "node-b"):
            raise MessageValidationError("Unknown lab endpoint.")
        if self.sender == self.recipient or self.kind not in ("heartbeat", "ack"):
            raise MessageValidationError("Invalid heartbeat route or kind.")
        try:
            if not isinstance(self.timestamp, str) or "T" not in self.timestamp or not self.timestamp.endswith("Z"):
                raise ValueError
            datetime.fromisoformat(self.timestamp[:-1] + "+00:00")
        except ValueError as exc:
            raise MessageValidationError("Expected UTC timestamp.") from exc
        if self.kind == "heartbeat" and self.correlation_id is not None:
            raise MessageValidationError("Heartbeat cannot have a correlation ID.")
        if self.kind == "ack":
            validate_id(self.correlation_id)

    @classmethod
    def heartbeat(cls, run_id, sender, recipient):
        return cls(2, run_id, str(uuid4()), utc_now(), sender, recipient, "heartbeat", None)

    def acknowledgement(self):
        """Deterministic acknowledgement makes replica/restart uploads idempotent."""
        return Envelope(2, self.run_id,
                        str(uuid5(NAMESPACE_URL, f"lab-ack:{self.run_id}:{self.message_id}")),
                        self.timestamp, self.recipient, self.sender, "ack", self.message_id)

    @property
    def path(self):
        return f"/lab-{self.run_id}-{self.recipient}-{self.message_id}.json"

    def to_bytes(self):
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def from_bytes(cls, data):
        if not isinstance(data, bytes) or len(data) > 4096:
            raise MessageValidationError("Envelope exceeds 4096 bytes or is not bytes.")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise MessageValidationError("Duplicate JSON field.")
                result[key] = value
            return result

        try:
            value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
            if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
                raise MessageValidationError("Unexpected envelope fields.")
            return cls(**value)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise MessageValidationError("Invalid envelope JSON.") from exc
