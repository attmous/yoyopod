# CLI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the YoyoPod CLI into a flat `yoyopod_cli/` package at the repo root, rename the entry point `yoyopod` → `yoyopod`, prune ~15 unused commands, consolidate path constants into `paths.py`, and apply one uniform command template across every file.

**Architecture:** New flat package at `yoyopod_cli/` (sibling of `src/`). Every command follows a single template: typed Typer handler → `pi_conn(ctx)` for shared Pi connection → inline f-string shell command → `raise typer.Exit(run_remote(...))`. No intermediate builder layer for simple commands; complex multi-line shell remains a private helper in the same file. `pyproject.toml` scripts collapse from `yoyopod` + `yoyopod` to just `yoyopod`, with a root callback launching the app when no subcommand is passed. The current `src/yoyopod/cli/` tree is deleted wholesale once the new one is green.

**Tech Stack:** Python 3.12, Typer, loguru, pyyaml, pytest, uv, hatch.

**Spec:** [docs/superpowers/specs/2026-04-20-cli-polish-design.md](../specs/2026-04-20-cli-polish-design.md)

---

## Shared Patterns (reference — read before any task)

Every command file in `yoyopod_cli/` follows the **same template**. You will see this shape 11 times across the plan; each task shows the specific command body, but the surrounding structure is always this:

### Remote command template (`remote_*.py`)

```python
# yoyopod_cli/remote_<group>.py
from __future__ import annotations

import shlex
import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import load_pi_paths
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import run_remote

app = build_remote_app("<group>", "<group help text>.")


@app.command()
def <command_name>(
    ctx: typer.Context,
    # command-specific options here
    verbose: bool = typer.Option(False, "--verbose", help="Enable DEBUG logging."),
) -> None:
    """<command docstring>."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    pi = load_pi_paths()

    # build the shell command (inline f-string for simple commands)
    cmd = f"..."

    raise typer.Exit(run_remote(conn, cmd))
```

### Pi command template (`pi_*.py`)

On-Pi commands don't need `pi_conn(ctx)` — they run directly. They still use `configure_logging` and read app config via `resolve_config_dir`.

```python
# yoyopod_cli/pi_<group>.py
from __future__ import annotations

from typing import Annotated

import typer

from yoyopod_cli.common import configure_logging, resolve_config_dir

app = typer.Typer(name="<group>", help="<group help text>.", no_args_is_help=True)


@app.command()
def <command_name>(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory.")] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """<command docstring>."""
    from yoyopod.config import ConfigManager
    # ...heavy imports lazy-loaded inside the function

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)
    # ...command logic
```

### Complex shell — private helpers, same file

Simple shell commands go inline. Complex multi-line shell scripts (startup verification, native shim refresh, deploy validation — the ones in current `ops/commands.py`) live as **private helpers above the command** that uses them in the same file. The rule: the reader holds one file to understand one command. No central `commands.py` re-export file.

```python
def _build_startup_verification(pi: PiPaths, attempts: int = 20) -> str:
    """Build the multi-line shell script that waits for the startup marker."""
    pid_file = shlex.quote(pi.pid_file)
    # ... complex logic
    return " && ".join([...])


@app.command()
def status(ctx: typer.Context) -> None:
    conn = pi_conn(ctx)
    pi = load_pi_paths()
    cmd = _build_startup_verification(pi)
    raise typer.Exit(run_remote(conn, cmd))
```

### Testing approach

**Unit-test private helpers** (the `_build_*` functions) for shell-string correctness. **Integration-test commands** by invoking the Typer app via `runner.invoke(app, [...])` with mocked `run_remote`. No `argparse.Namespace` anywhere.

---

## Task 1: Scaffold `yoyopod_cli/` package skeleton

**Files:**
- Create: `yoyopod_cli/__init__.py`
- Create: `yoyopod_cli/common.py`
- Test: `tests/test_yoyopod_cli_bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_bootstrap.py
"""Smoke test for the new yoyopod_cli package scaffold."""
from __future__ import annotations

import importlib


def test_package_imports() -> None:
    module = importlib.import_module("yoyopod_cli")
    assert module.__name__ == "yoyopod_cli"


def test_version_exposed() -> None:
    module = importlib.import_module("yoyopod_cli")
    assert isinstance(module.__version__, str)
    assert module.__version__


def test_common_imports() -> None:
    module = importlib.import_module("yoyopod_cli.common")
    assert callable(module.configure_logging)
    assert callable(module.resolve_config_dir)
    assert module.REPO_ROOT.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_bootstrap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli'`

- [ ] **Step 3: Create `yoyopod_cli/__init__.py`**

```python
# yoyopod_cli/__init__.py
"""yoyopod_cli — flat CLI package for YoyoPod.

Entry point is `yoyopod_cli.main:run`. See COMMANDS.md for the full command reference.
"""

from __future__ import annotations

__version__ = "0.1.0"
```

- [ ] **Step 4: Create `yoyopod_cli/common.py`**

```python
# yoyopod_cli/common.py
"""Shared CLI helpers (logging, repo root, config dir resolution)."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]


def configure_logging(verbose: bool) -> None:
    """Configure loguru for CLI commands."""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="{time:HH:mm:ss} | {level:<7} | {message}")


def resolve_config_dir(config_dir: str) -> Path:
    """Resolve a config directory relative to the repo root."""
    path = Path(config_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_yoyopod_cli_bootstrap.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add yoyopod_cli/__init__.py yoyopod_cli/common.py tests/test_yoyopod_cli_bootstrap.py
git commit -m "feat(cli): scaffold yoyopod_cli package skeleton"
```

---

## Task 2: Create `yoyopod_cli/paths.py` with dataclasses and YAML merger

**Files:**
- Create: `yoyopod_cli/paths.py`
- Test: `tests/test_yoyopod_cli_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_paths.py
"""Tests for yoyopod_cli.paths — the single source of truth for path constants."""
from __future__ import annotations

from pathlib import Path

import pytest

from yoyopod_cli.paths import (
    CONFIGS,
    HOST,
    PI_DEFAULTS,
    PROCS,
    PiPaths,
    load_pi_paths,
)


def test_host_paths_resolve() -> None:
    assert HOST.repo_root.exists()
    assert HOST.deploy_config == HOST.repo_root / "deploy" / "pi-deploy.yaml"
    assert HOST.deploy_config_local == HOST.repo_root / "deploy" / "pi-deploy.local.yaml"


def test_pi_defaults_populated() -> None:
    assert PI_DEFAULTS.project_dir == "~/YoyoPod_Core"
    assert PI_DEFAULTS.log_file == "logs/yoyopod.log"
    assert PI_DEFAULTS.pid_file == "/tmp/yoyopod.pid"
    assert "python" in PI_DEFAULTS.kill_processes


def test_configs_paths_exist() -> None:
    assert CONFIGS.core.exists()
    assert CONFIGS.music.exists()
    assert CONFIGS.calling.exists()


def test_procs_known() -> None:
    assert PROCS.app == "python yoyopod.py"
    assert PROCS.mpv == "mpv"


def test_load_pi_paths_returns_defaults_when_no_override(tmp_path, monkeypatch) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "log_file: logs/yoyopod.log\n"
        "error_log_file: logs/yoyopod_errors.log\n"
        "pid_file: /tmp/yoyopod.pid\n"
        "startup_marker: YoyoPod starting\n"
    )
    local_yaml = tmp_path / "local.yaml"  # does not exist

    result = load_pi_paths(base_path=base_yaml, local_path=local_yaml)
    assert isinstance(result, PiPaths)
    assert result.log_file == "logs/yoyopod.log"
    assert result.project_dir == "~/YoyoPod_Core"  # default, no override


def test_load_pi_paths_applies_local_override(tmp_path) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "log_file: logs/yoyopod.log\n"
        "error_log_file: logs/yoyopod_errors.log\n"
        "pid_file: /tmp/yoyopod.pid\n"
        "startup_marker: YoyoPod starting\n"
    )
    local_yaml = tmp_path / "local.yaml"
    local_yaml.write_text("host: rpi-zero\nproject_dir: /opt/yoyopod\n")

    result = load_pi_paths(base_path=base_yaml, local_path=local_yaml)
    assert result.project_dir == "/opt/yoyopod"  # overridden
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.paths'`

- [ ] **Step 3: Create `yoyopod_cli/paths.py`**

```python
# yoyopod_cli/paths.py
"""All CLI paths and process constants — single source of truth.

If a path or process name changes, edit this file and only this file.
Per-host overrides still live in deploy/pi-deploy.local.yaml.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class HostPaths:
    """Paths on the dev machine."""

    repo_root: Path = REPO_ROOT
    deploy_config: Path = REPO_ROOT / "deploy" / "pi-deploy.yaml"
    deploy_config_local: Path = REPO_ROOT / "deploy" / "pi-deploy.local.yaml"
    systemd_unit_template: Path = REPO_ROOT / "deploy" / "systemd" / "yoyopod@.service"


@dataclass(frozen=True)
class PiPaths:
    """Default Pi-side paths (overridable via pi-deploy.local.yaml)."""

    project_dir: str = "~/YoyoPod_Core"
    venv: str = ".venv"
    start_cmd: str = "python yoyopod.py"
    log_file: str = "logs/yoyopod.log"
    error_log_file: str = "logs/yoyopod_errors.log"
    pid_file: str = "/tmp/yoyopod.pid"
    screenshot_path: str = "/tmp/yoyopod_screenshot.png"
    test_music_target_dir: str = "logs/test-music"
    startup_marker: str = "YoyoPod starting"
    kill_processes: tuple[str, ...] = ("python", "linphonec")
    rsync_exclude: tuple[str, ...] = (
        ".git/",
        ".cache/",
        "__pycache__/",
        "*.pyc",
        ".venv/",
        "build/",
        "logs/",
        "models/",
        "node_modules/",
        "*.egg-info/",
    )


@dataclass(frozen=True)
class ConfigFiles:
    """YAML configs the app reads; referenced by CLI commands."""

    core: Path = REPO_ROOT / "config" / "app" / "core.yaml"
    music: Path = REPO_ROOT / "config" / "audio" / "music.yaml"
    hardware: Path = REPO_ROOT / "config" / "device" / "hardware.yaml"
    cellular: Path = REPO_ROOT / "config" / "network" / "cellular.yaml"
    voice: Path = REPO_ROOT / "config" / "voice" / "assistant.yaml"
    calling: Path = REPO_ROOT / "config" / "communication" / "calling.yaml"
    messaging: Path = REPO_ROOT / "config" / "communication" / "messaging.yaml"
    people: Path = REPO_ROOT / "config" / "people" / "directory.yaml"
    cloud_backend: Path = REPO_ROOT / "config" / "cloud" / "backend.yaml"


@dataclass(frozen=True)
class ProcessNames:
    """Process names used in kill/grep operations."""

    app: str = "python yoyopod.py"
    mpv: str = "mpv"
    linphonec: str = "linphonec"


HOST = HostPaths()
PI_DEFAULTS = PiPaths()
CONFIGS = ConfigFiles()
PROCS = ProcessNames()


def _load_yaml(path: Path) -> dict[str, object]:
    """Load one YAML mapping from disk; return {} if missing."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Expected YAML mapping in {path}")
    return data


def _as_str_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize a YAML list into a tuple of non-empty strings."""
    if isinstance(value, str):
        candidates: Sequence[object] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        candidates = value
    else:
        return default
    normalized = tuple(str(item).strip() for item in candidates if str(item).strip())
    return normalized or default


def load_pi_paths(
    *,
    base_path: Path | None = None,
    local_path: Path | None = None,
) -> PiPaths:
    """Return PiPaths with base + local YAML overrides applied.

    Reads fresh on every call — CLI commands are short-lived processes.
    """
    base = base_path if base_path is not None else HOST.deploy_config
    local = local_path if local_path is not None else HOST.deploy_config_local

    merged: dict[str, object] = {}
    merged.update(_load_yaml(base))
    merged.update(_load_yaml(local))

    return replace(
        PI_DEFAULTS,
        project_dir=str(merged.get("project_dir", PI_DEFAULTS.project_dir)).strip() or PI_DEFAULTS.project_dir,
        venv=str(merged.get("venv", PI_DEFAULTS.venv)).strip() or PI_DEFAULTS.venv,
        start_cmd=str(merged.get("start_cmd", PI_DEFAULTS.start_cmd)).strip() or PI_DEFAULTS.start_cmd,
        log_file=str(merged.get("log_file", PI_DEFAULTS.log_file)).strip() or PI_DEFAULTS.log_file,
        error_log_file=str(merged.get("error_log_file", PI_DEFAULTS.error_log_file)).strip() or PI_DEFAULTS.error_log_file,
        pid_file=str(merged.get("pid_file", PI_DEFAULTS.pid_file)).strip() or PI_DEFAULTS.pid_file,
        screenshot_path=str(merged.get("screenshot_path", PI_DEFAULTS.screenshot_path)).strip() or PI_DEFAULTS.screenshot_path,
        test_music_target_dir=str(merged.get("test_music_target_dir", PI_DEFAULTS.test_music_target_dir)).strip() or PI_DEFAULTS.test_music_target_dir,
        startup_marker=str(merged.get("startup_marker", PI_DEFAULTS.startup_marker)).strip() or PI_DEFAULTS.startup_marker,
        kill_processes=_as_str_tuple(merged.get("kill_processes"), PI_DEFAULTS.kill_processes),
        rsync_exclude=_as_str_tuple(merged.get("rsync_exclude"), PI_DEFAULTS.rsync_exclude),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_yoyopod_cli_paths.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/paths.py tests/test_yoyopod_cli_paths.py
git commit -m "feat(cli): add yoyopod_cli/paths.py single source of truth"
```

