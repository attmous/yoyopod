"""Screenshot capture helpers for remote Pi display."""

from __future__ import annotations

import argparse
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Protocol

import typer

from yoyopod.cli.remote.config import PiDeployConfig, RemoteConfig
from yoyopod.cli.remote.transport import run_remote_capture, validate_config

from .validation import _resolve_remote_config


class RemoteCaptureFn(Protocol):
    """Callable contract for SSH capture helpers."""

    def __call__(
        self,
        config: RemoteConfig,
        remote_command: str,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunFn(Protocol):
    """Callable contract for local subprocess runners."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess[object]: ...


def run_screenshot(
    config: RemoteConfig,
    deploy_config: PiDeployConfig,
    args: argparse.Namespace,
    *,
    run_remote_capture_fn: RemoteCaptureFn,
    subprocess_run_fn: SubprocessRunFn,
) -> int:
    """Capture a screenshot from the remote app and copy it locally."""
    wait_seconds = 20
    pid_file = shlex.quote(deploy_config.pid_file)
    screenshot_path = shlex.quote(deploy_config.screenshot_path)

    alive_result = run_remote_capture_fn(
        config,
        f"test -f {pid_file} && kill -0 $(cat {pid_file}) 2>/dev/null && echo ALIVE || echo DEAD",
    )
    if alive_result.returncode != 0 or alive_result.stdout.strip() != "ALIVE":
        print("Remote app is not running; restart it before requesting a screenshot.")
        if alive_result.stderr.strip():
            print(alive_result.stderr.strip())
        return 1

    clear_result = run_remote_capture_fn(
        config,
        f"rm -f {screenshot_path}",
    )
    if clear_result.returncode != 0:
        print("Failed to clear the previous screenshot on the Raspberry Pi.")
        if clear_result.stderr.strip():
            print(clear_result.stderr.strip())
        return clear_result.returncode

    signal_name = "USR1" if args.readback else "USR2"
    signal_result = run_remote_capture_fn(
        config,
        f"kill -{signal_name} $(cat {pid_file})",
    )
    if signal_result.returncode != 0:
        print("Failed to trigger screenshot capture on the Raspberry Pi.")
        if signal_result.stderr.strip():
            print(signal_result.stderr.strip())
        return signal_result.returncode

    verify_result = run_remote_capture_fn(
        config,
        (
            f"for _ in $(seq 1 {wait_seconds}); do "
            f"test -f {screenshot_path} && echo READY && exit 0; "
            "sleep 1; "
            "done; "
            "echo MISSING"
        ),
    )
    if verify_result.returncode != 0 or verify_result.stdout.strip() != "READY":
        print(
            "Screenshot was not created on the Raspberry Pi. "
            "Confirm the app is running and screenshot handlers are installed. "
            "If the app is wedged, inspect `yoyoctl remote logs --errors` for the "
            "traceback dump and runtime snapshot triggered by the screenshot signal."
        )
        if verify_result.stderr.strip():
            print(verify_result.stderr.strip())
        return 1

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scp_command = [
        "scp",
        f"{config.ssh_target}:{deploy_config.screenshot_path}",
        str(output_path),
    ]
    print("")
    print("[pi-remote] local=screenshot-copy")
    print(f"[pi-remote] cmd={shlex.join(scp_command)}")
    print("")
    copy_result = subprocess_run_fn(scp_command, check=False)
    if copy_result.returncode == 0:
        print(f"Saved screenshot to {output_path}")
    return copy_result.returncode


def screenshot(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    output: Annotated[
        str, typer.Option("--output", help="Local output file path.")
    ] = "screenshot.png",
    readback: Annotated[
        bool,
        typer.Option(
            "--readback", help="Use LVGL readback (SIGUSR1) instead of shadow path (SIGUSR2)."
        ),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Capture a screenshot from the Pi display."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    from yoyopod.cli.remote.config import load_pi_deploy_config

    deploy_config = load_pi_deploy_config()
    args = argparse.Namespace(readback=readback, output=output)
    rc = run_screenshot(
        config,
        deploy_config,
        args,
        run_remote_capture_fn=run_remote_capture,
        subprocess_run_fn=subprocess.run,
    )
    if rc != 0:
        raise typer.Exit(code=rc)


__all__ = [
    "run_screenshot",
    "screenshot",
]
