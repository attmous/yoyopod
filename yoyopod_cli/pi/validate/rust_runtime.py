"""Rust runtime stack probes used by target validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from yoyopod_cli.pi.rust_ui_host import _native_lvgl_env
from yoyopod_cli.pi.support.rust_ui_host import (
    RustUiHostSupervisor,
    RustUiRuntimeSnapshot,
    UiEnvelope,
)
from yoyopod_cli.pi.validate._common import _CheckResult


def _binary_name(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    return f"{name}{suffix}"


def _slot_aware_path(relative_path: Path) -> Path:
    candidates = [
        Path("app") / relative_path,
        relative_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return relative_path


def _default_runtime_worker_path() -> Path:
    return _slot_aware_path(Path("device") / "runtime" / "build" / _binary_name("yoyopod-runtime"))


def _default_ui_worker_path() -> Path:
    return _slot_aware_path(Path("device") / "ui" / "build" / _binary_name("yoyopod-ui-host"))


def _ui_hardware(app_config: dict[str, Any]) -> str:
    display = app_config.get("display", {})
    configured = ""
    if isinstance(display, dict):
        configured = str(display.get("hardware", "")).strip().lower()
    if configured in {"mock", "whisplay"}:
        return configured
    return "whisplay"


def rust_runtime_dry_run_check(config_dir: Path, worker: Path | None = None) -> _CheckResult:
    """Run the Rust runtime config/load path without starting hardware workers."""

    runtime_worker = worker or _default_runtime_worker_path()
    if not runtime_worker.exists():
        return _CheckResult(
            name="rust-runtime",
            status="fail",
            details=f"missing Rust runtime binary at {runtime_worker}",
        )

    try:
        completed = subprocess.run(
            [str(runtime_worker), "--config-dir", str(config_dir), "--dry-run"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return _CheckResult(name="rust-runtime", status="fail", details=str(exc))

    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        return _CheckResult(
            name="rust-runtime",
            status="fail",
            details=details or f"dry-run exited {completed.returncode}",
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _CheckResult(
            name="rust-runtime",
            status="fail",
            details=f"dry-run did not emit JSON config: {exc}",
        )

    worker_paths = payload.get("worker_paths", {}) if isinstance(payload, dict) else {}
    configured_workers = len(worker_paths) if isinstance(worker_paths, dict) else 0
    return _CheckResult(
        name="rust-runtime",
        status="pass",
        details=f"binary={runtime_worker}, dry_run=ok, worker_paths={configured_workers}",
    )


def rust_ui_smoke_check(
    config_dir: Path,
    app_config: dict[str, Any],
    hold_seconds: float,
    worker: Path | None = None,
) -> _CheckResult:
    """Render one Rust runtime snapshot through the Rust UI host and require health."""

    del config_dir
    worker_path = worker or _default_ui_worker_path()
    if not worker_path.exists():
        return _CheckResult(
            name="rust-ui",
            status="fail",
            details=f"missing Rust UI host binary at {worker_path}",
        )

    hardware = _ui_hardware(app_config)
    supervisor = RustUiHostSupervisor(
        argv=[str(worker_path), "--hardware", hardware],
        env=_native_lvgl_env(),
    )
    try:
        ready = supervisor.start()
        if ready.type != "ui.ready":
            return _CheckResult(
                name="rust-ui",
                status="fail",
                details=f"expected ui.ready, got {ready.type}",
            )

        payload = RustUiRuntimeSnapshot().to_payload()
        supervisor.send(
            UiEnvelope.command(
                "ui.runtime_snapshot",
                payload,
                request_id="smoke-runtime-snapshot",
            )
        )
        _read_until(supervisor, {"ui.screen_changed"})
        if hold_seconds > 0:
            time.sleep(hold_seconds)
        health = _request_health(supervisor)
        _require_healthy_ui(health.payload)
        return _CheckResult(
            name="rust-ui",
            status="pass",
            details=_format_ui_health(worker_path, hardware, health.payload),
        )
    except Exception as exc:
        return _CheckResult(name="rust-ui", status="fail", details=str(exc))
    finally:
        supervisor.stop()


def rust_ui_navigation_check(
    config_dir: Path,
    cycles: int,
    hold_seconds: float,
    idle_seconds: float,
    tail_idle_seconds: float,
    worker: Path | None = None,
) -> _CheckResult:
    """Drive Rust UI semantic navigation through the worker protocol."""

    del config_dir
    worker_path = worker or _default_ui_worker_path()
    if not worker_path.exists():
        return _CheckResult(
            name="rust-ui-navigation",
            status="fail",
            details=f"missing Rust UI host binary at {worker_path}",
        )

    supervisor = RustUiHostSupervisor(
        argv=[str(worker_path), "--hardware", "whisplay"],
        env=_native_lvgl_env(),
    )
    try:
        ready = supervisor.start()
        if ready.type != "ui.ready":
            return _CheckResult(
                name="rust-ui-navigation",
                status="fail",
                details=f"expected ui.ready, got {ready.type}",
            )

        supervisor.send(
            UiEnvelope.command(
                "ui.runtime_snapshot",
                RustUiRuntimeSnapshot().to_payload(),
                request_id="navigation-runtime-snapshot",
            )
        )
        _expect_screen(supervisor, "hub")

        visited: list[str] = ["hub"]
        for cycle in range(max(1, cycles)):
            _send_input(supervisor, "select", f"navigation-{cycle}-select")
            visited.append(_expect_screen(supervisor, "listen"))
            _sleep(hold_seconds)
            _sleep(idle_seconds)

            _send_input(supervisor, "back", f"navigation-{cycle}-back")
            visited.append(_expect_screen(supervisor, "hub"))
            _sleep(hold_seconds)

            _send_input(supervisor, "advance", f"navigation-{cycle}-advance")
            health = _request_health(supervisor)
            _require_healthy_ui(health.payload)
            _sleep(hold_seconds)

        _sleep(tail_idle_seconds)
        health = _request_health(supervisor)
        _require_healthy_ui(health.payload)
        return _CheckResult(
            name="rust-ui-navigation",
            status="pass",
            details=(
                f"binary={worker_path}, protocol=ui.runtime_snapshot/ui.input_action, "
                f"visited={','.join(visited)}, frames={health.payload.get('frames')}, "
                f"active_screen={health.payload.get('active_screen')}"
            ),
        )
    except Exception as exc:
        return _CheckResult(name="rust-ui-navigation", status="fail", details=str(exc))
    finally:
        supervisor.stop()


def _send_input(supervisor: RustUiHostSupervisor, action: str, request_id: str) -> None:
    payload = RustUiRuntimeSnapshot().to_payload()
    payload["action"] = action
    supervisor.send(UiEnvelope.command("ui.input_action", payload, request_id=request_id))


def _expect_screen(supervisor: RustUiHostSupervisor, screen: str) -> str:
    event = _read_until(supervisor, {"ui.screen_changed"})
    observed = str(event.payload.get("screen", ""))
    if observed != screen:
        raise RuntimeError(f"expected Rust UI screen {screen}, got {observed or event.payload}")
    return observed


def _request_health(supervisor: RustUiHostSupervisor) -> UiEnvelope:
    supervisor.send(UiEnvelope.command("ui.health", request_id="health"))
    return _read_until(supervisor, {"ui.health"})


def _read_until(supervisor: RustUiHostSupervisor, event_types: set[str]) -> UiEnvelope:
    for _ in range(32):
        event = supervisor.read_event()
        if event.type == "ui.error":
            raise RuntimeError(f"Rust UI host error: {event.payload}")
        if event.type in event_types:
            return event
    raise RuntimeError(f"Rust UI host did not emit any of {sorted(event_types)}")


def _require_healthy_ui(payload: dict[str, Any]) -> None:
    frames = int(payload.get("frames", 0))
    renderer = str(payload.get("last_ui_renderer", "")).strip()
    active_screen = str(payload.get("active_screen", "")).strip()
    if frames < 1:
        raise RuntimeError(f"Rust UI host rendered no frames: {payload}")
    if not renderer:
        raise RuntimeError(f"Rust UI host did not report a renderer: {payload}")
    if not active_screen:
        raise RuntimeError(f"Rust UI host did not report an active screen: {payload}")


def _format_ui_health(worker_path: Path, hardware: str, payload: dict[str, Any]) -> str:
    return (
        f"binary={worker_path}, hardware={hardware}, frames={payload.get('frames')}, "
        f"button_events={payload.get('button_events')}, "
        f"active_screen={payload.get('active_screen')}, "
        f"last_ui_renderer={payload.get('last_ui_renderer')}"
    )


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
