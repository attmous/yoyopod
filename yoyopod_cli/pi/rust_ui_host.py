"""Whisplay-only Rust UI host validation command."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
from typing import Annotated, Literal, cast

import typer

from yoyopod_cli.contracts.worker_protocol import (
    WorkerEnvelope,
    WorkerProtocolError,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)


class RustUiHostError(RuntimeError):
    """Raised when the Rust UI host cannot be controlled."""


class RustUiHostSupervisor:
    """Tiny subprocess client for the Rust UI host worker protocol."""

    def __init__(
        self,
        *,
        argv: list[str],
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> WorkerEnvelope:
        if self.process is not None and self.process.poll() is None:
            raise RustUiHostError("Rust UI host is already running")
        self.process = subprocess.Popen(
            self.argv,
            cwd=str(self.cwd) if self.cwd is not None else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=dict(self.env) if self.env is not None else None,
        )
        return self.read_event()

    def send(self, envelope: WorkerEnvelope) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise RustUiHostError("Rust UI host stdin is not available")
        process.stdin.write(encode_envelope(envelope))
        process.stdin.flush()

    def read_event(self) -> WorkerEnvelope:
        process = self._require_process()
        if process.stdout is None:
            raise RustUiHostError("Rust UI host stdout is not available")
        line = process.stdout.readline()
        if not line:
            raise RustUiHostError("Rust UI host exited before emitting an event")
        try:
            return parse_envelope_line(line)
        except WorkerProtocolError as exc:
            raise RustUiHostError(str(exc)) from exc

    def stop(self, timeout_seconds: float = 2.0) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                self.send(ui_command("ui.shutdown"))
            except Exception:
                pass
            process.terminate()
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        self.process = None

    def _require_process(self) -> subprocess.Popen[str]:
        if self.process is None:
            raise RustUiHostError("Rust UI host is not running")
        return self.process


def ui_command(
    message_type: str,
    payload: dict[str, object] | None = None,
    *,
    request_id: str | None = None,
) -> WorkerEnvelope:
    """Build one command envelope for the Rust UI host."""

    return make_envelope(
        kind="command",
        type=message_type,
        request_id=request_id,
        payload=dict(payload or {}),
    )


def default_runtime_snapshot_payload() -> dict[str, object]:
    """Return a compact runtime snapshot sufficient for UI smoke/navigation checks."""

    return {
        "app_state": "hub",
        "hub": {
            "cards": [
                {"key": "listen", "title": "Listen", "subtitle": "Music", "accent": 0x00FF88},
                {"key": "talk", "title": "Talk", "subtitle": "Calls", "accent": 0x00D4FF},
                {"key": "ask", "title": "Ask", "subtitle": "Idle", "accent": 0x9F7AEA},
                {"key": "setup", "title": "Setup", "subtitle": "100%", "accent": 0xF6AD55},
            ]
        },
        "music": {
            "playing": False,
            "paused": False,
            "title": "Nothing Playing",
            "artist": "",
            "progress_permille": 0,
            "playlists": [],
            "recent_tracks": [],
        },
        "call": {
            "state": "idle",
            "peer_name": "",
            "peer_address": "",
            "duration_text": "",
            "muted": False,
            "contacts": [],
            "history": [],
        },
        "voice": {
            "phase": "idle",
            "headline": "Ask",
            "body": "Ask me anything...",
            "capture_in_flight": False,
            "ptt_active": False,
        },
        "power": {
            "battery_percent": 100,
            "charging": False,
            "power_available": True,
            "rows": [],
        },
        "network": {
            "enabled": False,
            "connected": False,
            "signal_strength": 0,
            "gps_has_fix": False,
        },
        "overlay": {"loading": False, "error": "", "message": ""},
    }


def _default_worker_path() -> Path:
    suffix = ".exe" if __import__("os").name == "nt" else ""
    relative = Path("device") / "ui" / "build" / f"yoyopod-ui-host{suffix}"
    packaged = Path("app") / relative
    return packaged if packaged.exists() else relative


def rust_ui_host(
    worker: Annotated[
        Path,
        typer.Option("--worker", help="Path to the Rust UI host binary."),
    ] = _default_worker_path(),
    frames: Annotated[
        int,
        typer.Option("--frames", min=1, help="Number of test scene frames to send."),
    ] = 10,
    hardware: Annotated[
        str,
        typer.Option("--hardware", help="Worker hardware mode: mock or whisplay."),
    ] = "whisplay",
    screen: Annotated[
        str,
        typer.Option("--screen", help="Screen to render: test-scene or hub."),
    ] = "test-scene",
) -> None:
    """Run the Rust UI host against Whisplay hardware."""

    selected_screen = _screen_name(screen)
    argv = [str(worker), "--hardware", hardware]
    supervisor = RustUiHostSupervisor(argv=argv, env=_native_lvgl_env())
    ready = supervisor.start()
    typer.echo(f"Rust UI host ready: {ready.payload}")

    try:
        for counter in range(1, frames + 1):
            if selected_screen == "hub":
                supervisor.send(
                    ui_command(
                        "ui.runtime_snapshot",
                        default_runtime_snapshot_payload(),
                        request_id=f"hub-frame-{counter}",
                    )
                )
            else:
                supervisor.send(
                    ui_command(
                        "ui.show_test_scene",
                        {"counter": counter},
                        request_id=f"frame-{counter}",
                    )
                )
        supervisor.send(ui_command("ui.health", request_id="health"))
        while True:
            health = supervisor.read_event()
            if health.type == "ui.health":
                break
        typer.echo(
            "Rust UI host health: "
            f"frames={health.payload.get('frames')} "
            f"button_events={health.payload.get('button_events')} "
            f"active_screen={health.payload.get('active_screen', '')} "
            f"last_ui_renderer={health.payload.get('last_ui_renderer', '')}"
        )
    finally:
        supervisor.stop()


ScreenName = Literal["test-scene", "hub"]


def _screen_name(value: str) -> ScreenName:
    if value in {"test-scene", "hub"}:
        return cast(ScreenName, value)
    raise typer.BadParameter("screen must be test-scene or hub")


def _native_lvgl_env() -> dict[str, str]:
    env = os.environ.copy()
    native_builds = [
        Path("app") / "device" / "ui" / "native" / "lvgl" / "build",
        Path("device") / "ui" / "native" / "lvgl" / "build",
    ]
    entries: list[str] = []
    for native_build in native_builds:
        entries.extend(
            [
                native_build.as_posix(),
                (native_build / "lib").as_posix(),
                (native_build / "lvgl" / "lib").as_posix(),
            ]
        )
    existing = env.get("LD_LIBRARY_PATH", "")
    if existing:
        entries.append(existing)
    env["LD_LIBRARY_PATH"] = ":".join(entries)
    return env
