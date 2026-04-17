"""src/yoyopod/cli/setup.py - repo-owned setup and dependency verification commands."""

from __future__ import annotations

import importlib.util
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from yoyopod.cli.common import REPO_ROOT
from yoyopod.setup_contract import SETUP_TRACKED_CONFIG_FILES

setup_app = typer.Typer(
    name="setup",
    help="Baseline repo-owned host and Raspberry Pi setup commands.",
    no_args_is_help=True,
)

TRACKED_CONFIG_PATHS: tuple[Path, ...] = tuple(
    REPO_ROOT / relative_path for relative_path in SETUP_TRACKED_CONFIG_FILES
)
CORE_PI_PACKAGES: tuple[str, ...] = (
    "mpv",
    "ffmpeg",
    "liblinphone-dev",
    "pkg-config",
    "cmake",
    "alsa-utils",
    "i2c-tools",
)
VOICE_PI_PACKAGES: tuple[str, ...] = ("espeak-ng",)
NETWORK_PI_PACKAGES: tuple[str, ...] = ("ppp",)
PISUGAR_PI_PACKAGES: tuple[str, ...] = ("pisugar-server",)
HOST_REQUIRED_TOOLS: tuple[str, ...] = ("git", "uv")
HOST_REMOTE_TOOLS: tuple[str, ...] = ("ssh", "rsync")
HOST_DEV_MODULES: tuple[str, ...] = ("pytest", "black", "ruff", "mypy", "typer")
NATIVE_ARTIFACTS: tuple[Path, ...] = (
    REPO_ROOT
    / "src"
    / "yoyopod"
    / "ui"
    / "lvgl_binding"
    / "native"
    / "build"
    / "libyoyopod_lvgl_shim.so",
    REPO_ROOT
    / "src"
    / "yoyopod"
    / "communication"
    / "integrations"
    / "liblinphone_binding"
    / "native"
    / "build"
    / "libyoyopod_liblinphone_shim.so",
)


@dataclass(frozen=True)
class SetupCommand:
    """One executable setup step."""

    label: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class SetupCheck:
    """One setup verification result."""

    label: str
    ok: bool
    detail: str


def _run_setup_commands(commands: tuple[SetupCommand, ...], *, dry_run: bool) -> int:
    """Execute one setup plan locally from the repo root."""

    for step in commands:
        print("")
        print(f"[setup] step={step.label}")
        print(f"[setup] cmd={shlex.join(step.command)}")
        if dry_run:
            continue
        completed = subprocess.run(step.command, cwd=REPO_ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def _report_checks(checks: tuple[SetupCheck, ...]) -> int:
    """Print one verification report and return 1 when any check fails."""

    failed = False
    for check in checks:
        status = "ok" if check.ok else "missing"
        print(f"[setup] {status} {check.label}: {check.detail}")
        failed = failed or not check.ok
    return 1 if failed else 0


def _python_version_check() -> SetupCheck:
    required = (3, 12)
    actual = sys.version_info[:3]
    ok = actual >= required
    detail = f"python={actual[0]}.{actual[1]}.{actual[2]} required>={required[0]}.{required[1]}"
    return SetupCheck("python-version", ok, detail)


def _tool_check(program: str) -> SetupCheck:
    resolved = shutil.which(program)
    return SetupCheck(program, resolved is not None, resolved or "not found on PATH")


def _module_check(module_name: str) -> SetupCheck:
    spec = importlib.util.find_spec(module_name)
    return SetupCheck(module_name, spec is not None, "importable" if spec else "not importable")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _file_check(path: Path) -> SetupCheck:
    return SetupCheck(_display_path(path), path.exists(), "present" if path.exists() else "missing")


def _apt_package_check(package: str) -> SetupCheck:
    completed = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", package],
        check=False,
        capture_output=True,
        text=True,
    )
    ok = completed.returncode == 0 and "install ok installed" in completed.stdout
    detail = completed.stdout.strip() or completed.stderr.strip() or "missing"
    return SetupCheck(f"apt:{package}", ok, detail)


def _service_active_check(service_name: str) -> SetupCheck:
    completed = subprocess.run(
        ["systemctl", "is-active", "--quiet", service_name],
        check=False,
    )
    return SetupCheck(
        f"service:{service_name}",
        completed.returncode == 0,
        "active" if completed.returncode == 0 else "inactive",
    )


def pi_package_list(
    *,
    with_voice: bool,
    with_network: bool,
    with_pisugar: bool,
) -> tuple[str, ...]:
    """Return the ordered Raspberry Pi apt package list for the requested features."""

    packages = list(CORE_PI_PACKAGES)
    if with_voice:
        packages.extend(VOICE_PI_PACKAGES)
    if with_network:
        packages.extend(NETWORK_PI_PACKAGES)
    if with_pisugar:
        packages.extend(PISUGAR_PI_PACKAGES)
    return tuple(packages)


def build_host_setup_commands(*, skip_sync: bool = False) -> tuple[SetupCommand, ...]:
    """Build the local developer bootstrap command sequence."""

    if skip_sync:
        return ()
    return (SetupCommand("uv-sync-dev", ("uv", "sync", "--extra", "dev")),)


