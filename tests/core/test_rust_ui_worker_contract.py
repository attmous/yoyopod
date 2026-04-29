from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RUST_UI_MANIFEST = Path("yoyopod_rs/Cargo.toml")


def test_rust_ui_worker_mock_contract() -> None:
    if shutil.which("cargo") is None:
        pytest.skip("cargo toolchain not available")

    command = {
        "schema_version": 1,
        "kind": "command",
        "type": "ui.show_test_scene",
        "request_id": "frame-contract",
        "timestamp_ms": 1,
        "deadline_ms": 1000,
        "payload": {"counter": 1},
    }
    shutdown = {
        "schema_version": 1,
        "kind": "command",
        "type": "ui.shutdown",
        "request_id": "shutdown",
        "timestamp_ms": 2,
        "deadline_ms": 1000,
        "payload": {},
    }

    result = subprocess.run(
        [
            "cargo",
            "run",
            "--manifest-path",
            RUST_UI_MANIFEST.as_posix(),
            "--quiet",
            "--bin",
            "yoyopod-ui-host",
            "--",
            "--hardware",
            "mock",
        ],
        input=json.dumps(command) + "\n" + json.dumps(shutdown) + "\n",
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert envelopes[0]["type"] == "ui.ready"


def test_rust_ui_worker_accepts_static_hub_command() -> None:
    if shutil.which("cargo") is None:
        pytest.skip("cargo toolchain not available")

    command = {
        "schema_version": 1,
        "kind": "command",
        "type": "ui.show_hub",
        "request_id": "hub-contract",
        "timestamp_ms": 1,
        "deadline_ms": 1000,
        "payload": {"renderer": "framebuffer", "title": "Listen"},
    }
    health = {
        "schema_version": 1,
        "kind": "command",
        "type": "ui.health",
        "request_id": "health",
        "timestamp_ms": 2,
        "deadline_ms": 1000,
        "payload": {},
    }
    shutdown = {
        "schema_version": 1,
        "kind": "command",
        "type": "ui.shutdown",
        "request_id": "shutdown",
        "timestamp_ms": 3,
        "deadline_ms": 1000,
        "payload": {},
    }

    result = subprocess.run(
        [
            "cargo",
            "run",
            "--manifest-path",
            RUST_UI_MANIFEST.as_posix(),
            "--quiet",
            "--bin",
            "yoyopod-ui-host",
            "--",
            "--hardware",
            "mock",
        ],
        input="\n".join(json.dumps(item) for item in (command, health, shutdown)) + "\n",
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert envelopes[0]["type"] == "ui.ready"
    assert envelopes[-1]["type"] == "ui.health"
    assert envelopes[-1]["payload"]["frames"] == 1
    assert envelopes[-1]["payload"]["last_hub_renderer"] == "framebuffer"
