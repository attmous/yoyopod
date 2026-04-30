from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from yoyopod.ui.rust_host.protocol import UiEnvelope
from yoyopod.ui.rust_host.snapshot import RustUiRuntimeSnapshot
from yoyopod_cli.pi import app
import yoyopod_cli.pi.rust_ui_host as rust_ui_host


class _FakeSupervisor:
    instances: list["_FakeSupervisor"] = []

    def __init__(
        self,
        argv: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env or {}
        self.sent: list[UiEnvelope] = []
        self._events: list[UiEnvelope] = []
        self.instances.append(self)

    def start(self) -> UiEnvelope:
        return UiEnvelope(
            kind="event",
            type="ui.ready",
            payload={"display": {"width": 240}},
        )

    def send(self, envelope: UiEnvelope) -> None:
        self.sent.append(envelope)
        if envelope.type == "ui.runtime_snapshot":
            self._events.append(
                UiEnvelope(
                    kind="event",
                    type="ui.screen_changed",
                    payload={"screen": "hub", "title": "Listen"},
                )
            )
        elif envelope.type == "ui.health":
            self._events.append(
                UiEnvelope(
                    kind="event",
                    type="ui.health",
                    payload={
                        "frames": 1,
                        "button_events": 0,
                        "active_screen": "hub",
                        "last_ui_renderer": "framebuffer",
                    },
                )
            )

    def read_event(self) -> UiEnvelope:
        return self._events.pop(0)

    def stop(self) -> None:
        return None


def test_rust_ui_host_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rust-ui-host", "--help"])

    assert result.exit_code == 0
    assert "rust ui host" in result.output.lower()


def test_rust_ui_host_runs_supervisor(monkeypatch, tmp_path: Path) -> None:
    worker = tmp_path / "yoyopod-ui-host"
    worker.write_text("fake", encoding="utf-8")
    _FakeSupervisor.instances.clear()
    monkeypatch.setattr(rust_ui_host, "RustUiHostSupervisor", _FakeSupervisor)

    runner = CliRunner()
    result = runner.invoke(app, ["rust-ui-host", "--worker", str(worker), "--frames", "1"])

    assert result.exit_code == 0
    assert "ready" in result.output.lower()
    assert "frames=1" in result.output
    assert "yoyopod/ui/lvgl_binding/native/build" in _FakeSupervisor.instances[-1].env[
        "LD_LIBRARY_PATH"
    ]


def test_rust_ui_host_sends_runtime_snapshot_for_hub_screen(
    monkeypatch, tmp_path: Path
) -> None:
    worker = tmp_path / "yoyopod-ui-host"
    worker.write_text("fake", encoding="utf-8")
    _FakeSupervisor.instances.clear()
    monkeypatch.setattr(rust_ui_host, "RustUiHostSupervisor", _FakeSupervisor)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "rust-ui-host",
            "--worker",
            str(worker),
            "--frames",
            "1",
            "--screen",
            "hub",
        ],
    )

    assert result.exit_code == 0
    sent = _FakeSupervisor.instances[-1].sent[0]
    assert sent.type == "ui.runtime_snapshot"
    assert sent.request_id == "hub-frame-1"
    assert sent.payload == RustUiRuntimeSnapshot().to_payload()
    assert [card["title"] for card in sent.payload["hub"]["cards"]] == [
        "Listen",
        "Talk",
        "Ask",
        "Setup",
    ]
    assert "active_screen=hub" in result.output
    assert "last_ui_renderer=framebuffer" in result.output
