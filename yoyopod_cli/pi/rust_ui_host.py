"""Whisplay-only Rust UI host validation command."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal, cast

import typer

from yoyopod.ui.rust_host.protocol import UiEnvelope
from yoyopod.ui.rust_host.snapshot import RustUiRuntimeSnapshot
from yoyopod.ui.rust_host.supervisor import RustUiHostSupervisor


def _default_worker_path() -> Path:
    suffix = ".exe" if __import__("os").name == "nt" else ""
    return Path("yoyopod_rs") / "ui-host" / "build" / f"yoyopod-ui-host{suffix}"


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
                    UiEnvelope.command(
                        "ui.runtime_snapshot",
                        RustUiRuntimeSnapshot().to_payload(),
                        request_id=f"hub-frame-{counter}",
                    )
                )
            else:
                supervisor.send(
                    UiEnvelope.command(
                        "ui.show_test_scene",
                        {"counter": counter},
                        request_id=f"frame-{counter}",
                    )
                )
        supervisor.send(UiEnvelope.command("ui.health", request_id="health"))
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
    native_build = Path("yoyopod") / "ui" / "lvgl_binding" / "native" / "build"
    native_lib = native_build / "lib"
    entries = [native_build.as_posix(), native_lib.as_posix()]
    existing = env.get("LD_LIBRARY_PATH", "")
    if existing:
        entries.append(existing)
    env["LD_LIBRARY_PATH"] = ":".join(entries)
    return env
