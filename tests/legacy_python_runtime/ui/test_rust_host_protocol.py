from __future__ import annotations

import pytest

from yoyopod.ui.rust_host.hub import RustHubSnapshot
from yoyopod.ui.rust_host.protocol import UiEnvelope, UiProtocolError


def test_parse_ready_event_defaults_schema_version() -> None:
    envelope = UiEnvelope.from_json_line(
        '{"kind":"event","type":"ui.ready","payload":{"display":{"width":240}}}'
    )

    assert envelope.schema_version == 1
    assert envelope.kind == "event"
    assert envelope.type == "ui.ready"
    assert envelope.payload["display"]["width"] == 240


def test_command_encoder_uses_ui_prefix() -> None:
    line = UiEnvelope.command("ui.health").to_json_line()

    assert line.endswith("\n")
    assert '"kind":"command"' in line
    assert '"type":"ui.health"' in line


def test_rejects_non_object_payload() -> None:
    with pytest.raises(UiProtocolError, match="payload"):
        UiEnvelope.from_json_line('{"kind":"event","type":"ui.ready","payload":[]}')


def test_static_hub_payload_uses_lvgl_sync_contract_names() -> None:
    payload = RustHubSnapshot.static().to_payload(renderer="lvgl")

    assert payload["renderer"] == "lvgl"
    assert payload["title"] == "Listen"
    assert payload["selected_index"] == 0
    assert payload["total_cards"] == 4