---

## Task 3: Create `yoyopod_cli/remote_transport.py`

**Files:**
- Create: `yoyopod_cli/remote_transport.py`
- Test: `tests/test_yoyopod_cli_remote_transport.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_transport.py
"""Unit tests for SSH transport helpers."""
from __future__ import annotations

from yoyopod_cli.remote_transport import (
    build_ssh_command,
    quote_remote_project_dir,
    shell_quote,
)
from yoyopod_cli.remote_shared import RemoteConnection


def test_shell_quote_escapes() -> None:
    assert shell_quote("foo bar") == "'foo bar'"
    assert shell_quote("clean") == "clean"


def test_quote_remote_project_dir_tilde() -> None:
    assert quote_remote_project_dir("~") == '"$HOME"'
    assert quote_remote_project_dir("~/YoyoPod_Core") == '"$HOME/YoyoPod_Core"'


def test_quote_remote_project_dir_absolute() -> None:
    assert quote_remote_project_dir("/opt/yoyopod") == "/opt/yoyopod"


def test_build_ssh_command_without_tty() -> None:
    conn = RemoteConnection(host="rpi-zero", user="pi", project_dir="~/YoyoPod_Core", branch="main")
    parts = build_ssh_command(conn, "ls")
    assert parts[0] == "ssh"
    assert "-t" not in parts
    assert parts[1] == "pi@rpi-zero"
    assert "cd \"$HOME/YoyoPod_Core\" && ls" in parts[2]


def test_build_ssh_command_with_tty() -> None:
    conn = RemoteConnection(host="rpi-zero", user="", project_dir="~", branch="main")
    parts = build_ssh_command(conn, "htop", tty=True)
    assert parts[0] == "ssh"
    assert parts[1] == "-t"
    assert parts[2] == "rpi-zero"  # no user → host only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_transport.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.remote_transport'`

- [ ] **Step 3: Create `yoyopod_cli/remote_transport.py`**

```python
# yoyopod_cli/remote_transport.py
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
    """Quote the remote project path while preserving ``~`` expansion."""
    if project_dir == "~":
        return '"$HOME"'
    if project_dir.startswith("~/"):
        suffix = project_dir[2:].replace('"', '\\"')
        return f'"$HOME/{suffix}"'
    return shlex.quote(project_dir)


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


def run_remote(conn: RemoteConnection, remote_command: str, tty: bool = False) -> int:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_yoyopod_cli_remote_transport.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/remote_transport.py tests/test_yoyopod_cli_remote_transport.py
git commit -m "feat(cli): add yoyopod_cli/remote_transport.py SSH helpers"
```

---

## Task 4: Create `yoyopod_cli/remote_shared.py`

**Files:**
- Create: `yoyopod_cli/remote_shared.py`
- Test: `tests/test_yoyopod_cli_remote_shared.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_shared.py
"""Tests for the shared Pi-connection options callback."""
from __future__ import annotations

import typer
from typer.testing import CliRunner

from yoyopod_cli.remote_shared import (
    RemoteConnection,
    build_remote_app,
    pi_conn,
)


def test_remote_connection_ssh_target_with_user() -> None:
    conn = RemoteConnection(host="rpi-zero", user="pi", project_dir="~", branch="main")
    assert conn.ssh_target == "pi@rpi-zero"


def test_remote_connection_ssh_target_without_user() -> None:
    conn = RemoteConnection(host="rpi-zero", user="", project_dir="~", branch="main")
    assert conn.ssh_target == "rpi-zero"


def test_build_remote_app_captures_cli_flags() -> None:
    app = build_remote_app("ops", "Test ops group.")

    captured: dict[str, object] = {}

    @app.command()
    def echo(ctx: typer.Context) -> None:
        conn = pi_conn(ctx)
        captured["host"] = conn.host
        captured["user"] = conn.user
        captured["project_dir"] = conn.project_dir
        captured["branch"] = conn.branch

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--host",
            "rpi-zero",
            "--user",
            "pi",
            "--project-dir",
            "/opt/yoyopod",
            "--branch",
            "feature-x",
            "echo",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["host"] == "rpi-zero"
    assert captured["user"] == "pi"
    assert captured["project_dir"] == "/opt/yoyopod"
    assert captured["branch"] == "feature-x"


def test_build_remote_app_defaults_from_env(monkeypatch) -> None:
    monkeypatch.setenv("YOYOPOD_PI_HOST", "env-host")
    monkeypatch.setenv("YOYOPOD_PI_USER", "env-user")

    app = build_remote_app("ops", "Test ops group.")

    captured: dict[str, object] = {}

    @app.command()
    def echo(ctx: typer.Context) -> None:
        conn = pi_conn(ctx)
        captured["host"] = conn.host
        captured["user"] = conn.user

    runner = CliRunner()
    result = runner.invoke(app, ["echo"])
    assert result.exit_code == 0, result.output
    assert captured["host"] == "env-host"
    assert captured["user"] == "env-user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_shared.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.remote_shared'`

- [ ] **Step 3: Create `yoyopod_cli/remote_shared.py`**

```python
# yoyopod_cli/remote_shared.py
"""Shared Pi-connection state for remote CLI groups.

Every `yoyopod remote <group>` has a typer.callback() that captures the four
Pi-connection flags once. Individual command handlers pull the typed
`RemoteConnection` via `pi_conn(ctx)` — no duplication.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from yoyopod_cli.paths import HOST, load_pi_paths


@dataclass(frozen=True)
class RemoteConnection:
    """Connection details resolved from CLI flags + env vars + YAML defaults."""

    host: str
    user: str
    project_dir: str
    branch: str

    @property
    def ssh_target(self) -> str:
        """Return the SSH target as `user@host` or just `host`."""
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


def _resolve_remote_connection(
    host: str,
    user: str,
    project_dir: str,
    branch: str,
) -> RemoteConnection:
    """Merge CLI flags (highest) → env (already handled by Typer) → YAML defaults."""
    pi = load_pi_paths()
    # NB: host/user/branch defaults live in pi-deploy.yaml but are RemoteConnection concerns,
    # not PiPaths. Read them directly from the same YAML via load_pi_paths's upstream yaml load.
    import yaml

    defaults: dict[str, object] = {}
    for candidate in (HOST.deploy_config, HOST.deploy_config_local):
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            if isinstance(data, dict):
                defaults.update(data)

    return RemoteConnection(
        host=host or str(defaults.get("host", "")).strip(),
        user=user or str(defaults.get("user", "")).strip(),
        project_dir=(project_dir or str(defaults.get("project_dir", pi.project_dir)).strip()) or pi.project_dir,
        branch=(branch or str(defaults.get("branch", "main")).strip()) or "main",
    )


def build_remote_app(name: str, help: str) -> typer.Typer:
    """Build a Typer sub-app with the shared Pi-connection callback."""
    app = typer.Typer(name=name, help=help, no_args_is_help=True)

    @app.callback()
    def _capture_connection(
        ctx: typer.Context,
        host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST", help="SSH host or alias."),
        user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER", help="SSH user (optional)."),
        project_dir: str = typer.Option(
            "", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR", help="Project dir on the Pi."
        ),
        branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH", help="Git branch to target."),
    ) -> None:
        ctx.obj = _resolve_remote_connection(host, user, project_dir, branch)

    return app


def pi_conn(ctx: typer.Context) -> RemoteConnection:
    """Typed accessor for the shared Pi connection."""
    return ctx.ensure_object(RemoteConnection)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_yoyopod_cli_remote_shared.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/remote_shared.py tests/test_yoyopod_cli_remote_shared.py
git commit -m "feat(cli): add yoyopod_cli/remote_shared.py for unified Pi options"
```

---

## Task 5: Create `yoyopod_cli/main.py` and wire entry point

**Files:**
- Create: `yoyopod_cli/main.py`
- Modify: `pyproject.toml`
- Test: `tests/test_yoyopod_cli_main.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_main.py
"""Tests for the yoyopod entry point and bare-invocation behavior."""
from __future__ import annotations

import typer
from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_help_lists_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Subapps registered at this task are still empty placeholders —
    # after later tasks these will include real groups. For now just
    # verify `--help` emits without error.
    assert "yoyopod" in result.output.lower()


def test_version_flag_present() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.main'`

- [ ] **Step 3: Create `yoyopod_cli/main.py`**

