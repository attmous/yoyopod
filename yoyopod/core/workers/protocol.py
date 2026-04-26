"""NDJSON envelope helpers for YoYoPod worker processes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_SCHEMA_VERSION = 1
VALID_KINDS = frozenset({"command", "event", "result", "error", "heartbeat"})


class WorkerProtocolError(ValueError):
    """Raised when a worker protocol envelope is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class WorkerEnvelope:
    """One validated worker protocol message envelope."""

    schema_version: int
    kind: str
    type: str
    request_id: str | None = None
    timestamp_ms: int = 0
    deadline_ms: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


def make_envelope(
    *,
    kind: str,
    type: str,
    request_id: str | None = None,
    timestamp_ms: int = 0,
    deadline_ms: int = 0,
    payload: dict[str, Any] | None = None,
) -> WorkerEnvelope:
    """Create a schema-version-1 worker envelope after validating fields."""

    return _validate_envelope_data(
        {
            "schema_version": SUPPORTED_SCHEMA_VERSION,
            "kind": kind,
            "type": type,
            "request_id": request_id,
            "timestamp_ms": timestamp_ms,
            "deadline_ms": deadline_ms,
            "payload": {} if payload is None else payload,
        }
    )


def parse_envelope_line(line: str | bytes) -> WorkerEnvelope:
    """Parse one NDJSON worker envelope line and validate its object shape."""

    try:
        decoded = line.decode("utf-8") if isinstance(line, bytes) else line
    except UnicodeDecodeError as exc:
        raise WorkerProtocolError("worker envelope line is not valid UTF-8") from exc

    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise WorkerProtocolError(f"invalid JSON worker envelope: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise WorkerProtocolError("worker envelope must be a JSON object")

    return _validate_envelope_data(data)


def encode_envelope(envelope: WorkerEnvelope) -> str:
    """Return stable compact newline-terminated JSON for one envelope."""

    validated = _validate_envelope_data(
        {
            "schema_version": envelope.schema_version,
            "kind": envelope.kind,
            "type": envelope.type,
            "request_id": envelope.request_id,
            "timestamp_ms": envelope.timestamp_ms,
            "deadline_ms": envelope.deadline_ms,
            "payload": envelope.payload,
        }
    )
    data = {
        "schema_version": validated.schema_version,
        "kind": validated.kind,
        "type": validated.type,
        "request_id": validated.request_id,
        "timestamp_ms": validated.timestamp_ms,
        "deadline_ms": validated.deadline_ms,
        "payload": validated.payload,
    }
    return json.dumps(data, separators=(",", ":"), ensure_ascii=True) + "\n"


def _validate_envelope_data(data: dict[str, Any]) -> WorkerEnvelope:
    schema_version = data.get("schema_version")
    if not _is_non_bool_int(schema_version) or schema_version != SUPPORTED_SCHEMA_VERSION:
        raise WorkerProtocolError(
            f"unsupported worker schema_version {schema_version!r}; "
            f"expected {SUPPORTED_SCHEMA_VERSION}"
        )

    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in VALID_KINDS:
        raise WorkerProtocolError(f"invalid worker envelope kind {kind!r}")

    type_value = data.get("type")
    if not isinstance(type_value, str) or not type_value.strip():
        raise WorkerProtocolError("worker envelope type must be a non-empty string")

    request_id = data.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise WorkerProtocolError("worker envelope request_id must be a string or null")

    timestamp_ms = data.get("timestamp_ms", 0)
    if not _is_non_negative_int(timestamp_ms):
        raise WorkerProtocolError("worker envelope timestamp_ms must be a non-negative integer")

    deadline_ms = data.get("deadline_ms", 0)
    if not _is_non_negative_int(deadline_ms):
        raise WorkerProtocolError("worker envelope deadline_ms must be a non-negative integer")

    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise WorkerProtocolError("worker envelope payload must be a JSON object")

    return WorkerEnvelope(
        schema_version=schema_version,
        kind=kind,
        type=type_value,
        request_id=request_id,
        timestamp_ms=timestamp_ms,
        deadline_ms=deadline_ms,
        payload=dict(payload),
    )


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_non_bool_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
