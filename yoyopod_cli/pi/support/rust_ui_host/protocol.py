"""Line-delimited JSON protocol for the Rust UI host."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any

SUPPORTED_SCHEMA_VERSION = 1
VALID_KINDS = {"command", "event", "error", "heartbeat"}


class UiProtocolError(ValueError):
    """Raised when a Rust UI host envelope is malformed."""


@dataclass(frozen=True, slots=True)
class UiEnvelope:
    kind: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SUPPORTED_SCHEMA_VERSION
    request_id: str = ""
    timestamp_ms: int = 0
    deadline_ms: int = 0

    @classmethod
    def command(
        cls,
        message_type: str,
        payload: dict[str, Any] | None = None,
        *,
        request_id: str = "",
    ) -> UiEnvelope:
        return cls(
            kind="command",
            type=message_type,
            payload=payload or {},
            request_id=request_id,
            timestamp_ms=int(time.monotonic() * 1000),
        )

    @classmethod
    def from_json_line(cls, line: str) -> UiEnvelope:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UiProtocolError(f"invalid JSON UI envelope: {exc}") from exc

        if not isinstance(raw, dict):
            raise UiProtocolError("UI envelope must be a JSON object")

        envelope = cls(
            schema_version=int(raw.get("schema_version", SUPPORTED_SCHEMA_VERSION)),
            kind=str(raw.get("kind", "")),
            type=str(raw.get("type", "")),
            request_id=str(raw.get("request_id", "")),
            timestamp_ms=int(raw.get("timestamp_ms", 0)),
            deadline_ms=int(raw.get("deadline_ms", 0)),
            payload=raw.get("payload", {}),
        )
        envelope.validate()
        return envelope

    def to_json_line(self) -> str:
        self.validate()
        return (
            json.dumps(
                {
                    "schema_version": self.schema_version,
                    "kind": self.kind,
                    "type": self.type,
                    "request_id": self.request_id,
                    "timestamp_ms": self.timestamp_ms,
                    "deadline_ms": self.deadline_ms,
                    "payload": self.payload,
                },
                separators=(",", ":"),
            )
            + "\n"
        )

    def validate(self) -> None:
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise UiProtocolError(
                f"unsupported schema_version {self.schema_version}; "
                f"expected {SUPPORTED_SCHEMA_VERSION}"
            )
        if self.kind not in VALID_KINDS:
            raise UiProtocolError(f"invalid UI envelope kind {self.kind!r}")
        if not self.type:
            raise UiProtocolError("UI envelope type must be non-empty")
        if not isinstance(self.payload, dict):
            raise UiProtocolError("UI envelope payload must be an object")