```python
# yoyopod_cli/main.py
"""
yoyopod — app launcher and CLI dispatcher.

Usage:
    yoyopod                      # Launch the YoyoPod app
    yoyopod deploy               # Sync code to the Pi and restart
    yoyopod status               # Pi health dashboard
    yoyopod logs [-f --errors]   # Tail logs from the Pi
    yoyopod restart              # Restart the app on the Pi
    yoyopod validate             # Run the validation suite on the Pi
    yoyopod remote <cmd>         # Dev-machine → Pi commands
    yoyopod pi <cmd>             # On-device commands
    yoyopod build <cmd>          # Native extension builds
    yoyopod setup <cmd>          # Host and Pi setup
"""

from __future__ import annotations

import typer

from yoyopod_cli import __version__

app = typer.Typer(
    name="yoyopod",
    help="YoyoPod app launcher and CLI.",
    no_args_is_help=False,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"yoyopod {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Launch the YoyoPod app when invoked with no subcommand."""
    if ctx.invoked_subcommand is None:
        from yoyopod.main import main as launch_app

        launch_app()


def run() -> None:
    """Entry-point shim used by `[project.scripts]`."""
    app()
```

- [ ] **Step 4: Update `pyproject.toml` scripts section**

Edit `pyproject.toml` lines 50–53:

```toml
[project.scripts]
yoyopod = "yoyopod_cli.main:run"
```

Remove the `yoyopod = "yoyopod.cli:run"` line. Leave `yoyopod` pointing at the new CLI.

- [ ] **Step 5: Re-install the package so the new script is available**

Run: `uv sync --extra dev`

Expected: `yoyopod` is now reinstalled to point at `yoyopod_cli.main:run`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_main.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Sanity-check CLI**

Run: `uv run yoyopod --version`
Expected: `yoyopod 0.1.0`

Run: `uv run yoyopod --help`
Expected: Help text showing the root command (subapps still empty).

- [ ] **Step 8: Commit**

```bash
git add yoyopod_cli/main.py pyproject.toml tests/test_yoyopod_cli_main.py
git commit -m "feat(cli): add yoyopod_cli/main.py entry point and rewire yoyopod script"
```

---

## Task 6: Port `yoyopod_cli/build.py`

**Files:**
- Create: `yoyopod_cli/build.py`
- Modify: `yoyopod_cli/main.py` (register subapp)
- Test: `tests/test_yoyopod_cli_build.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_build.py
"""Tests for yoyopod_cli.build — native extension build commands."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.build import app


def test_lvgl_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lvgl", "--help"])
    assert result.exit_code == 0
    assert "lvgl" in result.output.lower()


def test_liblinphone_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["liblinphone", "--help"])
    assert result.exit_code == 0
    assert "liblinphone" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_build.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.build'`

- [ ] **Step 3: Copy current build logic to `yoyopod_cli/build.py`**

Copy file `src/yoyopod/cli/build.py` → `yoyopod_cli/build.py`, then apply these rewrites:

- Replace `_REPO_ROOT = Path(__file__).resolve().parents[3]` with `from yoyopod_cli.paths import HOST; _REPO_ROOT = HOST.repo_root`.
- Rename `build_app = typer.Typer(...)` to `app = typer.Typer(...)`.
- Update module docstring to reference the new path.

No other changes — build commands don't use the Pi-connection infrastructure.

- [ ] **Step 4: Register `build` subapp in `main.py`**

Edit `yoyopod_cli/main.py` to add after the `_root` callback:

```python
from yoyopod_cli import build as _build

app.add_typer(_build.app, name="build")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_build.py tests/test_yoyopod_cli_main.py -v`
Expected: PASS (4 passed)

Run: `uv run yoyopod build --help`
Expected: Lists `lvgl` and `liblinphone` subcommands.

- [ ] **Step 6: Commit**

```bash
git add yoyopod_cli/build.py yoyopod_cli/main.py tests/test_yoyopod_cli_build.py
git commit -m "feat(cli): port build commands to yoyopod_cli/build.py"
```

---

## Task 7: Port `yoyopod_cli/setup.py`

**Files:**
- Create: `yoyopod_cli/setup.py`
- Modify: `yoyopod_cli/main.py` (register subapp)
- Test: `tests/test_yoyopod_cli_setup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_setup.py
"""Tests for yoyopod_cli.setup — host + Pi setup commands."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.setup import app


def test_host_verify_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["verify-host", "--help"])
    assert result.exit_code == 0


def test_pi_verify_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["verify-pi", "--help"])
    assert result.exit_code == 0


def test_setup_lists_all_four_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "host" in result.output
    assert "pi" in result.output
    assert "verify-host" in result.output
    assert "verify-pi" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.setup'`

- [ ] **Step 3: Copy and rewrite setup logic**

Copy file `src/yoyopod/cli/setup.py` → `yoyopod_cli/setup.py`, then apply:

- Replace `from yoyopod.cli.common import REPO_ROOT` with `from yoyopod_cli.paths import HOST; REPO_ROOT = HOST.repo_root`.
- Rename `setup_app = typer.Typer(...)` to `app = typer.Typer(...)`.
- Update all internal references `setup_app` → `app`.
- Update module docstring to reference the new path.

Command-body logic stays identical; these are host-only subprocess runners that don't touch the Pi connection infrastructure.

- [ ] **Step 4: Register `setup` subapp in `main.py`**

Edit `yoyopod_cli/main.py` to add:

```python
from yoyopod_cli import setup as _setup

app.add_typer(_setup.app, name="setup")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_setup.py -v`
Expected: PASS (3 passed)

Run: `uv run yoyopod setup --help`
Expected: Lists `host`, `pi`, `verify-host`, `verify-pi`.

- [ ] **Step 6: Commit**

```bash
git add yoyopod_cli/setup.py yoyopod_cli/main.py tests/test_yoyopod_cli_setup.py
git commit -m "feat(cli): port setup commands to yoyopod_cli/setup.py"
```

---

## Task 8: Port `yoyopod_cli/remote_ops.py` (status, sync, restart, logs, screenshot)

This is the hot-path task — the first one that exercises the full shared-options + transport pattern. Every later remote port follows the same shape.

**Files:**
- Create: `yoyopod_cli/remote_ops.py`
- Test: `tests/test_yoyopod_cli_remote_ops.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_ops.py
"""Tests for yoyopod_cli.remote_ops — runtime ops over SSH."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_ops import app, _build_status, _build_restart, _build_logs_tail
from yoyopod_cli.paths import PiPaths


def test_build_status_includes_repo_sha_and_log_tail() -> None:
    pi = PiPaths()
    shell = _build_status(pi)
    assert "git rev-parse HEAD" in shell
    assert pi.log_file in shell
    assert pi.pid_file in shell


def test_build_restart_uses_configured_processes() -> None:
    pi = PiPaths(kill_processes=("python", "linphonec"))
    shell = _build_restart(pi)
    assert "python" in shell
    assert "linphonec" in shell
    assert "pkill" in shell


def test_build_logs_tail_defaults() -> None:
    pi = PiPaths()
    shell = _build_logs_tail(pi, lines=50, follow=False, errors=False, filter_pattern="")
    assert "tail -n 50" in shell
    assert pi.log_file in shell
    assert "-f" not in shell


def test_build_logs_tail_follow_errors_filter() -> None:
    pi = PiPaths()
    shell = _build_logs_tail(pi, lines=20, follow=True, errors=True, filter_pattern="ERROR")
    assert "tail -n 20 -f" in shell
    assert pi.error_log_file in shell
    assert "grep 'ERROR'" in shell


def test_status_cli_invokes_run_remote(monkeypatch) -> None:
    calls: list[tuple[object, str]] = []

    def fake_run_remote(conn, cmd, tty=False):
        calls.append((conn, cmd))
        return 0

    monkeypatch.setattr("yoyopod_cli.remote_ops.run_remote", fake_run_remote)
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    conn, cmd = calls[0]
    assert conn.host == "rpi-zero"
    assert "git rev-parse HEAD" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_ops.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.remote_ops'`

- [ ] **Step 3: Create `yoyopod_cli/remote_ops.py`**

```python
# yoyopod_cli/remote_ops.py
"""Runtime ops on the Pi via SSH — status, sync, restart, logs, screenshot."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import HOST, PROCS, PiPaths, load_pi_paths
from yoyopod_cli.remote_shared import RemoteConnection, build_remote_app, pi_conn
from yoyopod_cli.remote_transport import (
    quote_remote_project_dir,
    run_remote,
    run_remote_capture,
    shell_quote,
    validate_config,
)

app = build_remote_app("ops", "Runtime ops on the Pi via SSH.")


# ---- shell builders (private, single-file) ----------------------------------

def _build_status(pi: PiPaths) -> str:
    """Build the shell that prints repo SHA, process list, and log tail."""
    log = shell_quote(pi.log_file)
    pid = shell_quote(pi.pid_file)
    return (
        f"echo '=== git ===' && git rev-parse HEAD && "
        f"echo '=== processes ===' && (ps aux | grep -E 'python|mpv|linphonec' | grep -v grep || true) && "
        f"echo '=== pid ===' && (cat {pid} 2>/dev/null || echo 'no pid file') && "
        f"echo '=== log tail ===' && (tail -n 20 {log} 2>/dev/null || echo 'no log file')"
    )


def _build_restart(pi: PiPaths) -> str:
    """Build the shell that kills the app processes; systemd restarts them."""
    kills = " ; ".join(f"pkill -f {shell_quote(proc)} || true" for proc in pi.kill_processes)
    return f"{kills} ; echo 'processes signalled — systemd will respawn'"


def _build_logs_tail(pi: PiPaths, *, lines: int, follow: bool, errors: bool, filter_pattern: str) -> str:
    """Build the log-tail shell with optional follow/errors/filter."""
    log = pi.error_log_file if errors else pi.log_file
    cmd = f"tail -n {lines}{' -f' if follow else ''} {shell_quote(log)}"
    if filter_pattern:
        cmd += f" | grep {shell_quote(filter_pattern)}"
    return cmd


def _build_sync(pi: PiPaths, branch: str) -> str:
    """Build the shell that fast-forwards the branch and restarts via kill."""
    return (
        f"git fetch origin && "
        f"git checkout {shell_quote(branch)} && "
        f"git reset --hard origin/{shell_quote(branch)} && "
        f"{_build_restart(pi)}"
    )


# ---- commands ---------------------------------------------------------------

@app.command()
def status(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Show repo SHA, processes, and log tail on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_status(pi)))


@app.command()
def restart(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Restart the yoyopod app on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_restart(pi)))


@app.command()
def logs(
    ctx: typer.Context,
    lines: int = typer.Option(50, "--lines", help="Number of lines to tail."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output."),
    errors: bool = typer.Option(False, "--errors", help="Tail the error log."),
    filter: str = typer.Option("", "--filter", help="Grep filter applied to the output."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Tail yoyopod logs on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    cmd = _build_logs_tail(pi, lines=lines, follow=follow, errors=errors, filter_pattern=filter)
    raise typer.Exit(run_remote(conn, cmd, tty=follow))


@app.command()
def sync(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Fetch + hard-reset branch on the Pi and restart the app (fast deploy)."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()
    raise typer.Exit(run_remote(conn, _build_sync(pi, conn.branch)))


@app.command()
def screenshot(
    ctx: typer.Context,
    out: str = typer.Option("", "--out", help="Local file path. Default: logs/screenshots/<timestamp>.png"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Capture the display shadow buffer from the Pi and copy it locally."""
    from datetime import datetime

    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    pi = load_pi_paths()

    remote_png = pi.screenshot_path
    cmd = (
        f"python -c 'from yoyopod.ui.display.factory import capture_shadow_png; "
        f"capture_shadow_png({shell_quote(remote_png)})'"
    )
    rc = run_remote(conn, cmd)
    if rc != 0:
        raise typer.Exit(rc)

    local_target = Path(out) if out else HOST.repo_root / "logs" / "screenshots" / f"{datetime.now():%Y%m%d-%H%M%S}.png"
    local_target.parent.mkdir(parents=True, exist_ok=True)

    scp_cmd = ["scp", f"{conn.ssh_target}:{remote_png}", str(local_target)]
    completed = subprocess.run(scp_cmd, check=False)
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)
    typer.echo(f"screenshot saved to {local_target}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_remote_ops.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/remote_ops.py tests/test_yoyopod_cli_remote_ops.py
git commit -m "feat(cli): port remote ops (status/sync/restart/logs/screenshot)"
```

