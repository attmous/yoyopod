"""SSH and local subprocess helpers for remote Pi operations."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence

from yoyopod_cli.remote_shared import RemoteConnection


def shell_quote(value: str) -> str:
    """Shell-escape a literal value."""
    return shlex.quote(value)


def quote_remote_project_dir(project_dir: str) -> str:
    """Quote the remote project path, preserving ``~`` expansion.

    The ``~/`` suffix is placed inside double quotes where ``$HOME`` expands.
    Embedded ``$``, backticks, and ``"`` in the suffix are escaped so they
    are not interpreted as command substitution. Intended for trusted,
    developer-controlled paths from deploy YAML or CLI flags.
    """
    if project_dir == "~":
        return '"$HOME"'
    if project_dir.startswith("~/"):
        suffix = (
            project_dir[2:]
            .replace("\\", "\\\\")  # escape backslashes first
            .replace('"', '\\"')  # then embedded double quotes
            .replace("$", "\\$")  # then dollar signs
            .replace("`", "\\`")  # then backticks
        )
        return f'"$HOME/{suffix}"'
    return shlex.quote(project_dir)


def venv_activate_prefix(venv_relpath: str = ".venv") -> str:
    """Return a shell fragment that activates the Pi's venv before invoking ``yoyopod``.

    SSH sessions started with ``bash -lc`` are login shells but do not auto-activate
    per-project virtualenvs. Prepending this to any remote command that needs the
    ``yoyopod`` console script ensures it is resolved from the repo's venv.
    """
    return f"source {venv_relpath}/bin/activate"


def build_ssh_command(
    conn: RemoteConnection,
    remote_command: str,
    *,
    tty: bool = False,
) -> list[str]:
    """Build an SSH command targeting the Pi."""
    wrapped = f"cd {quote_remote_project_dir(conn.project_dir)} && {remote_command}"
    cmd = ["ssh"]
    if tty:
        cmd.append("-t")
    cmd.extend([conn.ssh_target, f"bash -lc {shlex.quote(wrapped)}"])
    return cmd


def run_remote(conn: RemoteConnection, remote_command: str, *, tty: bool = False) -> int:
    """Execute a command on the Pi via SSH. Returns the exit code."""
    ssh_cmd = build_ssh_command(conn, remote_command, tty=tty)
    print("")
    print(f"[yoyopod-remote] host={conn.ssh_target}")
    print(f"[yoyopod-remote] dir={conn.project_dir}")
    print(f"[yoyopod-remote] cmd={remote_command}")
    print("")
    completed = subprocess.run(ssh_cmd, check=False)
    return completed.returncode


def run_remote_capture(
    conn: RemoteConnection,
    remote_command: str,
) -> subprocess.CompletedProcess[str]:
    """Execute an SSH command and capture stdout/stderr."""
    ssh_cmd = build_ssh_command(conn, remote_command)
    return subprocess.run(ssh_cmd, check=False, capture_output=True, text=True)


def run_local(command: Sequence[str], label: str) -> int:
    """Execute a local command and stream its output."""
    print("")
    print(f"[yoyopod-remote] local={label}")
    print(f"[yoyopod-remote] cmd={shlex.join(command)}")
    print("")
    completed = subprocess.run(list(command), check=False)
    return completed.returncode


def run_local_capture(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Execute a local command and capture stdout/stderr."""
    return subprocess.run(list(command), check=False, capture_output=True, text=True)


def validate_config(conn: RemoteConnection) -> None:
    """Ensure required connection details are present."""
    if not conn.host:
        raise SystemExit(
            "Missing Raspberry Pi host. Set it with "
            "`yoyopod remote config edit`, pass --host, or set YOYOPOD_PI_HOST."
        )
