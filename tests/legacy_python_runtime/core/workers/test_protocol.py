from __future__ import annotations

import json

import pytest

from yoyopod.core.workers.protocol import (
    SUPPORTED_SCHEMA_VERSION,
    VALID_KINDS,
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)


def test_parse_valid_envelope_line() -> None:
    envelope = parse_envelope_line(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "event",
                "type": "network.status",
                "request_id": None,
                "timestamp_ms": 1777100000000,
                "deadline_ms": 5000,
                "payload": {"connected": True},
            }
        )
    )

    assert envelope == WorkerEnvelope(
        schema_version=SUPPORTED_SCHEMA_VERSION,
        kind="event",
        type="network.status",
        request_id=None,
        timestamp_ms=1777100000000,
        deadline_ms=5000,
        payload={"connected": True},
    )
    assert VALID_KINDS == {"command", "event", "result", "error", "heartbeat"}


def test_valid_kinds_is_immutable() -> None:
    assert isinstance(VALID_KINDS, frozenset)
    assert not hasattr(VALID_KINDS, "add")


def test_make_envelope_copies_payload() -> None:
    payload = {"text": "hello"}

    envelope = make_envelope(kind="result", type="voice.transcribe", payload=payload)
    payload["text"] = "changed"

    assert envelope.payload == {"text": "hello"}


def test_parse_rejects_unknown_schema_version() -> None:
    with pytest.raises(WorkerProtocolError, match="schema_version"):
        parse_envelope_line(
            json.dumps(
                {
                    "schema_version": 2,
                    "kind": "event",
                    "type": "network.status",
                    "payload": {},
                }
            )
        )


def test_parse_rejects_non_dict_payload() -> None:
    with pytest.raises(WorkerProtocolError, match="payload"):
        parse_envelope_line(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "event",
                    "type": "network.status",
                    "payload": [],
                }
            )
        )


def test_encode_envelope_is_newline_terminated_and_round_trips() -> None:
    envelope = make_envelope(
        kind="result",
        type="voice.transcribe",
        request_id="req-1",
        timestamp_ms=1777100000000,
        deadline_ms=2500,
        payload={"text": "hello"},
    )

    encoded = encode_envelope(envelope)

    assert encoded.endswith("\n")
    assert "\n" not in encoded[:-1]
    assert encoded == (
        '{"schema_version":1,"kind":"result","type":"voice.transcribe",'
        '"request_id":"req-1","timestamp_ms":1777100000000,'
        '"deadline_ms":2500,"payload":{"text":"hello"}}\n'
    )
    assert parse_envelope_line(encoded) == envelope


@pytest.mark.parametrize("line", ["{", b"{"])
def test_parse_rejects_invalid_json(line: str | bytes) -> None:
    with pytest.raises(WorkerProtocolError, match="invalid JSON"):
        parse_envelope_line(line)


@pytest.mark.parametrize("line", ["[]", "null", '"hello"'])
def test_parse_rejects_non_object_envelope(line: str) -> None:
    with pytest.raises(WorkerProtocolError, match="object"):
        parse_envelope_line(line)


@pytest.mark.parametrize("kind", ["", "unknown", 5, None])
def test_parse_rejects_invalid_kind(kind: object) -> None:
    with pytest.raises(WorkerProtocolError, match="kind"):
        parse_envelope_line(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": kind,
                    "type": "voice.transcribe",
                    "payload": {},
                }
            )
        )


@pytest.mark.parametrize("type_value", ["", "   ", 5, None])
def test_parse_rejects_empty_or_non_string_type(type_value: object) -> None:
    with pytest.raises(WorkerProtocolError, match="type"):
        parse_envelope_line(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "event",
                    "type": type_value,
                    "payload": {},
                }
            )
        )


@pytest.mark.parametrize("request_id", [5, False, {}, []])
def test_parse_rejects_non_string_non_null_request_id(request_id: object) -> None:
    with pytest.raises(WorkerProtocolError, match="request_id"):
        parse_envelope_line(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "result",
                    "type": "voice.transcribe",
                    "request_id": request_id,
                    "payload": {},
                }
            )
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("timestamp_ms", -1),
        ("deadline_ms", -1),
        ("timestamp_ms", 1.2),
        ("deadline_ms", 1.2),
        ("timestamp_ms", True),
        ("deadline_ms", False),
    ],
)
def test_parse_rejects_invalid_timestamp_and_deadline(
    field_name: str,
    value: object,
) -> None:
    data = {
        "schema_version": 1,
        "kind": "event",
        "type": "network.status",
        "payload": {},
    }
    data[field_name] = value

    with pytest.raises(WorkerProtocolError, match=field_name):
        parse_envelope_line(json.dumps(data))


def test_parse_accepts_bytes_line() -> None:
    envelope = parse_envelope_line(
        b'{"schema_version":1,"kind":"heartbeat","type":"worker.alive","payload":{}}\n'
    )

    assert envelope.kind == "heartbeat"
    assert envelope.type == "worker.alive"
