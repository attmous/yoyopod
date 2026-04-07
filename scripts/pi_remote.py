#!/usr/bin/env python3
"""Developer helper for common YoyoPod Raspberry Pi workflows over SSH."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml


@dataclass
class RemoteConfig:
    """Connection details for the Raspberry Pi host."""

    host: str
    user: str
    project_dir: str
    branch: str

    @property
    def ssh_target(self) -> str:
        """Return the SSH target in user@host form when a user is configured."""
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


@dataclass(frozen=True)
class PiDeployConfig:
    """Stable runtime paths used by the Pi deploy/debugging workflow."""

    host: str = ""
    user: str = ""
    project_dir: str = "~/yoyo-py"
    branch: str = "main"
    venv: str = ".venv"
    start_cmd: str = "python yoyopod.py"
    kill_processes: tuple[str, ...] = ("python", "linphonec")
    log_file: str = "logs/yoyopod.log"
    error_log_file: str = "logs/yoyopod_errors.log"
    pid_file: str = "/tmp/yoyopod.pid"
    startup_marker: str = "YoyoPod starting"
    screenshot_path: str = "/tmp/yoyopod_screenshot.png"
    rsync_exclude: tuple[str, ...] = (
        ".git/",
        "__pycache__/",
        "*.pyc",
        ".venv/",
        "logs/",
        "node_modules/",
        "*.egg-info/",
    )


def load_pi_deploy_config() -> PiDeployConfig:
    """Load the checked-in Raspberry Pi deploy contract."""

    config_path = Path(__file__).resolve().parent.parent / "deploy" / "pi-deploy.yaml"
    with open(config_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return PiDeployConfig(
        host=str(data.get("host", "")).strip(),
        user=str(data.get("user", "")).strip(),
        project_dir=str(
            data.get("project_dir", data.get("remote_dir", "~/yoyo-py"))
        ).strip()
        or "~/yoyo-py",
        branch=str(data.get("branch", "main")).strip() or "main",
        venv=str(data.get("venv", ".venv")).strip() or ".venv",
        start_cmd=str(data.get("start_cmd", "python yoyopod.py")).strip()
        or "python yoyopod.py",
        kill_processes=tuple(
            str(process).strip()
            for process in data.get("kill_processes", ("python", "linphonec"))
            if str(process).strip()
        )
        or ("python", "linphonec"),
        log_file=str(data["log_file"]).strip(),
        error_log_file=str(data["error_log_file"]).strip(),
        pid_file=str(data["pid_file"]).strip(),
        startup_marker=str(data["startup_marker"]).strip(),
        screenshot_path=str(
            data.get("screenshot_path", "/tmp/yoyopod_screenshot.png")
        ).strip()
        or "/tmp/yoyopod_screenshot.png",
        rsync_exclude=tuple(
            str(pattern)
            for pattern in data.get(
                "rsync_exclude",
                (
                    ".git/",
                    "__pycache__/",
                    "*.pyc",
                    ".venv/",
                    "logs/",
                    "node_modules/",
                    "*.egg-info/",
                ),
            )
        ),
    )


def build_parser(deploy_config: PiDeployConfig) -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run common YoyoPod Raspberry Pi development tasks over SSH. "
            "Defaults can be provided with YOYOPOD_PI_HOST, "
            "YOYOPOD_PI_PROJECT_DIR, and YOYOPOD_PI_BRANCH, or "
            "through deploy/pi-deploy.yaml."
        )
    )
    parser.add_argument(
        "--host",
        default=os.getenv("YOYOPOD_PI_HOST", deploy_config.host),
        help="SSH host or alias for the Raspberry Pi",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("YOYOPOD_PI_USER", deploy_config.user),
        help="SSH user for the Raspberry Pi (optional)",
    )
    parser.add_argument(
        "--project-dir",
        default=os.getenv("YOYOPOD_PI_PROJECT_DIR", deploy_config.project_dir),
        help="Project directory on the Raspberry Pi (default: ~/yoyo-py)",
    )
    parser.add_argument(
        "--branch",
        default=os.getenv("YOYOPOD_PI_BRANCH", deploy_config.branch),
        help="Git branch to sync on the Raspberry Pi (default: main)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "status",
        help="Show remote repo, Mopidy, and process status",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Fetch, checkout, pull, and optionally run uv sync on the Raspberry Pi",
    )
    sync_parser.add_argument(
        "--skip-uv-sync",
        action="store_true",
        help="Skip `uv sync --extra dev` after pulling",
    )

    rsync_parser = subparsers.add_parser(
        "rsync",
        help="Rsync the local working tree to the Raspberry Pi and restart the app",
    )
    rsync_parser.add_argument(
        "--skip-restart",
        action="store_true",
        help="Only rsync files without restarting the app afterward",
    )

    restart_parser = subparsers.add_parser(
        "restart",
        help="Kill and relaunch the production app on the Raspberry Pi",
    )

    screenshot_parser = subparsers.add_parser(
        "screenshot",
        help="Capture a screenshot from the running app on the Raspberry Pi",
    )
    screenshot_parser.add_argument(
        "--readback",
        action="store_true",
        help="Use LVGL readback (SIGUSR2) instead of the shadow buffer (SIGUSR1)",
    )
    screenshot_parser.add_argument(
        "--output",
        default="pi_screenshot.png",
        help="Local path for the downloaded screenshot (default: ./pi_screenshot.png)",
    )

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="Run the Raspberry Pi smoke validator remotely",
    )
    smoke_parser.add_argument(
        "--with-power",
        action="store_true",
        help="Include PiSugar power checks",
    )
    smoke_parser.add_argument(
        "--with-rtc",
        action="store_true",
        help="Include PiSugar RTC checks",
    )
    smoke_parser.add_argument(
        "--with-mopidy",
        action="store_true",
        help="Include Mopidy connectivity checks",
    )
    smoke_parser.add_argument(
        "--with-voip",
        action="store_true",
        help="Include SIP registration checks",
    )
    smoke_parser.add_argument(
        "--with-lvgl-soak",
        action="store_true",
        help="Include a short LVGL transition and sleep/wake soak",
    )
    smoke_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose smoke-script logging",
    )
    smoke_parser.add_argument(
        "--mopidy-timeout",
        type=int,
        default=5,
        help="Mopidy request timeout in seconds (default: 5)",
    )
    smoke_parser.add_argument(
        "--voip-timeout",
        type=float,
        default=10.0,
        help="VoIP registration timeout in seconds (default: 10)",
    )

    whisplay_parser = subparsers.add_parser(
        "whisplay",
        help="Run the Whisplay gesture-tuning helper remotely",
    )
    whisplay_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose tuner logging",
    )
    whisplay_parser.add_argument(
        "--duration-seconds",
        type=float,
        default=30.0,
        help="How long to monitor gestures before exiting (default: 30)",
    )
    whisplay_parser.add_argument(
        "--debounce-ms",
        type=int,
        help="Temporary Whisplay debounce override in milliseconds",
    )
    whisplay_parser.add_argument(
        "--double-tap-ms",
        type=int,
        help="Temporary Whisplay double-tap override in milliseconds",
    )
    whisplay_parser.add_argument(
        "--long-hold-ms",
        type=int,
        help="Temporary Whisplay long-hold override in milliseconds",
    )
    whisplay_parser.add_argument(
        "--no-display",
        action="store_true",
        help="Log events only without drawing tuner hints on the display",
    )

    lvgl_soak_parser = subparsers.add_parser(
        "lvgl-soak",
        help="Run the LVGL Whisplay soak helper remotely",
    )
    lvgl_soak_parser.add_argument(
        "--cycles",
        type=int,
        default=2,
        help="How many full transition cycles to run (default: 2)",
    )
    lvgl_soak_parser.add_argument(
        "--hold-seconds",
        type=float,
        default=0.2,
        help="How long to keep each screen active (default: 0.2)",
    )
    lvgl_soak_parser.add_argument(
        "--skip-sleep",
        action="store_true",
        help="Skip the sleep/wake exercise",
    )
    lvgl_soak_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose soak logging",
    )

    rtc_parser = subparsers.add_parser(
        "rtc",
        help="Inspect or control PiSugar RTC state remotely",
    )
    rtc_parser.add_argument(
        "rtc_action",
        nargs="?",
        default="status",
        choices=["status", "sync-to-rtc", "sync-from-rtc", "set-alarm", "disable-alarm"],
        help="RTC action to run remotely (default: status)",
    )
    rtc_parser.add_argument(
        "--time",
        help="ISO8601 timestamp for set-alarm, e.g. 2026-04-06T07:30:00+02:00",
    )
    rtc_parser.add_argument(
        "--repeat-mask",
        type=int,
        default=127,
        help="Weekday repeat bitmask for set-alarm (default: 127)",
    )
    rtc_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose RTC helper logging",
    )

    power_parser = subparsers.add_parser(
        "power",
        help="Inspect PiSugar power telemetry remotely",
    )
    power_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose power helper logging",
    )

    logs_parser = subparsers.add_parser(
        "logs",
        help="Tail the file-based YoyoPod logs on the Raspberry Pi",
    )
    logs_parser.add_argument(
        "--errors",
        action="store_true",
        help="Read the errors-only log file instead of the main log",
    )
    logs_parser.add_argument(
        "--follow",
        action="store_true",
        help="Follow the log output until interrupted",
    )
    logs_parser.add_argument(
        "--filter",
        help="Case-insensitive grep filter for subsystem, module, level, or text",
    )
    logs_parser.add_argument(
        "--lines",
        type=int,
        default=100,
        help="How many lines to show before following (default: 100)",
    )

    service_parser = subparsers.add_parser(
        "service",
        help="Install or inspect the production YoyoPod systemd service",
    )
    service_parser.add_argument(
        "service_action",
        nargs="?",
        default="status",
        choices=["status", "install", "start", "stop", "restart", "logs"],
        help="Service action to run remotely (default: status)",
    )
    service_parser.add_argument(
        "--lines",
        type=int,
        default=100,
        help="How many journal lines to show for `service logs` (default: 100)",
    )

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Run local checks, sync the Pi, and execute the Pi smoke pass",
    )
    preflight_parser.add_argument(
        "--skip-local",
        action="store_true",
        help="Skip local compile/test verification before remote work",
    )
    preflight_parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Skip the remote git pull and dependency sync step",
    )
    preflight_parser.add_argument(
        "--skip-uv-sync",
        action="store_true",
        help="Skip `uv sync --extra dev` during the remote sync step",
    )
    preflight_parser.add_argument(
        "--with-power",
        action="store_true",
        help="Include PiSugar power checks in the remote smoke pass",
    )
    preflight_parser.add_argument(
        "--with-rtc",
        action="store_true",
        help="Include PiSugar RTC checks in the remote smoke pass",
    )
    preflight_parser.add_argument(
        "--with-mopidy",
        action="store_true",
        help="Include Mopidy connectivity checks in the remote smoke pass",
    )
    preflight_parser.add_argument(
        "--with-voip",
        action="store_true",
        help="Include SIP registration checks in the remote smoke pass",
    )
    preflight_parser.add_argument(
        "--with-lvgl-soak",
        action="store_true",
        help="Include the LVGL soak helper in the remote smoke pass",
    )
    preflight_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose smoke-script logging",
    )
    preflight_parser.add_argument(
        "--mopidy-timeout",
        type=int,
        default=5,
        help="Mopidy request timeout in seconds (default: 5)",
    )
    preflight_parser.add_argument(
        "--voip-timeout",
        type=float,
        default=10.0,
        help="VoIP registration timeout in seconds (default: 10)",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Start the production app on the Raspberry Pi",
    )
    run_parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run the app in simulation mode instead of hardware mode",
    )
    run_parser.add_argument(
        "--app-arg",
        action="append",
        default=[],
        help="Extra argument to pass through to yoyopod.py (repeatable)",
    )

    return parser


def validate_config(config: RemoteConfig) -> None:
    """Ensure required connection details are present."""
    if not config.host:
        raise SystemExit(
            "Missing Raspberry Pi host. Set it in deploy/pi-deploy.yaml, "
            "pass --host, or set YOYOPOD_PI_HOST."
        )


def quote_remote_project_dir(project_dir: str) -> str:
    """Quote the remote project path while preserving `~` expansion."""
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
    wrapped_command = (
        f"cd {quote_remote_project_dir(config.project_dir)} && {remote_command}"
    )
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


def shell_quote(value: str) -> str:
    """Shell-escape one literal value for the remote command string."""

    return shlex.quote(value)


def _activate_script_path(venv: str) -> str:
    """Return the shell path for activating the configured virtualenv."""
    normalized = venv.rstrip("/")
    if normalized.endswith("/bin/activate"):
        return normalized
    return f"{normalized}/bin/activate"


def build_status_command(deploy_config: PiDeployConfig | None = None) -> str:
    """Create the remote status command."""
    deploy = deploy_config or load_pi_deploy_config()
    return " && ".join(
        [
            "echo '== Git ==' ",
            "git branch --show-current",
            "git rev-parse --short HEAD",
            "git status --short",
            "echo",
            "echo '== Mopidy ==' ",
            "systemctl --user is-active mopidy || true",
            "echo",
            "echo '== YoyoPod Service ==' ",
            "systemctl is-active \"yoyopod@$(id -un).service\" || true",
            "echo",
            "echo '== PiSugar Server ==' ",
            "systemctl is-active pisugar-server || true",
            "echo",
            "echo '== PID File ==' ",
            (
                f"if test -f {shell_quote(deploy.pid_file)}; "
                f"then cat {shell_quote(deploy.pid_file)}; "
                "else echo 'missing'; fi"
            ),
            "echo",
            "echo '== Latest Startup Marker ==' ",
            (
                f"if test -f {shell_quote(deploy.log_file)}; "
                f"then grep -F {shell_quote(deploy.startup_marker)} {shell_quote(deploy.log_file)} | tail -n 1 || true; "
                "else echo 'missing'; fi"
            ),
            "echo",
            "echo '== Top Processes ==' ",
            "ps -eo pid,comm,%mem,%cpu --sort=-%mem | head -15",
        ]
    )


def build_sync_command(config: RemoteConfig, skip_uv_sync: bool) -> str:
    """Create the remote sync command."""
    commands = [
        "git fetch origin",
        f"git checkout {shlex.quote(config.branch)}",
        f"git pull --ff-only origin {shlex.quote(config.branch)}",
    ]
    if not skip_uv_sync:
        commands.append("uv sync --extra dev")
    return " && ".join(commands)


def build_rsync_command(
    config: RemoteConfig,
    deploy_config: PiDeployConfig,
) -> list[str]:
    """Create the local rsync command for a dirty-tree sync."""
    command = ["rsync", "-avz", "--delete"]
    for pattern in deploy_config.rsync_exclude:
        command.extend(["--exclude", pattern])

    remote_dir = config.project_dir.rstrip("/")
    command.extend(["./", f"{config.ssh_target}:{remote_dir}/"])
    return command


def build_restart_command(deploy_config: PiDeployConfig) -> str:
    """Create the remote restart command for the production app."""
    pid_file = shell_quote(deploy_config.pid_file)
    activate_script = shell_quote(_activate_script_path(deploy_config.venv))

    commands = [
        f"(test -f {pid_file} && kill -9 $(cat {pid_file}) 2>/dev/null) || true",
    ]
    for process_name in deploy_config.kill_processes:
        commands.append(f"killall -9 {shell_quote(process_name)} 2>/dev/null || true")

    commands.extend(
        [
            f"source {activate_script} && nohup {deploy_config.start_cmd} > /dev/null 2>&1 &",
            build_startup_verification_command(deploy_config),
        ]
    )
    return " && ".join(commands)


def build_smoke_command(args: argparse.Namespace) -> str:
    """Create the remote smoke-validation command."""
    parts = ["uv run python scripts/pi_smoke.py"]
    if getattr(args, "with_power", False):
        parts.append("--with-power")
    if getattr(args, "with_rtc", False):
        parts.append("--with-rtc")
    if getattr(args, "with_mopidy", False):
        parts.append("--with-mopidy")
    if getattr(args, "with_voip", False):
        parts.append("--with-voip")
    if getattr(args, "with_lvgl_soak", False):
        parts.append("--with-lvgl-soak")
    if getattr(args, "verbose", False):
        parts.append("--verbose")
    if getattr(args, "mopidy_timeout", 5) != 5:
        parts.extend(["--mopidy-timeout", str(args.mopidy_timeout)])
    if getattr(args, "voip_timeout", 10.0) != 10.0:
        parts.extend(["--voip-timeout", str(args.voip_timeout)])
    return " ".join(parts)


def build_lvgl_soak_command(args: argparse.Namespace) -> str:
    """Create the remote LVGL soak command."""

    parts = ["uv run python scripts/lvgl_soak.py"]
    if args.verbose:
        parts.append("--verbose")
    if args.cycles != 2:
        parts.extend(["--cycles", str(args.cycles)])
    if args.hold_seconds != 0.2:
        parts.extend(["--hold-seconds", str(args.hold_seconds)])
    if args.skip_sleep:
        parts.append("--skip-sleep")
    return " ".join(parts)


def build_whisplay_command(args: argparse.Namespace) -> str:
    """Create the remote Whisplay tuning command."""
    parts = ["uv run python scripts/whisplay_tune.py"]
    if args.verbose:
        parts.append("--verbose")
    if args.no_display:
        parts.append("--no-display")
    if args.duration_seconds != 30.0:
        parts.extend(["--duration-seconds", str(args.duration_seconds)])
    if args.debounce_ms is not None:
        parts.extend(["--debounce-ms", str(args.debounce_ms)])
    if args.double_tap_ms is not None:
        parts.extend(["--double-tap-ms", str(args.double_tap_ms)])
    if args.long_hold_ms is not None:
        parts.extend(["--long-hold-ms", str(args.long_hold_ms)])
    return " ".join(parts)


def build_rtc_command(args: argparse.Namespace) -> str:
    """Create the remote PiSugar RTC command."""
    parts = ["uv run python scripts/pisugar_rtc.py"]
    if args.verbose:
        parts.append("--verbose")
    parts.append(args.rtc_action)
    if args.rtc_action == "set-alarm":
        if not args.time:
            raise SystemExit("--time is required for `pi_remote.py rtc set-alarm`")
        parts.extend(["--time", shlex.quote(args.time)])
        if args.repeat_mask != 127:
            parts.extend(["--repeat-mask", str(args.repeat_mask)])
    return " ".join(parts)


def build_power_command(args: argparse.Namespace) -> str:
    """Create the remote PiSugar power-status command."""
    parts = ["uv run python scripts/pisugar_power.py"]
    if args.verbose:
        parts.append("--verbose")
    return " ".join(parts)


def build_logs_command(
    args: argparse.Namespace,
    deploy_config: PiDeployConfig | None = None,
) -> str:
    """Create the remote file-log inspection command."""

    deploy = deploy_config or load_pi_deploy_config()
    target_log = deploy.error_log_file if args.errors else deploy.log_file
    tail_mode = "-F" if args.follow else ""
    base_tail = f"tail -n {args.lines} {tail_mode} {shell_quote(target_log)}".strip()

    if args.filter:
        return (
            f"test -f {shell_quote(target_log)} && "
            f"{base_tail} | grep --line-buffered -i -- {shell_quote(args.filter)}"
        )

    return f"test -f {shell_quote(target_log)} && {base_tail}"


def build_startup_verification_command(
    deploy_config: PiDeployConfig | None = None,
    *,
    attempts: int = 20,
) -> str:
    """Create a remote command that waits for the startup marker and matching PID."""

    deploy = deploy_config or load_pi_deploy_config()
    pid_file = shell_quote(deploy.pid_file)
    log_file = shell_quote(deploy.log_file)
    startup_marker = shell_quote(deploy.startup_marker)
    return " && ".join(
        [
            (
                f"for _ in $(seq 1 {attempts}); do "
                f"test -f {pid_file} && break; "
                "sleep 1; "
                "done"
            ),
            f"test -f {pid_file}",
            f'pid="$(tr -d \'\\n\' < {pid_file})"',
            'test -n "$pid"',
            'kill -0 "$pid"',
            (
                f"for _ in $(seq 1 {attempts}); do "
                f"if test -f {log_file} && "
                f"grep -F {startup_marker} {log_file} | tail -n 1 | grep -F \"pid=$pid\" >/dev/null; then "
                "break; "
                "fi; "
                "sleep 1; "
                "done"
            ),
            f"grep -F {startup_marker} {log_file} | tail -n 1 | grep -F \"pid=$pid\"",
        ]
    )


def build_service_command(
    args: argparse.Namespace,
    deploy_config: PiDeployConfig | None = None,
) -> str:
    """Create the remote systemd service command."""
    deploy = deploy_config or load_pi_deploy_config()
    service_name = 'yoyopod@"$(id -un)".service'
    verify_startup = build_startup_verification_command(deploy)

    if args.service_action == "status":
        return f"sudo systemctl status {service_name} --no-pager || true"

    if args.service_action == "install":
        return " && ".join(
            [
                "test -f deploy/systemd/yoyopod@.service",
                "sudo cp deploy/systemd/yoyopod@.service /etc/systemd/system/yoyopod@.service",
                "sudo systemctl daemon-reload",
                f"sudo systemctl enable --now {service_name}",
                verify_startup,
                f"sudo systemctl status {service_name} --no-pager",
            ]
        )

    if args.service_action == "start":
        return (
            f"sudo systemctl start {service_name} && "
            f"{verify_startup} && "
            f"sudo systemctl status {service_name} --no-pager"
        )

    if args.service_action == "stop":
        return f"sudo systemctl stop {service_name} && sudo systemctl status {service_name} --no-pager || true"

    if args.service_action == "restart":
        return (
            f"sudo systemctl restart {service_name} && "
            f"{verify_startup} && "
            f"sudo systemctl status {service_name} --no-pager"
        )

    if args.service_action == "logs":
        return f"sudo journalctl -u {service_name} -n {args.lines} --no-pager"

    raise SystemExit(f"Unsupported service action: {args.service_action}")


def build_run_command(args: argparse.Namespace) -> str:
    """Create the remote production-app command."""
    parts = ["uv run python yoyopod.py"]
    if args.simulate:
        parts.append("--simulate")
    for app_arg in args.app_arg:
        parts.append(shlex.quote(app_arg))
    return " ".join(parts)


def build_local_preflight_commands() -> list[tuple[str, list[str]]]:
    """Create the local verification commands for preflight."""
    return [
        (
            "compileall",
            [
                sys.executable,
                "-m",
                "compileall",
                "yoyopy",
                "tests",
                "scripts/pi_smoke.py",
                "scripts/pi_remote.py",
                "scripts/pisugar_rtc.py",
                "scripts/pisugar_power.py",
                "scripts/whisplay_tune.py",
                "scripts/lvgl_soak.py",
            ],
        ),
        (
            "pytest",
            ["uv", "run", "pytest", "-q"],
        ),
    ]


def run_rsync_deploy(
    config: RemoteConfig,
    deploy_config: PiDeployConfig,
    *,
    skip_restart: bool,
) -> int:
    """Rsync the local working tree to the Pi and optionally restart the app."""
    exit_code = run_local(build_rsync_command(config, deploy_config), "rsync")
    if exit_code != 0 or skip_restart:
        return exit_code

    return run_remote(config, build_restart_command(deploy_config))


def run_screenshot(
    config: RemoteConfig,
    deploy_config: PiDeployConfig,
    args: argparse.Namespace,
) -> int:
    """Capture a screenshot from the remote app and copy it locally."""
    pid_file = shell_quote(deploy_config.pid_file)
    screenshot_path = shell_quote(deploy_config.screenshot_path)

    alive_result = run_remote_capture(
        config,
        f"test -f {pid_file} && kill -0 $(cat {pid_file}) 2>/dev/null && echo ALIVE || echo DEAD",
    )
    if alive_result.returncode != 0 or alive_result.stdout.strip() != "ALIVE":
        print("Remote app is not running; restart it before requesting a screenshot.")
        if alive_result.stderr.strip():
            print(alive_result.stderr.strip())
        return 1

    signal_name = "USR2" if args.readback else "USR1"
    signal_result = run_remote_capture(
        config,
        f"kill -{signal_name} $(cat {pid_file})",
    )
    if signal_result.returncode != 0:
        print("Failed to trigger screenshot capture on the Raspberry Pi.")
        if signal_result.stderr.strip():
            print(signal_result.stderr.strip())
        return signal_result.returncode

    verify_result = run_remote_capture(
        config,
        f"sleep 1 && test -f {screenshot_path} && echo READY || echo MISSING",
    )
    if verify_result.returncode != 0 or verify_result.stdout.strip() != "READY":
        print(
            "Screenshot was not created on the Raspberry Pi. "
            "Confirm the app is running and screenshot handlers are installed."
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
    print(f"[pi-remote] local=screenshot-copy")
    print(f"[pi-remote] cmd={shlex.join(scp_command)}")
    print("")
    copy_result = subprocess.run(scp_command, check=False)
    if copy_result.returncode == 0:
        print(f"Saved screenshot to {output_path}")
    return copy_result.returncode


def run_preflight(config: RemoteConfig, args: argparse.Namespace) -> int:
    """Run the combined local + remote preflight flow."""
    if not args.skip_local:
        for label, command in build_local_preflight_commands():
            exit_code = run_local(command, label)
            if exit_code != 0:
                return exit_code

    if not args.skip_sync:
        exit_code = run_remote(
            config,
            build_sync_command(config, args.skip_uv_sync),
        )
        if exit_code != 0:
            return exit_code

    return run_remote(config, build_smoke_command(args))


def main() -> int:
    """Program entry point."""
    deploy_config = load_pi_deploy_config()
    parser = build_parser(deploy_config)
    args = parser.parse_args()

    config = RemoteConfig(
        host=args.host,
        user=args.user,
        project_dir=args.project_dir,
        branch=args.branch,
    )
    validate_config(config)

    if args.command == "status":
        return run_remote(config, build_status_command(deploy_config))

    if args.command == "sync":
        return run_remote(config, build_sync_command(config, args.skip_uv_sync))

    if args.command == "rsync":
        return run_rsync_deploy(
            config,
            deploy_config,
            skip_restart=args.skip_restart,
        )

    if args.command == "smoke":
        return run_remote(config, build_smoke_command(args))

    if args.command == "whisplay":
        return run_remote(config, build_whisplay_command(args), tty=True)

    if args.command == "lvgl-soak":
        return run_remote(config, build_lvgl_soak_command(args), tty=True)

    if args.command == "rtc":
        return run_remote(config, build_rtc_command(args))

    if args.command == "power":
        return run_remote(config, build_power_command(args))

    if args.command == "logs":
        return run_remote(config, build_logs_command(args, deploy_config), tty=args.follow)

    if args.command == "restart":
        return run_remote(config, build_restart_command(deploy_config))

    if args.command == "screenshot":
        return run_screenshot(config, deploy_config, args)

    if args.command == "service":
        return run_remote(config, build_service_command(args, deploy_config))

    if args.command == "preflight":
        return run_preflight(config, args)

    if args.command == "run":
        return run_remote(config, build_run_command(args), tty=True)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
