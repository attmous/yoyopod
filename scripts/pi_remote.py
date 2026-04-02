#!/usr/bin/env python3
"""Developer helper for common YoyoPod Raspberry Pi workflows over SSH."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence


@dataclass
class RemoteConfig:
    """Connection details for the Raspberry Pi host."""

    host: str
    project_dir: str
    branch: str


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run common YoyoPod Raspberry Pi development tasks over SSH. "
            "Defaults can be provided with YOYOPOD_PI_HOST, "
            "YOYOPOD_PI_PROJECT_DIR, and YOYOPOD_PI_BRANCH."
        )
    )
    parser.add_argument(
        "--host",
        default=os.getenv("YOYOPOD_PI_HOST", ""),
        help="SSH host or alias for the Raspberry Pi",
    )
    parser.add_argument(
        "--project-dir",
        default=os.getenv("YOYOPOD_PI_PROJECT_DIR", "~/yoyo-py"),
        help="Project directory on the Raspberry Pi (default: ~/yoyo-py)",
    )
    parser.add_argument(
        "--branch",
        default=os.getenv("YOYOPOD_PI_BRANCH", "main"),
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

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="Run the Raspberry Pi smoke validator remotely",
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
            "Missing Raspberry Pi host. Pass --host or set YOYOPOD_PI_HOST."
        )


def quote_remote_project_dir(project_dir: str) -> str:
    """Quote the remote project path while preserving `~` expansion."""
    if project_dir == "~":
        return '"$HOME"'

    if project_dir.startswith("~/"):
        suffix = project_dir[2:].replace('"', '\\"')
        return f'"$HOME/{suffix}"'

    return shlex.quote(project_dir)


def run_remote(config: RemoteConfig, remote_command: str, tty: bool = False) -> int:
    """Execute one command on the Raspberry Pi via SSH."""
    wrapped_command = (
        f"cd {quote_remote_project_dir(config.project_dir)} && {remote_command}"
    )
    ssh_command = ["ssh"]
    if tty:
        ssh_command.append("-t")
    ssh_command.extend([config.host, f"bash -lc {shlex.quote(wrapped_command)}"])

    print("")
    print(f"[pi-remote] host={config.host}")
    print(f"[pi-remote] dir={config.project_dir}")
    print(f"[pi-remote] cmd={remote_command}")
    print("")

    completed = subprocess.run(ssh_command, check=False)
    return completed.returncode


def run_local(command: Sequence[str], label: str) -> int:
    """Execute one local command and stream its output."""
    print("")
    print(f"[pi-remote] local={label}")
    print(f"[pi-remote] cmd={shlex.join(command)}")
    print("")

    completed = subprocess.run(list(command), check=False)
    return completed.returncode


def build_status_command() -> str:
    """Create the remote status command."""
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


def build_smoke_command(args: argparse.Namespace) -> str:
    """Create the remote smoke-validation command."""
    parts = ["uv run python scripts/pi_smoke.py"]
    if args.with_mopidy:
        parts.append("--with-mopidy")
    if args.with_voip:
        parts.append("--with-voip")
    if args.verbose:
        parts.append("--verbose")
    if args.mopidy_timeout != 5:
        parts.extend(["--mopidy-timeout", str(args.mopidy_timeout)])
    if args.voip_timeout != 10.0:
        parts.extend(["--voip-timeout", str(args.voip_timeout)])
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
                "scripts/whisplay_tune.py",
            ],
        ),
        (
            "pytest",
            ["uv", "run", "pytest", "-q"],
        ),
    ]


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
    parser = build_parser()
    args = parser.parse_args()

    config = RemoteConfig(
        host=args.host,
        project_dir=args.project_dir,
        branch=args.branch,
    )
    validate_config(config)

    if args.command == "status":
        return run_remote(config, build_status_command())

    if args.command == "sync":
        return run_remote(config, build_sync_command(config, args.skip_uv_sync))

    if args.command == "smoke":
        return run_remote(config, build_smoke_command(args))

    if args.command == "whisplay":
        return run_remote(config, build_whisplay_command(args), tty=True)

    if args.command == "preflight":
        return run_preflight(config, args)

    if args.command == "run":
        return run_remote(config, build_run_command(args), tty=True)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