---

## Task 9: Port `yoyopod_cli/remote_config.py`

**Files:**
- Create: `yoyopod_cli/remote_config.py`
- Test: `tests/test_yoyopod_cli_remote_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_config.py
"""Tests for yoyopod_cli.remote_config — show/edit pi-deploy.local.yaml."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_config import app


def test_show_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["show", "--help"])
    assert result.exit_code == 0


def test_edit_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["edit", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.remote_config'`

- [ ] **Step 3: Copy and rewrite**

Port `src/yoyopod/cli/remote/config.py`'s `config` command (and its helpers `show`/`edit`) into a new `yoyopod_cli/remote_config.py`. Apply these rewrites:

- Use `app = typer.Typer(name="config", ...)` — config doesn't need the shared Pi callback; it manipulates local files only.
- Replace imports from `yoyopod.cli.*` with `yoyopod_cli.*`.
- Use `HOST.deploy_config` / `HOST.deploy_config_local` from `yoyopod_cli.paths` instead of the old constants.

```python
# yoyopod_cli/remote_config.py
"""Show or edit deploy/pi-deploy.local.yaml (the per-host override file)."""

from __future__ import annotations

import os
import subprocess

import typer

from yoyopod_cli.paths import HOST

app = typer.Typer(name="config", help="Show or edit pi-deploy.local.yaml.", no_args_is_help=True)


@app.command()
def show() -> None:
    """Print the effective pi-deploy YAML (base merged with local override)."""
    import yaml

    from yoyopod_cli.paths import load_pi_paths
    from yoyopod_cli.remote_shared import _resolve_remote_connection

    conn = _resolve_remote_connection("", "", "", "")
    pi = load_pi_paths()

    effective = {
        "host": conn.host,
        "user": conn.user,
        "project_dir": conn.project_dir,
        "branch": conn.branch,
        "venv": pi.venv,
        "start_cmd": pi.start_cmd,
        "log_file": pi.log_file,
        "error_log_file": pi.error_log_file,
        "pid_file": pi.pid_file,
        "screenshot_path": pi.screenshot_path,
        "startup_marker": pi.startup_marker,
        "kill_processes": list(pi.kill_processes),
        "rsync_exclude": list(pi.rsync_exclude),
    }
    typer.echo(yaml.safe_dump(effective, sort_keys=False))


@app.command()
def edit() -> None:
    """Open deploy/pi-deploy.local.yaml in $EDITOR."""
    path = HOST.deploy_config_local
    if not path.exists():
        path.write_text(
            "# Host-specific overrides for deploy/pi-deploy.yaml\n"
            "# host: rpi-zero\n"
            "# user: pi\n"
            "# project_dir: ~/YoyoPod_Core\n"
        )
    editor = os.environ.get("EDITOR", "nano")
    subprocess.run([editor, str(path)], check=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_remote_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/remote_config.py tests/test_yoyopod_cli_remote_config.py
git commit -m "feat(cli): port remote config show/edit"
```

---

## Task 10: Port `yoyopod_cli/remote_infra.py` (power, rtc, service)

**Files:**
- Create: `yoyopod_cli/remote_infra.py`
- Test: `tests/test_yoyopod_cli_remote_infra.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_infra.py
"""Tests for yoyopod_cli.remote_infra — power, rtc, service."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_infra import app, _build_power, _build_rtc, _build_service_install
from yoyopod_cli.paths import HOST


def test_build_power_calls_battery() -> None:
    shell = _build_power()
    assert "yoyopod pi power battery" in shell or "yoyopod" not in shell


def test_build_rtc_with_status() -> None:
    shell = _build_rtc("status", time_iso="", repeat_mask=127)
    assert "yoyopod pi power rtc status" in shell


def test_build_rtc_with_set_alarm_time() -> None:
    shell = _build_rtc("set-alarm", time_iso="2026-04-20T07:00:00", repeat_mask=127)
    assert "set-alarm" in shell
    assert "2026-04-20T07:00:00" in shell
    assert "127" in shell


def test_build_service_install_uses_template_path() -> None:
    shell = _build_service_install()
    assert str(HOST.systemd_unit_template.name) in shell or "yoyopod@.service" in shell


def test_power_cli_invokes_run_remote(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("yoyopod_cli.remote_infra.run_remote", lambda conn, cmd, tty=False: (calls.append((conn, cmd)), 0)[1])
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["power"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_infra.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.remote_infra'`

- [ ] **Step 3: Create `yoyopod_cli/remote_infra.py`**

Port `src/yoyopod/cli/remote/infra.py` (294 lines), applying the standard rewrites:
- `build_remote_app("infra", ...)` — but since `power`, `rtc`, and `service` become peer commands under `remote` not `remote infra`, register each directly on `remote_app` (done in Task 14).
- Kill `argparse.Namespace`; use typed Typer params.
- Extract shell builders as `_build_*` private helpers.

```python
# yoyopod_cli/remote_infra.py
"""Remote infra commands: power snapshot, rtc, systemd service management."""

from __future__ import annotations

import shlex

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.paths import HOST
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import run_remote, shell_quote, validate_config

app = build_remote_app("infra", "Remote power, rtc, and service commands.")


def _build_power() -> str:
    """Invoke `yoyopod pi power battery` on the Pi."""
    return "yoyopod pi power battery"


def _build_rtc(action: str, *, time_iso: str, repeat_mask: int) -> str:
    """Build `yoyopod pi power rtc <action> …` on the Pi."""
    cmd = f"yoyopod pi power rtc {shell_quote(action)}"
    if action == "set-alarm":
        if not time_iso:
            raise typer.BadParameter("set-alarm requires --time")
        cmd += f" --time {shell_quote(time_iso)} --repeat-mask {repeat_mask}"
    return cmd


def _build_service_install() -> str:
    """Build the shell that installs the systemd unit."""
    return (
        f"sudo cp {shell_quote(str(HOST.systemd_unit_template))} /etc/systemd/system/ && "
        "sudo systemctl daemon-reload && "
        "sudo systemctl enable --now yoyopod@$USER"
    )


def _build_service_action(action: str) -> str:
    """Build `sudo systemctl <action> yoyopod@<user>` where $USER is resolved remotely."""
    return f"sudo systemctl {shell_quote(action)} yoyopod@$USER"


@app.command()
def power(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Query PiSugar state remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_power()))


@app.command()
def rtc(
    ctx: typer.Context,
    action: str = typer.Argument("status", help="status | sync-to | sync-from | set-alarm | disable-alarm"),
    time: str = typer.Option("", "--time", help="ISO 8601 timestamp for set-alarm."),
    repeat_mask: int = typer.Option(127, "--repeat-mask", help="Repeat-bitmask (default every day)."),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Inspect or control PiSugar RTC remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_rtc(action, time_iso=time, repeat_mask=repeat_mask)))


@app.command()
def service(
    ctx: typer.Context,
    action: str = typer.Argument(..., help="install | uninstall | status | start | stop"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Manage the yoyopod@<user> systemd unit on the Pi."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    if action == "install":
        cmd = _build_service_install()
    elif action == "uninstall":
        cmd = "sudo systemctl disable --now yoyopod@$USER && sudo rm -f /etc/systemd/system/yoyopod@.service && sudo systemctl daemon-reload"
    elif action in ("status", "start", "stop"):
        cmd = _build_service_action(action)
    else:
        raise typer.BadParameter(f"unknown action: {action}")
    raise typer.Exit(run_remote(conn, cmd))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_remote_infra.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/remote_infra.py tests/test_yoyopod_cli_remote_infra.py
git commit -m "feat(cli): port remote infra (power/rtc/service)"
```

---

## Task 11: Port `yoyopod_cli/remote_setup.py`

**Files:**
- Create: `yoyopod_cli/remote_setup.py`
- Test: `tests/test_yoyopod_cli_remote_setup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_setup.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_setup import app, _build_setup, _build_verify_setup


def test_build_setup_calls_pi_setup() -> None:
    shell = _build_setup()
    assert "yoyopod setup pi" in shell


def test_build_verify_setup_calls_pi_verify() -> None:
    shell = _build_verify_setup()
    assert "yoyopod setup verify-pi" in shell


def test_setup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yoyopod_cli.remote_setup'`

- [ ] **Step 3: Create `yoyopod_cli/remote_setup.py`**

Port `src/yoyopod/cli/remote/setup.py` (147 lines):

```python
# yoyopod_cli/remote_setup.py
"""Run Pi setup + verification remotely via SSH."""

from __future__ import annotations

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import run_remote, validate_config

app = build_remote_app("setup_remote", "Run setup on the Pi via SSH.")


def _build_setup() -> str:
    return "yoyopod setup pi"


def _build_verify_setup() -> str:
    return "yoyopod setup verify-pi"


@app.command()
def setup(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Run full Pi setup remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_setup(), tty=True))


@app.command(name="verify-setup")
def verify_setup(ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Verify Pi setup remotely."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    raise typer.Exit(run_remote(conn, _build_verify_setup()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_remote_setup.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/remote_setup.py tests/test_yoyopod_cli_remote_setup.py
git commit -m "feat(cli): port remote setup/verify-setup"
```

---

## Task 12: Port `yoyopod_cli/remote_validate.py` (folds lvgl-soak + navigation-soak as flags)

**Files:**
- Create: `yoyopod_cli/remote_validate.py`
- Test: `tests/test_yoyopod_cli_remote_validate.py`

The new `remote validate` absorbs two previously-separate commands: `remote lvgl-soak` becomes `remote validate --with-lvgl-soak`, and `remote navigation-soak` becomes `remote validate --with-navigation`. It also absorbs `remote preflight` and `remote sync` fast-path sanity checks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_validate.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_validate import (
    app,
    _build_validate,
    _build_preflight,
)


def test_build_preflight_checks_git_and_lint() -> None:
    shell = _build_preflight()
    assert "git diff" in shell or "git status" in shell
    assert "uv run" in shell or "scripts/quality.py" in shell


def test_build_validate_minimal() -> None:
    shell = _build_validate(with_music=False, with_voip=False, with_lvgl_soak=False, with_navigation=False)
    assert "yoyopod pi validate deploy" in shell
    assert "yoyopod pi validate smoke" in shell
    assert "voip" not in shell
    assert "lvgl" not in shell


