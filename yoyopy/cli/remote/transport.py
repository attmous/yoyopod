"""SSH and local execution helpers for remote Pi operations."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence

from yoyopy.cli.remote.config import RemoteConfig


def shell_quote(value: str) -> str:
    """Shell-escape one literal value for the remote command string."""

    return shlex.quote(value)


def quote_remote_project_dir(project_dir: str) -> str:
    """Quote the remote project path while preserving ``~`` expansion."""

    if project_dir == "~":
        return '"$HOME"'
    if project_dir.startswith("~/"):
        suffix = project_dir[2:].replace('"', '\\"')
        return f'"$HOME/{suffix}"'
    return shlex.quote(project_dir)


def build_ssh_command(
    config: RemoteConfig,
    remote_command: str,
    *,
    tty: bool = False,
) -> list[str]:
    """Build one SSH command targeting the Raspberry Pi."""

    wrapped_command = f"cd {quote_remote_project_dir(config.project_dir)} && {remote_command}"
    ssh_command = ["ssh"]
    if tty:
        ssh_command.append("-t")
    ssh_command.extend([config.ssh_target, f"bash -lc {shlex.quote(wrapped_command)}"])
    return ssh_command


def run_remote(config: RemoteConfig, remote_command: str, tty: bool = False) -> int:
    """Execute one command on the Raspberry Pi via SSH."""

    ssh_command = build_ssh_command(config, remote_command, tty=tty)

    print("")
    print(f"[pi-remote] host={config.ssh_target}")
    print(f"[pi-remote] dir={config.project_dir}")
    print(f"[pi-remote] cmd={remote_command}")
    print("")

    completed = subprocess.run(ssh_command, check=False)
    return completed.returncode


def run_remote_capture(
    config: RemoteConfig,
    remote_command: str,
) -> subprocess.CompletedProcess[str]:
    """Execute one SSH command and capture its stdout/stderr."""

    ssh_command = build_ssh_command(config, remote_command)
    return subprocess.run(
        ssh_command,
        check=False,
        capture_output=True,
        text=True,
    )


def run_local(command: Sequence[str], label: str) -> int:
    """Execute one local command and stream its output."""

    print("")
    print(f"[pi-remote] local={label}")
    print(f"[pi-remote] cmd={shlex.join(command)}")
    print("")

    completed = subprocess.run(list(command), check=False)
    return completed.returncode


def run_local_capture(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Execute one local command and capture its stdout/stderr."""

    return subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )


def validate_config(config: RemoteConfig) -> None:
    """Ensure required connection details are present."""

    if not config.host:
        raise SystemExit(
            "Missing Raspberry Pi host. Set it with "
            "`uv run yoyoctl remote config edit`, "
            "pass --host, or set YOYOPOD_PI_HOST."
        )
