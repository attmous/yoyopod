from __future__ import annotations

import pytest

from yoyopod_cli.contracts.worker_protocol import (
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)


def test_worker_protocol_round_trips_command_envelope() -> None:
    envelope = make_envelope(
        kind="command",
        type="network.health",
        request_id="req-1",
        payload={"check": "modem"},
    )

    encoded = encode_envelope(envelope)
    parsed = parse_envelope_line(encoded)

    assert parsed == envelope
    assert encoded.endswith("\n")
    assert '"type":"network.health"' in encoded


def test_worker_protocol_rejects_invalid_kind() -> None:
    with pytest.raises(WorkerProtocolError, match="invalid worker envelope kind"):
        make_envelope(kind="not-a-kind", type="network.health")