def test_build_validate_all_flags() -> None:
    shell = _build_validate(with_music=True, with_voip=True, with_lvgl_soak=True, with_navigation=True)
    assert "yoyopod pi validate music" in shell
    assert "yoyopod pi validate voip" in shell
    assert "yoyopod pi validate lvgl" in shell
    assert "yoyopod pi validate navigation" in shell


def test_preflight_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["preflight", "--help"])
    assert result.exit_code == 0


def test_validate_help_shows_flags() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0
    assert "--with-music" in result.output
    assert "--with-voip" in result.output
    assert "--with-lvgl-soak" in result.output
    assert "--with-navigation" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_validate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `yoyopod_cli/remote_validate.py`**

```python
# yoyopod_cli/remote_validate.py
"""Remote validate + preflight — run Pi validation stages over SSH.

Absorbs previous `remote lvgl-soak` as `--with-lvgl-soak`,
previous `remote navigation-soak` as `--with-navigation`.
"""

from __future__ import annotations

import typer

from yoyopod_cli.common import configure_logging
from yoyopod_cli.remote_shared import build_remote_app, pi_conn
from yoyopod_cli.remote_transport import (
    run_local,
    run_remote,
    validate_config,
)

app = build_remote_app("validate_app", "Validate commit + health on the Pi.")


def _build_preflight() -> str:
    """Local shell that fails fast on dirty tree + bad quality gate before any SSH work."""
    return (
        "git diff --quiet && git diff --cached --quiet && "
        "uv run python scripts/quality.py ci"
    )


def _build_validate(
    *,
    with_music: bool,
    with_voip: bool,
    with_lvgl_soak: bool,
    with_navigation: bool,
) -> str:
    """Shell that runs staged validation on the Pi."""
    steps = [
        "yoyopod pi validate deploy",
        "yoyopod pi validate smoke",
        "yoyopod pi validate stability",
    ]
    if with_music:
        steps.insert(2, "yoyopod pi validate music")
    if with_voip:
        steps.insert(-1, "yoyopod pi validate voip")
    if with_lvgl_soak:
        steps.append("yoyopod pi validate lvgl")
    if with_navigation:
        steps.append("yoyopod pi validate navigation")
    return " && ".join(steps)


@app.command()
def preflight(verbose: bool = typer.Option(False, "--verbose")) -> None:
    """Run host-side preflight checks (dirty tree + quality gate) before any remote work."""
    configure_logging(verbose)
    import shlex

    raise typer.Exit(run_local(shlex.split(_build_preflight()), "preflight"))


@app.command()
def validate(
    ctx: typer.Context,
    with_music: bool = typer.Option(False, "--with-music"),
    with_voip: bool = typer.Option(False, "--with-voip"),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak"),
    with_navigation: bool = typer.Option(False, "--with-navigation"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run staged Pi validation. Pass --with-* to add optional stages."""
    configure_logging(verbose)
    conn = pi_conn(ctx)
    validate_config(conn)
    cmd = _build_validate(
        with_music=with_music,
        with_voip=with_voip,
        with_lvgl_soak=with_lvgl_soak,
        with_navigation=with_navigation,
    )
    raise typer.Exit(run_remote(conn, cmd, tty=True))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_remote_validate.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/remote_validate.py tests/test_yoyopod_cli_remote_validate.py
git commit -m "feat(cli): port remote validate with --with-lvgl-soak/--with-navigation flags"
```

---

## Task 13: Wire the `remote` subapp in `main.py`

**Files:**
- Modify: `yoyopod_cli/main.py`
- Test: `tests/test_yoyopod_cli_remote_tree.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_remote_tree.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_remote_lists_all_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["remote", "--help"])
    assert result.exit_code == 0
    for cmd in ("status", "sync", "restart", "logs", "screenshot",
                "config", "power", "rtc", "service",
                "setup", "verify-setup", "preflight", "validate"):
        assert cmd in result.output, f"missing: {cmd}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_remote_tree.py -v`
Expected: FAIL — `remote` subapp not yet wired.

- [ ] **Step 3: Update `main.py` to register the `remote` subapp**

Edit `yoyopod_cli/main.py` to add between the `_root` callback and the `run()` definition:

```python
from yoyopod_cli import (
    build as _build,
    remote_config as _remote_config,
    remote_infra as _remote_infra,
    remote_ops as _remote_ops,
    remote_setup as _remote_setup,
    remote_validate as _remote_validate,
    setup as _setup,
)
from yoyopod_cli.remote_shared import build_remote_app

# --- remote group assembled from flat sub-modules
remote_app = build_remote_app("remote", "Dev-machine → Pi commands via SSH.")

# register ops commands directly as `remote status`, `remote sync`, etc.
for command_name in ("status", "sync", "restart", "logs", "screenshot"):
    handler = getattr(_remote_ops.app, "registered_commands", None)
    # Typer doesn't expose commands cleanly for re-registration; so we directly register:
remote_app.command(name="status")(_remote_ops.status)
remote_app.command(name="sync")(_remote_ops.sync)
remote_app.command(name="restart")(_remote_ops.restart)
remote_app.command(name="logs")(_remote_ops.logs)
remote_app.command(name="screenshot")(_remote_ops.screenshot)

remote_app.command(name="preflight")(_remote_validate.preflight)
remote_app.command(name="validate")(_remote_validate.validate)

remote_app.command(name="power")(_remote_infra.power)
remote_app.command(name="rtc")(_remote_infra.rtc)
remote_app.command(name="service")(_remote_infra.service)

remote_app.add_typer(_remote_config.app, name="config")

remote_app.command(name="setup")(_remote_setup.setup)
remote_app.command(name="verify-setup")(_remote_setup.verify_setup)

app.add_typer(remote_app, name="remote")
app.add_typer(_build.app, name="build")
app.add_typer(_setup.app, name="setup")
```