def build_pi_setup_commands(
    *,
    with_voice: bool,
    with_network: bool,
    with_pisugar: bool,
    skip_uv_sync: bool = False,
    skip_builds: bool = False,
) -> tuple[SetupCommand, ...]:
    """Build the on-device Raspberry Pi bootstrap command sequence."""

    commands: list[SetupCommand] = [
        SetupCommand("apt-update", ("sudo", "apt", "update")),
        SetupCommand(
            "apt-install",
            (
                "sudo",
                "apt",
                "install",
                "-y",
                *pi_package_list(
                    with_voice=with_voice,
                    with_network=with_network,
                    with_pisugar=with_pisugar,
                ),
            ),
        ),
    ]
    if not skip_uv_sync:
        commands.append(SetupCommand("uv-sync-dev", ("uv", "sync", "--extra", "dev")))
    if not skip_builds:
        commands.extend(
            (
                SetupCommand("build-liblinphone", ("uv", "run", "yoyoctl", "build", "liblinphone")),
                SetupCommand("build-lvgl", ("uv", "run", "yoyoctl", "build", "lvgl")),
            )
        )
    return tuple(commands)


def collect_host_setup_checks(
    *,
    with_remote_tools: bool,
    with_github: bool,
) -> tuple[SetupCheck, ...]:
    """Collect local developer-machine verification checks."""

    checks: list[SetupCheck] = [_python_version_check()]
    checks.extend(_tool_check(tool) for tool in HOST_REQUIRED_TOOLS)
    checks.extend(_module_check(module_name) for module_name in HOST_DEV_MODULES)
    checks.extend(_file_check(path) for path in TRACKED_CONFIG_PATHS)
    if with_remote_tools:
        checks.extend(_tool_check(tool) for tool in HOST_REMOTE_TOOLS)
    if with_github:
        checks.append(_tool_check("gh"))
    return tuple(checks)


def collect_pi_setup_checks(
    *,
    with_voice: bool,
    with_network: bool,
    with_pisugar: bool,
) -> tuple[SetupCheck, ...]:
    """Collect Raspberry Pi dependency verification checks."""

    checks: list[SetupCheck] = []
    checks.extend(_file_check(path) for path in TRACKED_CONFIG_PATHS)
    checks.append(_tool_check("uv"))
    checks.extend(
        _apt_package_check(package)
        for package in pi_package_list(
            with_voice=with_voice,
            with_network=with_network,
            with_pisugar=with_pisugar,
        )
    )
    checks.extend(
        SetupCheck(_display_path(path), path.exists(), "built" if path.exists() else "missing")
        for path in NATIVE_ARTIFACTS
    )
    if with_pisugar:
        checks.append(_service_active_check("pisugar-server"))
    return tuple(checks)


@setup_app.command("host")
def host(
    skip_sync: Annotated[
        bool, typer.Option("--skip-sync", help="Skip `uv sync --extra dev`.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the planned commands without executing them.")
    ] = False,
) -> None:
    """Bootstrap the baseline local developer environment from the repo contract."""

    exit_code = _run_setup_commands(build_host_setup_commands(skip_sync=skip_sync), dry_run=dry_run)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@setup_app.command("pi")
def pi(
    with_voice: Annotated[
        bool, typer.Option("--with-voice", help="Install voice-path extras such as espeak-ng.")
    ] = False,
    with_network: Annotated[
        bool, typer.Option("--with-network", help="Install cellular and PPP extras.")
    ] = False,
    with_pisugar: Annotated[
        bool, typer.Option("--with-pisugar", help="Install PiSugar-specific packages.")
    ] = False,
    skip_uv_sync: Annotated[
        bool, typer.Option("--skip-uv-sync", help="Skip `uv sync --extra dev` after apt install.")
    ] = False,
    skip_builds: Annotated[
        bool, typer.Option("--skip-builds", help="Skip the native shim build steps.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the planned commands without executing them.")
    ] = False,
) -> None:
    """Bootstrap a target Raspberry Pi using the baseline repo-owned contract."""

    exit_code = _run_setup_commands(
        build_pi_setup_commands(
            with_voice=with_voice,
            with_network=with_network,
            with_pisugar=with_pisugar,
            skip_uv_sync=skip_uv_sync,
            skip_builds=skip_builds,
        ),
        dry_run=dry_run,
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@setup_app.command("verify-host")
def verify_host(
    with_remote_tools: Annotated[
        bool,
        typer.Option(
            "--with-remote-tools",
            help="Require `ssh` and `rsync` for the Pi workflow.",
        ),
    ] = False,
    with_github: Annotated[
        bool, typer.Option("--with-github", help="Require the `gh` CLI.")
    ] = False,
) -> None:
    """Verify the baseline local developer-machine setup contract."""

    exit_code = _report_checks(
        collect_host_setup_checks(
            with_remote_tools=with_remote_tools,
            with_github=with_github,
        )
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@setup_app.command("verify-pi")
def verify_pi(
    with_voice: Annotated[
        bool, typer.Option("--with-voice", help="Require voice-path extras such as espeak-ng.")
    ] = False,
    with_network: Annotated[
        bool, typer.Option("--with-network", help="Require cellular and PPP extras.")
    ] = False,
    with_pisugar: Annotated[
        bool, typer.Option("--with-pisugar", help="Require PiSugar-specific packages and service.")
    ] = False,
) -> None:
    """Verify baseline Raspberry Pi setup and dependency state."""

    exit_code = _report_checks(
        collect_pi_setup_checks(
            with_voice=with_voice,
            with_network=with_network,
            with_pisugar=with_pisugar,
        )
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)