(Adjust the earlier two `app.add_typer` statements from Tasks 6 and 7 to match this single block.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_remote_tree.py -v`
Expected: PASS (1 passed)

Run: `uv run yoyopod remote --help`
Expected: Full list of remote commands.

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/main.py tests/test_yoyopod_cli_remote_tree.py
git commit -m "feat(cli): wire remote subapp in main.py"
```

---

## Task 14: Port `yoyopod_cli/pi_voip.py` (check, debug — soaks cut)

**Files:**
- Create: `yoyopod_cli/pi_voip.py`
- Test: `tests/test_yoyopod_cli_pi_voip.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_pi_voip.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi_voip import app


def test_check_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["check", "--help"])
    assert result.exit_code == 0
    assert "registration" in result.output.lower()


def test_debug_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["debug", "--help"])
    assert result.exit_code == 0


def test_soak_commands_removed() -> None:
    runner = CliRunner()
    for cmd in ("registration-stability", "reconnect-drill", "call-soak"):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code != 0, f"{cmd} should have been removed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_pi_voip.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `yoyopod_cli/pi_voip.py`**

Port only `check` (line 483) and `debug` (line 537) from `src/yoyopod/cli/pi/voip.py`. The three soak commands (`registration-stability`, `reconnect-drill`, `call-soak`) do **not** come across — they're absorbed into `pi_validate.py --soak` in Task 17.

Also port the shared helper functions: `_build_voip_manager`, `_wait_for_registration_ok`, `_print_result`, `_VoIPDrillRecorder`. These go into `pi_voip.py` only if `check`/`debug` use them; otherwise they move to `pi_validate.py` with the soak logic in Task 17. Check each:

- `check` uses `_build_voip_manager`, `_wait_for_registration_ok`, `_print_result` — keep those in `pi_voip.py`.
- `debug` uses `_build_voip_manager` — shared.
- The soak-specific helpers (`_VoIPDrillRecorder`, `_hold_registration_ok`, `_wait_for_call_state`) move to `pi_validate.py` in Task 17.

Apply the standard rewrites:
- `from yoyopod.cli.common import configure_logging, resolve_config_dir` → `from yoyopod_cli.common import configure_logging, resolve_config_dir`
- `voip_app = typer.Typer(...)` → `app = typer.Typer(name="voip", ...)`
- All `@voip_app.command()` → `@app.command()`

```python
# yoyopod_cli/pi_voip.py
"""On-device VoIP diagnostics — check registration, debug incoming calls."""

from __future__ import annotations

from typing import Annotated

import typer

from yoyopod_cli.common import configure_logging, resolve_config_dir

app = typer.Typer(name="voip", help="On-device VoIP diagnostics.", no_args_is_help=True)


# ... copy _build_voip_manager, _wait_for_registration_ok, _print_result helpers from
#     src/yoyopod/cli/pi/voip.py, with imports adjusted.


@app.command()
def check(
    config_dir: Annotated[str, typer.Option("--config-dir")] = "config",
    registration_timeout: Annotated[float, typer.Option("--registration-timeout")] = 30.0,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """One-shot SIP registration check."""
    # ... copied body from src/yoyopod/cli/pi/voip.py:483-536 ...


@app.command()
def debug(
    config_dir: Annotated[str, typer.Option("--config-dir")] = "config",
    duration_seconds: Annotated[float, typer.Option("--duration-seconds")] = 60.0,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """Live incoming-call debug — log every SIP event for N seconds."""
    # ... copied body from src/yoyopod/cli/pi/voip.py:537-586 ...
```

Detailed transcription: open `src/yoyopod/cli/pi/voip.py`, copy lines 1–50 (imports + helpers used by check/debug), then lines 483–586 (the two commands). Rewrite imports as above. Do **not** copy lines 588–1066 (soak commands + their helpers).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_pi_voip.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/pi_voip.py tests/test_yoyopod_cli_pi_voip.py
git commit -m "feat(cli): port pi voip check/debug (soaks deferred to pi_validate)"
```

---

## Task 15: Port `yoyopod_cli/pi_power.py`

**Files:**
- Create: `yoyopod_cli/pi_power.py`
- Test: `tests/test_yoyopod_cli_pi_power.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_pi_power.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi_power import app


def test_battery_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["battery", "--help"])
    assert result.exit_code == 0


def test_rtc_status_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rtc", "status", "--help"])
    assert result.exit_code == 0


def test_rtc_all_subcommands() -> None:
    runner = CliRunner()
    for sub in ("status", "sync-to", "sync-from", "set-alarm", "disable-alarm"):
        result = runner.invoke(app, ["rtc", sub, "--help"])
        assert result.exit_code == 0, f"rtc {sub} help failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_pi_power.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `yoyopod_cli/pi_power.py`**

Copy `src/yoyopod/cli/pi/power.py` (198 lines) → `yoyopod_cli/pi_power.py`. Apply rewrites:

- `from yoyopod.cli.common ...` → `from yoyopod_cli.common ...`
- `power_app = typer.Typer(...)` → `app = typer.Typer(name="power", ...)`
- `rtc_app` stays as-is; registered on `app` (the new name for `power_app`):
  ```python
  app.add_typer(rtc_app)
  ```
- All `@power_app.command()` decorators → `@app.command()`
- `@rtc_app.command()` decorators unchanged.

Command body logic is identical (it reads app config and talks to the PowerManager directly — no CLI infra dependency changes).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_pi_power.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/pi_power.py tests/test_yoyopod_cli_pi_power.py
git commit -m "feat(cli): port pi power (battery + rtc subgroup)"
```

---

## Task 16: Port `yoyopod_cli/pi_network.py`

**Files:**
- Create: `yoyopod_cli/pi_network.py`
- Test: `tests/test_yoyopod_cli_pi_network.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_pi_network.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi_network import app


def test_probe_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["probe", "--help"])
    assert result.exit_code == 0


def test_status_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0


def test_gps_command_removed() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["gps", "--help"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_pi_network.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `yoyopod_cli/pi_network.py`**

Copy `src/yoyopod/cli/pi/network.py` (155 lines) → `yoyopod_cli/pi_network.py`. Keep `probe` (line 16) and `status` (line 61). **Do NOT copy** `gps` (line 111).

Apply rewrites:
- `from yoyopod.cli.common ...` → `from yoyopod_cli.common ...`
- `network_app = typer.Typer(...)` → `app = typer.Typer(name="network", ...)`
- All `@network_app.command()` → `@app.command()`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_pi_network.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/pi_network.py tests/test_yoyopod_cli_pi_network.py
git commit -m "feat(cli): port pi network (probe + status; gps cut)"
```

---

## Task 17: Port `yoyopod_cli/pi_validate.py` (with folded `voip --soak` and new `lvgl`)

This is the biggest task. It:
- Ports existing `pi validate` subcommands: `deploy`, `smoke`, `music`, `voip`, `stability`, `navigation`
- Adds new `lvgl` subcommand (absorbing logic from `src/yoyopod/cli/pi/lvgl.py` + `src/yoyopod/cli/pi/stability.py`'s lvgl parts)
- Adds `--soak {registration,reconnect,call}` flag to `voip` subcommand, absorbing the three cut VoIP soak commands' logic from `src/yoyopod/cli/pi/voip.py` lines 588–1066

**Files:**
- Create: `yoyopod_cli/pi_validate.py`
- Test: `tests/test_yoyopod_cli_pi_validate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_pi_validate.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.pi_validate import app


def test_all_subcommands_present() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("deploy", "smoke", "music", "voip", "stability", "navigation", "lvgl"):
        assert cmd in result.output, f"missing validate subcommand: {cmd}"


def test_voip_soak_flag_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["voip", "--help"])
    assert result.exit_code == 0
    assert "--soak" in result.output
    assert "registration" in result.output
    assert "reconnect" in result.output
    assert "call" in result.output


def test_lvgl_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lvgl", "--help"])
    assert result.exit_code == 0


def test_deploy_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["deploy", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_pi_validate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `yoyopod_cli/pi_validate.py`**

Open `src/yoyopod/cli/pi/validate.py` (469 lines) and copy the whole file into `yoyopod_cli/pi_validate.py`. Apply rewrites:

- `from yoyopod.cli.common ...` → `from yoyopod_cli.common ...`
- `from yoyopod.cli.pi.smoke import ...` → inline or copy into this file (cut `pi smoke` in §4 of the spec).
- `from yoyopod.cli.pi.stability import run_navigation_idle_soak` → keep behavior; copy `run_navigation_idle_soak` and its helpers from `src/yoyopod/cli/pi/stability.py` into `pi_validate.py` as private functions.
- `validate_app = typer.Typer(...)` → `app = typer.Typer(name="validate", ...)`
- All `@validate_app.command()` → `@app.command()`

Add the `voip --soak` flag: the existing `voip` command currently runs a check-and-exit; extend its signature with `soak: str = typer.Option("", "--soak", help="registration | reconnect | call")`. When `--soak` is set, route to the soak logic:

```python
@app.command()
def voip(
    config_dir: Annotated[str, typer.Option("--config-dir")] = "config",
    registration_timeout: Annotated[float, typer.Option("--registration-timeout")] = 30.0,
    soak: Annotated[str, typer.Option("--soak", help="Optional soak mode: registration | reconnect | call")] = "",
    # soak-specific options below
    hold_seconds: Annotated[float, typer.Option("--hold-seconds")] = 60.0,
    disconnect_seconds: Annotated[float, typer.Option("--disconnect-seconds")] = 8.0,
    drop_detect_timeout: Annotated[float, typer.Option("--drop-detect-timeout")] = 20.0,
    recovery_timeout: Annotated[float, typer.Option("--recovery-timeout")] = 45.0,
    drop_command: Annotated[str, typer.Option("--drop-command")] = "",
    restore_command: Annotated[str, typer.Option("--restore-command")] = "",
    soak_target: Annotated[str, typer.Option("--soak-target")] = "",
    soak_contact_name: Annotated[str, typer.Option("--soak-contact-name")] = "",
    soak_seconds: Annotated[float, typer.Option("--soak-seconds")] = 300.0,
    connect_timeout: Annotated[float, typer.Option("--connect-timeout")] = 60.0,
    hangup_timeout: Annotated[float, typer.Option("--hangup-timeout")] = 15.0,
    artifacts_dir: Annotated[str, typer.Option("--artifacts-dir")] = "logs/voip-validation",
    sample_interval: Annotated[float, typer.Option("--sample-interval")] = 1.0,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """VoIP validation: quick check (default) or soak drill (--soak)."""
    configure_logging(verbose)
    if not soak:
        return _run_quick_voip_check(config_dir, registration_timeout)
    if soak == "registration":
        return _run_voip_registration_stability(config_dir, registration_timeout, hold_seconds, artifacts_dir, sample_interval)
    if soak == "reconnect":
        return _run_voip_reconnect_drill(
            config_dir, registration_timeout, disconnect_seconds, drop_detect_timeout,
            recovery_timeout, drop_command, restore_command, artifacts_dir, sample_interval,
        )
    if soak == "call":
        if not soak_target:
            raise typer.BadParameter("--soak call requires --soak-target")
        return _run_voip_call_soak(
            config_dir, soak_target, soak_contact_name, registration_timeout,
            connect_timeout, soak_seconds, hangup_timeout, artifacts_dir, sample_interval,
        )
    raise typer.BadParameter(f"unknown --soak value: {soak}")
```

Then copy the three soak-implementation functions from `src/yoyopod/cli/pi/voip.py` (lines 588–1066) as private `_run_voip_registration_stability`, `_run_voip_reconnect_drill`, `_run_voip_call_soak` in `pi_validate.py`. Also copy the helper classes `_VoIPDrillRecorder`, `_wait_for_call_state`, `_hold_registration_ok`, etc. from that file.

Add the `lvgl` subcommand — absorb from `src/yoyopod/cli/pi/lvgl.py` `soak` command (line 17):

```python
@app.command()
def lvgl(
    config_dir: Annotated[str, typer.Option("--config-dir")] = "config",
    duration_seconds: Annotated[float, typer.Option("--duration-seconds")] = 60.0,
    cycles: Annotated[int, typer.Option("--cycles")] = 1,
    verbose: Annotated[bool, typer.Option("--verbose")] = False,
) -> None:
    """LVGL render-path soak validation on the Pi."""
    configure_logging(verbose)
    # Copy body from src/yoyopod/cli/pi/lvgl.py:17-75 (the `soak` command)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_pi_validate.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run full quality gate to catch import issues**

Run: `uv run python scripts/quality.py ci`
Expected: PASS (may fail on new-file format/lint — fix inline).

- [ ] **Step 6: Commit**

```bash
git add yoyopod_cli/pi_validate.py tests/test_yoyopod_cli_pi_validate.py
git commit -m "feat(cli): port pi validate with folded voip --soak and lvgl subcommand"
```

---

## Task 18: Wire the `pi` subapp in `main.py`

**Files:**
- Modify: `yoyopod_cli/main.py`
- Test: `tests/test_yoyopod_cli_pi_tree.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_pi_tree.py
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_pi_lists_all_groups() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["pi", "--help"])
    assert result.exit_code == 0
    for group in ("validate", "voip", "power", "network"):
        assert group in result.output


def test_pi_validate_lvgl_reachable() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["pi", "validate", "lvgl", "--help"])
    assert result.exit_code == 0


def test_pi_power_rtc_reachable() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["pi", "power", "rtc", "status", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_pi_tree.py -v`
Expected: FAIL — `pi` subapp not wired.

- [ ] **Step 3: Update `main.py` to add the `pi` subapp**

Append to `yoyopod_cli/main.py` before `app.add_typer(remote_app, ...)`:

```python
from yoyopod_cli import pi_network as _pi_network
from yoyopod_cli import pi_power as _pi_power
from yoyopod_cli import pi_validate as _pi_validate
from yoyopod_cli import pi_voip as _pi_voip
import typer as _typer

pi_app = _typer.Typer(name="pi", help="Commands that run on the Pi.", no_args_is_help=True)
pi_app.add_typer(_pi_validate.app, name="validate")
pi_app.add_typer(_pi_voip.app, name="voip")
pi_app.add_typer(_pi_power.app, name="power")
pi_app.add_typer(_pi_network.app, name="network")

app.add_typer(pi_app, name="pi")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_pi_tree.py -v`
Expected: PASS (3 passed)

Run: `uv run yoyopod pi --help`
Expected: All four subgroups listed.

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/main.py tests/test_yoyopod_cli_pi_tree.py
git commit -m "feat(cli): wire pi subapp in main.py"
```

---

## Task 19: Add top-level shortcuts (`deploy`, `status`, `logs`, `restart`, `validate`)

**Files:**
- Modify: `yoyopod_cli/main.py`
- Test: `tests/test_yoyopod_cli_shortcuts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_shortcuts.py
"""Test top-level aliases for hot-path commands."""
from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.main import app


def test_deploy_aliases_remote_sync(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "yoyopod_cli.remote_ops.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["deploy"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    # verify sync-shaped command
    assert "git fetch origin" in calls[0]


def test_status_alias(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "yoyopod_cli.remote_ops.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "git rev-parse HEAD" in calls[0]


def test_all_shortcuts_listed_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("deploy", "status", "logs", "restart", "validate"):
        assert cmd in result.output, f"missing top-level shortcut: {cmd}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_shortcuts.py -v`
Expected: FAIL — shortcuts not wired yet.

- [ ] **Step 3: Add shortcuts to `main.py`**

Append to `yoyopod_cli/main.py` after the `app.add_typer(pi_app, ...)` line:

```python
# --- top-level shortcuts (thin aliases wrapping the remote handlers)
# Each alias gets its own Typer.Context → RemoteConnection plumbing because
# the shared remote_app callback only fires for commands *inside* remote_app.
# Shortcuts invoke the underlying handler via a small wrapper that mimics
# the callback.
from yoyopod_cli.remote_shared import _resolve_remote_connection


def _shortcut(handler):
    """Return a top-level Typer-command wrapper that seeds ctx.obj then calls handler."""
    def wrapper(
        host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
        user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
        project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
        branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
        verbose: bool = typer.Option(False, "--verbose"),
    ) -> None:
        conn = _resolve_remote_connection(host, user, project_dir, branch)
        ctx = typer.Context(typer.Typer())  # minimal context just for ensure_object
        ctx.obj = conn
        handler(ctx=ctx, verbose=verbose)
    wrapper.__name__ = handler.__name__
    wrapper.__doc__ = handler.__doc__
    return wrapper


app.command(name="deploy")(_shortcut(_remote_ops.sync))
app.command(name="status")(_shortcut(_remote_ops.status))
app.command(name="restart")(_shortcut(_remote_ops.restart))
# logs + validate have extra options — use dedicated wrappers:

@app.command(name="logs")
def _logs_shortcut(
    host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
    user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
    project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
    branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    lines: int = typer.Option(50, "--lines"),
    follow: bool = typer.Option(False, "--follow", "-f"),
    errors: bool = typer.Option(False, "--errors"),
    filter: str = typer.Option("", "--filter"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Tail yoyopod logs on the Pi (alias for `remote logs`)."""
    conn = _resolve_remote_connection(host, user, project_dir, branch)
    ctx = typer.Context(typer.Typer())
    ctx.obj = conn
    _remote_ops.logs(ctx=ctx, lines=lines, follow=follow, errors=errors, filter=filter, verbose=verbose)


@app.command(name="validate")
def _validate_shortcut(
    host: str = typer.Option("", "--host", envvar="YOYOPOD_PI_HOST"),
    user: str = typer.Option("", "--user", envvar="YOYOPOD_PI_USER"),
    project_dir: str = typer.Option("", "--project-dir", envvar="YOYOPOD_PI_PROJECT_DIR"),
    branch: str = typer.Option("", "--branch", envvar="YOYOPOD_PI_BRANCH"),
    with_music: bool = typer.Option(False, "--with-music"),
    with_voip: bool = typer.Option(False, "--with-voip"),
    with_lvgl_soak: bool = typer.Option(False, "--with-lvgl-soak"),
    with_navigation: bool = typer.Option(False, "--with-navigation"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run staged Pi validation (alias for `remote validate`)."""
    conn = _resolve_remote_connection(host, user, project_dir, branch)
    ctx = typer.Context(typer.Typer())
    ctx.obj = conn
    _remote_validate.validate(
        ctx=ctx,
        with_music=with_music,
        with_voip=with_voip,
        with_lvgl_soak=with_lvgl_soak,
        with_navigation=with_navigation,
        verbose=verbose,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_shortcuts.py -v`
Expected: PASS (3 passed)

Run: `uv run yoyopod --help`
Expected: Top-level shortcuts visible.

- [ ] **Step 5: Commit**

```bash
git add yoyopod_cli/main.py tests/test_yoyopod_cli_shortcuts.py
git commit -m "feat(cli): add top-level deploy/status/logs/restart/validate shortcuts"
```

---

## Task 20: Build `_docgen.py` and generate `COMMANDS.md`

**Files:**
- Create: `yoyopod_cli/_docgen.py`
- Create: `yoyopod_cli/COMMANDS.md`
- Modify: `yoyopod_cli/main.py` (add `dev docs` command)
- Test: `tests/test_yoyopod_cli_docgen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_docgen.py
from __future__ import annotations

from yoyopod_cli._docgen import generate_commands_md
from yoyopod_cli.main import app


def test_docgen_contains_all_shortcut_commands() -> None:
    md = generate_commands_md(app)
    for cmd in ("deploy", "status", "logs", "restart", "validate"):
        assert f"`yoyopod {cmd}`" in md, f"missing shortcut: {cmd}"


def test_docgen_contains_remote_commands() -> None:
    md = generate_commands_md(app)
    assert "## `yoyopod remote" in md
    for cmd in ("status", "sync", "logs", "config", "power", "rtc", "service"):
        assert cmd in md, f"missing remote command: {cmd}"


def test_docgen_contains_pi_commands() -> None:
    md = generate_commands_md(app)
    assert "## `yoyopod pi" in md
    for cmd in ("validate", "voip", "power", "network"):
        assert cmd in md


def test_docgen_does_not_contain_cut_commands() -> None:
    md = generate_commands_md(app)
    for cut in (
        "gallery", "tune", "whisplay",
        "registration-stability", "reconnect-drill", "call-soak",
        "lvgl probe", "navigation-soak", "lvgl-soak",
        "rsync", "provision-test-music",
    ):
        assert cut not in md, f"cut command still present: {cut}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yoyopod_cli_docgen.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `yoyopod_cli/_docgen.py`**

```python
# yoyopod_cli/_docgen.py
"""Walk a Typer app and emit a markdown command-reference table."""

from __future__ import annotations

from io import StringIO

import typer
from click.core import Group


def _walk(typer_app: typer.Typer, prefix: str = "yoyopod") -> list[tuple[str, str]]:
    """Return [(full_path, short_help), ...] for every leaf command."""
    click_app = typer.main.get_command(typer_app)
    out: list[tuple[str, str]] = []
    _walk_click(click_app, prefix, out)
    return out


def _walk_click(click_cmd, prefix: str, out: list[tuple[str, str]]) -> None:
    if isinstance(click_cmd, Group):
        for name, sub in (click_cmd.commands or {}).items():
            _walk_click(sub, f"{prefix} {name}", out)
    else:
        help_text = click_cmd.short_help or click_cmd.help or ""
        out.append((prefix, help_text.strip().split("\n")[0]))


def generate_commands_md(typer_app: typer.Typer) -> str:
    """Emit the full COMMANDS.md string."""
    entries = _walk(typer_app)

    groups = {
        "Top-level shortcuts": [],
        "`yoyopod remote` — dev-machine → Pi via SSH": [],
        "`yoyopod pi` — on the Pi": [],
        "`yoyopod build`": [],
        "`yoyopod setup`": [],
    }

    for path, help_text in entries:
        parts = path.split()
        if len(parts) == 2:
            groups["Top-level shortcuts"].append((path, help_text))
        elif parts[1] == "remote":
            groups["`yoyopod remote` — dev-machine → Pi via SSH"].append((path, help_text))
        elif parts[1] == "pi":
            groups["`yoyopod pi` — on the Pi"].append((path, help_text))
        elif parts[1] == "build":
            groups["`yoyopod build`"].append((path, help_text))
        elif parts[1] == "setup":
            groups["`yoyopod setup`"].append((path, help_text))

    buf = StringIO()
    buf.write("# YoyoPod CLI — Command Reference\n\n")
    buf.write("Auto-generated by `_docgen.py`. Run `yoyopod dev docs` to regenerate.\n")
    buf.write("For live help, use `yoyopod <cmd> --help`.\n\n")

    for title, cmds in groups.items():
        if not cmds:
            continue
        buf.write(f"## {title}\n\n")
        buf.write("| Command | What it does |\n|---|---|\n")
        for path, help_text in sorted(cmds):
            buf.write(f"| `{path}` | {help_text or '—'} |\n")
        buf.write("\n")

    return buf.getvalue()
```

- [ ] **Step 4: Generate `COMMANDS.md` once**

Run from the repo root:

```bash
uv run python -c "from yoyopod_cli._docgen import generate_commands_md; from yoyopod_cli.main import app; open('yoyopod_cli/COMMANDS.md', 'w').write(generate_commands_md(app))"
```

- [ ] **Step 5: Add `yoyopod dev docs` to `main.py`**

Append to `yoyopod_cli/main.py`:

```python
dev_app = typer.Typer(name="dev", help="Developer utilities.", no_args_is_help=True)
app.add_typer(dev_app, name="dev")


@dev_app.command()
def docs() -> None:
    """Regenerate yoyopod_cli/COMMANDS.md from the live Typer tree."""
    from yoyopod_cli._docgen import generate_commands_md
    from yoyopod_cli.paths import HOST

    md = generate_commands_md(app)
    (HOST.repo_root / "yoyopod_cli" / "COMMANDS.md").write_text(md, encoding="utf-8")
    typer.echo("yoyopod_cli/COMMANDS.md regenerated.")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_yoyopod_cli_docgen.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Commit**

```bash
git add yoyopod_cli/_docgen.py yoyopod_cli/COMMANDS.md yoyopod_cli/main.py tests/test_yoyopod_cli_docgen.py
git commit -m "feat(cli): add _docgen and commit initial COMMANDS.md"
```

---

## Task 21: Wire `COMMANDS.md` drift check into quality gate

**Files:**
- Modify: `scripts/quality.py`
- Test: `tests/test_yoyopod_cli_docs_drift.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_yoyopod_cli_docs_drift.py
"""Verify yoyopod_cli/COMMANDS.md is in sync with the Typer tree."""
from __future__ import annotations

from pathlib import Path

from yoyopod_cli._docgen import generate_commands_md
from yoyopod_cli.main import app
from yoyopod_cli.paths import HOST


def test_commands_md_is_up_to_date() -> None:
    committed = (HOST.repo_root / "yoyopod_cli" / "COMMANDS.md").read_text(encoding="utf-8")
    regenerated = generate_commands_md(app)
    assert committed == regenerated, (
        "yoyopod_cli/COMMANDS.md is out of date. "
        "Run `uv run yoyopod dev docs` and commit."
    )
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_yoyopod_cli_docs_drift.py -v`
Expected: PASS (already in sync from Task 20).

- [ ] **Step 3: Commit**

```bash
git add tests/test_yoyopod_cli_docs_drift.py
git commit -m "test(cli): enforce COMMANDS.md stays in sync with Typer tree"
```

---

## Task 22: Update `pyproject.toml` quality-gate paths

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update the `[tool.yoyopod_quality]` paths**

Edit `pyproject.toml` lines 78–105:

Replace:
```toml
gate_format_paths = [
    "scripts/quality.py",
    "src/yoyopod/main.py",
    "src/yoyopod/cli/__init__.py",
    "src/yoyopod/cli/common.py",
    "src/yoyopod/cli/build.py",
    "src/yoyopod/cli/remote",
]
```
with:
```toml
gate_format_paths = [
    "scripts/quality.py",
    "src/yoyopod/main.py",
    "yoyopod_cli",
]
```

Apply the same replacement pattern to `gate_lint_paths` and `gate_type_paths`.

- [ ] **Step 2: Run the quality gate**

Run: `uv run python scripts/quality.py ci`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(cli): point quality-gate paths at yoyopod_cli"
```

---

## Task 23: Delete the legacy `src/yoyopod/cli/` tree

**Files:**
- Delete: `src/yoyopod/cli/` (entire directory)

- [ ] **Step 1: Verify new CLI handles the full surface before deletion**

Run these sanity checks (should all succeed, some may require a Pi):

```bash
uv run yoyopod --help
uv run yoyopod remote --help
uv run yoyopod pi --help
uv run yoyopod build --help
uv run yoyopod setup --help
uv run yoyopod deploy --help
uv run yoyopod status --help
uv run yoyopod logs --help
uv run yoyopod restart --help
uv run yoyopod validate --help
uv run yoyopod dev docs --help
```

- [ ] **Step 2: Delete the old tree**

```bash
git rm -r src/yoyopod/cli/
```

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/ -x`

Expected: Some tests still reference the old paths — these are migrated in Task 24. For now, collect the list of failures.

- [ ] **Step 4: Commit the deletion**

```bash
git commit -m "refactor(cli): delete legacy src/yoyopod/cli/ tree"
```

---

## Task 24: Migrate existing test files (import path rewrites)

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_cli_bootstrap.py`
- Modify: `tests/test_pi_remote.py`
- Modify: `tests/test_setup_cli.py`
- Modify: `tests/test_voip_cli.py`
- Modify: `tests/test_navigation_soak.py`
- Modify: `tests/test_remote_config_helpers.py`
- Modify: `tests/test_quality_script.py`

- [ ] **Step 1: Rewrite each `from yoyopod.cli.*` to `from yoyopod_cli.*`**

For each file above, replace:
- `from yoyopod.cli import app` → `from yoyopod_cli.main import app`
- `from yoyopod.cli.common import ...` → `from yoyopod_cli.common import ...`
- `from yoyopod.cli.remote.config import ...` → `from yoyopod_cli.paths import load_pi_paths` and `from yoyopod_cli.remote_shared import RemoteConnection`, mapping field names (see Task 24 notes below).
- `from yoyopod.cli.remote.transport import ...` → `from yoyopod_cli.remote_transport import ...`
- `from yoyopod.cli.remote.ops import ...` → `from yoyopod_cli.remote_ops import ...` (or `remote_validate`/`remote_infra` as appropriate — see `grep -n "from yoyopod.cli.remote.ops" tests/`)
- `from yoyopod.cli.pi.voip import ...` → `from yoyopod_cli.pi_voip import ...`
- `from yoyopod.cli.remote.navigation import ...` → `from yoyopod_cli.remote_validate import ...` (navigation-soak absorbed)

Field renames (`PiDeployConfig` → `RemoteConnection` + `PiPaths`):

- `PiDeployConfig.host/user/project_dir/branch` → `RemoteConnection.host/user/project_dir/branch`
- `PiDeployConfig.log_file/pid_file/startup_marker/...` → `PiPaths.log_file/pid_file/...`

- [ ] **Step 2: Rewrite monkeypatch targets**

Find all `monkeypatch.setattr("yoyopod.cli.remote.ops.*", ...)`:

Run: `grep -n "yoyopod.cli.remote.ops" tests/`

For each, update to the new module boundary:

| Old target | New target |
|---|---|
| `yoyopod.cli.remote.ops.subprocess.run` | `yoyopod_cli.remote_transport.subprocess.run` |
| `yoyopod.cli.remote.ops.shutil.which` | `yoyopod_cli.remote_transport.shutil.which` (add `import shutil` to transport if missing) |
| `yoyopod.cli.remote.ops.sys.platform` | (delete — sys.platform usage moved into run_rsync_deploy if still needed; otherwise stub in test) |
| `yoyopod.cli.remote.ops.run_local_capture` | `yoyopod_cli.remote_transport.run_local_capture` |
| `yoyopod.cli.remote.ops.run_remote_capture` | `yoyopod_cli.remote_transport.run_remote_capture` |
| `yoyopod.cli.remote.ops.validation.resolve_local_validation_target` | (function cut — delete the test or replace with direct argument passing) |
| `yoyopod.cli.remote.ops.validation._resolve_remote_config` | `yoyopod_cli.remote_shared._resolve_remote_connection` |
| `yoyopod.cli.remote.ops.validation.validate_config` | `yoyopod_cli.remote_transport.validate_config` |
| `yoyopod.cli.remote.ops.validation.run_remote` | `yoyopod_cli.remote_transport.run_remote` |

- [ ] **Step 3: Run the test suite**

Run: `uv run pytest tests/ -x`
Expected: PASS — any remaining failure is either a test of a cut command (handled in Task 25) or genuine bug to fix.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(cli): migrate test imports + monkeypatches to yoyopod_cli"
```

---

## Task 25: Delete tests for cut commands

**Files:**
- Delete: `tests/test_pi_gallery.py` (pi gallery cut)
- Delete: `tests/test_whisplay_tune.py` (pi tune + remote whisplay cut)
- Modify: `tests/test_navigation_soak.py` (navigation-soak absorbed; convert to test `remote validate --with-navigation`)

- [ ] **Step 1: Delete the tests for cut commands**

```bash
git rm tests/test_pi_gallery.py tests/test_whisplay_tune.py
```

- [ ] **Step 2: Rewrite `tests/test_navigation_soak.py`**

Replace its contents with a test that verifies `remote validate --with-navigation` produces the right shell payload:

```python
# tests/test_navigation_soak.py
"""Regression test — navigation-soak is now a flag on remote validate."""
from __future__ import annotations

from yoyopod_cli.remote_validate import _build_validate


def test_with_navigation_flag_appends_navigation_stage() -> None:
    shell = _build_validate(
        with_music=False,
        with_voip=False,
        with_lvgl_soak=False,
        with_navigation=True,
    )
    assert "yoyopod pi validate navigation" in shell


def test_without_flag_skips_navigation_stage() -> None:
    shell = _build_validate(
        with_music=False,
        with_voip=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "yoyopod pi validate navigation" not in shell
```

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/`
Expected: PASS — whole suite green.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "test(cli): drop tests for cut commands; convert navigation-soak to flag test"
```

---

## Task 26: Doc sweep — replace `yoyopod` with `yoyopod` everywhere

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/DEVELOPMENT_GUIDE.md`
- Modify: `docs/PI_DEV_WORKFLOW.md`
- Modify: `docs/RPI_SMOKE_VALIDATION.md`
- Modify: `docs/SYSTEM_ARCHITECTURE.md`
- Modify: `rules/*.md`
- Modify: `skills/yoyopod-*/SKILL.md`

- [ ] **Step 1: Find all occurrences of `yoyopod`**

Run: `grep -rln "yoyopod" CLAUDE.md README.md AGENTS.md docs/ rules/ skills/`

Record the list.

- [ ] **Step 2: Find-replace in each file**

For each file in the list, replace `yoyopod` → `yoyopod`. In most contexts this is a literal replacement; hand-review each doc to catch:
- Any mention of `yoyopod` as a separate concept (e.g., "the `yoyopod` CLI") — reword to "the `yoyopod` CLI" or "the YoyoPod CLI".
- Any script shown running `uv run yoyopod` → `uv run yoyopod`.

- [ ] **Step 3: Update skills for removed commands**

For these skills, add a note that the relevant commands have been removed:

- `skills/yoyopod-*/SKILL.md`: refresh command examples to the new names (most are already `yoyopod pi xxx` or `yoyopod remote xxx` — just the binary name changes).

If any skill references `pi tune`, `pi gallery`, `remote whisplay`, `remote rsync`, `pi voip registration-stability`, `pi voip reconnect-drill`, `pi voip call-soak`, `pi lvgl probe`, `pi lvgl soak`, `remote navigation-soak`, or `remote lvgl-soak` directly, replace with the surviving equivalent:

| Old | New |
|---|---|
| `pi lvgl soak` | `pi validate lvgl` |
| `remote lvgl-soak` | `remote validate --with-lvgl-soak` |
| `remote navigation-soak` | `remote validate --with-navigation` |
| `pi voip registration-stability` | `pi validate voip --soak registration` |
| `pi voip reconnect-drill` | `pi validate voip --soak reconnect` |
| `pi voip call-soak` | `pi validate voip --soak call` |
| `remote rsync` | `remote sync` |
| `remote smoke` | `remote validate` |
| `pi smoke` | `pi validate smoke` |

- [ ] **Step 4: Re-run grep to verify**

Run: `grep -rn "yoyopod" CLAUDE.md README.md AGENTS.md docs/ rules/ skills/`
Expected: No matches.

- [ ] **Step 5: Run the quality gate**

Run: `uv run python scripts/quality.py ci`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md README.md AGENTS.md docs/ rules/ skills/
git commit -m "docs: rename yoyopod → yoyopod across docs/skills/rules"
```

---

## Task 27: Final verification

**Files:** (none — verification only)

- [ ] **Step 1: Clean install and test from scratch**

Run:
```bash
rm -rf .venv
uv sync --extra dev
uv run yoyopod --version
```
Expected: `yoyopod 0.1.0`

- [ ] **Step 2: Full CI**

Run: `uv run python scripts/quality.py ci`
Expected: PASS.

Run: `uv run pytest tests/`
Expected: PASS.

- [ ] **Step 3: Verify `yoyopod dev docs` round-trip**

Run:
```bash
uv run yoyopod dev docs
git diff yoyopod_cli/COMMANDS.md
```
Expected: No diff — `COMMANDS.md` is already in sync.

- [ ] **Step 4: Sanity-check help output**

Run:
```bash
uv run yoyopod --help
uv run yoyopod remote --help
uv run yoyopod pi --help
uv run yoyopod pi validate --help
uv run yoyopod pi validate voip --help
```

Visually confirm:
- Top-level shortcuts (`deploy`, `status`, `logs`, `restart`, `validate`) are visible.
- `remote` group lists every KEEP command from the spec and no CUT command.
- `pi validate` lists `deploy`, `smoke`, `music`, `voip`, `stability`, `navigation`, `lvgl`.
- `pi validate voip --help` shows the `--soak` flag.

- [ ] **Step 5: Real-hardware validation (optional — ideally on Pi)**

If a Pi is reachable:

```bash
uv run yoyopod deploy
uv run yoyopod pi validate deploy
uv run yoyopod pi validate smoke
```

Expected: deploy → smoke passes end-to-end.

- [ ] **Step 6: Final commit (if any trailing fixes)**

If any of the steps above required fixes, commit them:

```bash
git add .
git commit -m "chore(cli): final fixes from verification"
```

---

## Self-Review Checklist

### Spec coverage
- §2 In scope: all 10 bullets covered by Tasks 1–27. ✓
- §3 Target layout: Tasks 1–17 create the listed files. Tasks 23 deletes the old tree. ✓
- §4 Command triage: KEEP list covered by Tasks 6–18. CUT list handled by not porting + Task 25. Top-level shortcuts in Task 19. ✓
- §5 Command pattern: Applied in every port task (6–17). ✓
- §6 Shared remote options: Task 4. ✓
- §7 paths.py: Task 2. ✓
- §8 main.py entry: Tasks 5, 13, 18, 19. ✓
- §9 COMMANDS.md auto-generation + CI check: Tasks 20, 21. ✓
- §10 Testing approach: Tasks 24, 25 (migrations + deletions). New tests added throughout. ✓
- §11 Documentation updates: Task 26. ✓
- §12 Migration / cutover: Tasks 1–27 map 1:1 against §12's 14 steps (some split for bite-size). ✓
- pyproject.toml gate paths: Task 22. ✓

### Placeholder scan
- No `TBD` / `TODO` / `FIXME` in code blocks.
- No "add error handling" — all error paths in templates are explicit.
- Code blocks provided wherever a step changes code.
- Commit messages show exact text.

### Type consistency
- `RemoteConnection` signature consistent across Tasks 3, 4, 8, 10, 11, 12, 13, 19.
- `PiPaths` fields consistent across Tasks 2, 8, 10.
- Helper function names: `_build_*` convention applied uniformly across all port tasks.
- `pi_conn(ctx)` used consistently in every remote command.
- `configure_logging(verbose)` used consistently as first line of every handler.

All clear.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-20-cli-polish.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a refactor this size where each task is independently reviewable.

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
