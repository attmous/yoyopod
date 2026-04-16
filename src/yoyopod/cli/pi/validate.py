"""src/yoyopod/cli/pi/validate.py — focused target-side validation suite."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Annotated

import typer

from yoyopod.audio.test_music import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod.cli.common import REPO_ROOT, configure_logging, resolve_config_dir
from yoyopod.cli.pi.lvgl import soak as run_lvgl_soak
from yoyopod.cli.pi.navigation import run_navigation_soak
from yoyopod.cli.pi.smoke import (
    CheckResult,
    _display_check,
    _environment_check,
    _input_check,
    _load_app_config,
    _load_media_config,
    _music_check,
    _power_check,
    _rtc_check,
    _voip_check,
)
from yoyopod.cli.remote.config import PiDeployConfig, load_pi_deploy_config

validate_app = typer.Typer(
    name="validate",
    help=(
        "Focused target-side validation suite for deploy, smoke, music, voip, "
        "and navigation stability checks."
    ),
    no_args_is_help=True,
)


def _print_summary(name: str, results: list[CheckResult]) -> None:
    """Print a compact summary table for one validation command."""
    print("")
    print(f"YoyoPod target validation summary: {name}")
    print("=" * 48)
    for result in results:
        print(f"[{result.status.upper():4}] {result.name}: {result.details}")


def _resolve_runtime_path(path_value: str) -> Path:
    """Resolve one repo-relative or absolute runtime path."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _nearest_existing_parent(path: Path) -> Path:
    """Return the nearest existing parent for one path."""
    candidate = path if path.exists() and path.is_dir() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _config_files_check(config_path: Path) -> CheckResult:
    """Validate that the tracked runtime config files are present."""
    required_files = (
        config_path / "app" / "core.yaml",
        config_path / "audio" / "music.yaml",
        config_path / "device" / "hardware.yaml",
        config_path / "voice" / "assistant.yaml",
        config_path / "communication" / "calling.yaml",
        config_path / "communication" / "messaging.yaml",
        config_path / "communication" / "integrations" / "liblinphone_factory.conf",
        config_path / "people" / "directory.yaml",
        config_path / "people" / "contacts.seed.yaml",
    )
    missing = [str(path.relative_to(REPO_ROOT)) for path in required_files if not path.exists()]
    if missing:
        return CheckResult(
            name="config",
            status="fail",
            details=f"missing required config files: {', '.join(missing)}",
        )

    return CheckResult(
        name="config",
        status="pass",
        details=", ".join(str(path.relative_to(REPO_ROOT)) for path in required_files),
    )


def _deploy_contract_check() -> tuple[CheckResult, PiDeployConfig | None]:
    """Validate that the tracked deploy contract is readable."""
    try:
        deploy_config = load_pi_deploy_config()
    except Exception as exc:
        return CheckResult(name="deploy_contract", status="fail", details=str(exc)), None

    return (
        CheckResult(
            name="deploy_contract",
            status="pass",
            details=(
                f"project_dir={deploy_config.project_dir}, "
                f"venv={deploy_config.venv}, "
                f"start_cmd={deploy_config.start_cmd}"
            ),
        ),
        deploy_config,
    )


def _runtime_paths_check(deploy_config: PiDeployConfig) -> CheckResult:
    """Validate that runtime file parents are reachable and writable."""
    path_map = {
        "log": _resolve_runtime_path(deploy_config.log_file),
        "error_log": _resolve_runtime_path(deploy_config.error_log_file),
        "pid": _resolve_runtime_path(deploy_config.pid_file),
        "screenshot": _resolve_runtime_path(deploy_config.screenshot_path),
    }

    details: list[str] = []
    failures: list[str] = []
    for name, path in path_map.items():
        parent = _nearest_existing_parent(path)
        writable = os.access(parent, os.W_OK)
        details.append(f"{name}_parent={parent}")
        if not writable:
            failures.append(f"{name}_parent_not_writable={parent}")

    if failures:
        return CheckResult(
            name="runtime_paths",
            status="fail",
            details=", ".join(failures),
        )

    return CheckResult(
        name="runtime_paths",
        status="pass",
        details=", ".join(details),
    )


def _entrypoint_check(deploy_config: PiDeployConfig) -> CheckResult:
    """Validate repo entrypoints and the configured virtualenv activation path."""
    required_paths = {
        "app": REPO_ROOT / "yoyopod.py",
        "systemd": REPO_ROOT / "deploy" / "systemd" / "yoyopod@.service",
    }

    normalized_venv = Path(deploy_config.venv.rstrip("/"))
    if not normalized_venv.is_absolute():
        normalized_venv = REPO_ROOT / normalized_venv
    activate_path = (
        normalized_venv
        if normalized_venv.name == "activate"
        else normalized_venv / "bin" / "activate"
    )
    required_paths["venv_activate"] = activate_path

    missing = [
        f"{name}={path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}"
        for name, path in required_paths.items()
        if not path.exists()
    ]
    if missing:
        return CheckResult(
            name="entrypoints",
            status="fail",
            details=f"missing required paths: {', '.join(missing)}",
        )

    start_parts = shlex.split(deploy_config.start_cmd)
    if not start_parts:
        return CheckResult(
            name="entrypoints",
            status="fail",
            details="start_cmd is empty in deploy/pi-deploy.yaml",
        )

    executable = start_parts[0]
    resolved_executable = shutil.which(executable)
    if resolved_executable is None:
        return CheckResult(
            name="entrypoints",
            status="fail",
            details=f"configured start executable is not on PATH: {executable}",
        )

    return CheckResult(
        name="entrypoints",
        status="pass",
        details=(
            f"start_executable={resolved_executable}, "
            f"venv_activate={activate_path.relative_to(REPO_ROOT) if activate_path.is_relative_to(REPO_ROOT) else activate_path}"
        ),
    )


@validate_app.command()
def deploy(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to validate.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate deploy-readiness for the current target checkout without launching the app."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target deploy validation")

    deploy_result, deploy_config = _deploy_contract_check()
    results = [deploy_result, _config_files_check(config_path)]
    if deploy_config is not None:
        results.append(_runtime_paths_check(deploy_config))
        results.append(_entrypoint_check(deploy_config))

    _print_summary("deploy", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@validate_app.command()
def smoke(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    with_power: Annotated[
        bool, typer.Option("--with-power", help="Also validate PiSugar power telemetry.")
    ] = False,
    with_rtc: Annotated[
        bool, typer.Option("--with-rtc", help="Also validate PiSugar RTC state and alarm.")
    ] = False,
    display_hold_seconds: Annotated[
        float,
        typer.Option(
            "--display-hold-seconds",
            help="How long to keep the display confirmation text visible.",
        ),
    ] = 0.5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate core target hardware paths: environment, display, input, and optional PiSugar state."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target smoke validation")

    app_config = _load_app_config(config_path)
    results: list[CheckResult] = [_environment_check()]
    display = None

    try:
        display_result, display = _display_check(app_config, display_hold_seconds)
        results.append(display_result)

        if display_result.status == "pass" and display is not None:
            results.append(_input_check(display, app_config))

        if with_power:
            results.append(_power_check(config_path))

        if with_rtc:
            results.append(_rtc_check(config_path))
    finally:
        if display is not None:
            try:
                display.cleanup()
            except Exception as exc:
                logger.warning(f"Display cleanup failed: {exc}")

    _print_summary("smoke", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@validate_app.command()
def music(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    timeout: Annotated[
        int, typer.Option("--timeout", help="Startup timeout in seconds for the music backend.")
    ] = 5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate the mpv music backend on the target without starting the full app."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target music validation")

    media_config = _load_media_config(config_path)
    results = [_music_check(media_config, timeout)]

    _print_summary("music", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@validate_app.command()
def voip(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    timeout: Annotated[
        float, typer.Option("--timeout", help="Registration timeout in seconds.")
    ] = 90.0,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate Liblinphone startup and SIP registration on the target."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target VoIP validation")

    results = [_voip_check(config_path, timeout)]

    _print_summary("voip", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)


@validate_app.command()
def stability(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    cycles: Annotated[
        int, typer.Option("--cycles", help="How many full transition cycles to run.")
    ] = 2,
    hold_seconds: Annotated[
        float,
        typer.Option("--hold-seconds", help="How long to keep each screen active during the soak."),
    ] = 0.2,
    idle_seconds: Annotated[
        float,
        typer.Option("--idle-seconds", help="How long to idle after each full navigation cycle."),
    ] = 1.0,
    with_music: Annotated[
        bool,
        typer.Option(
            "--with-music",
            help="Also exercise playlist loading and now-playing actions during the soak.",
        ),
    ] = False,
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed deterministic validation music before playback soak steps.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = DEFAULT_TEST_MUSIC_TARGET_DIR,
    skip_sleep: Annotated[
        bool, typer.Option("--skip-sleep", help="Skip the sleep and wake exercise.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run a repeated navigation and idle stability pass on the target checkout."""
    run_lvgl_soak(
        config_dir=config_dir,
        simulate=False,
        cycles=cycles,
        hold_seconds=hold_seconds,
        idle_seconds=idle_seconds,
        with_music=with_music,
        provision_test_music=provision_test_music,
        test_music_dir=test_music_dir,
        skip_sleep=skip_sleep,
        verbose=verbose,
    )


@validate_app.command()
def navigation(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    cycles: Annotated[
        int, typer.Option("--cycles", help="How many full navigation cycles to run.")
    ] = 2,
    hold_seconds: Annotated[
        float,
        typer.Option(
            "--hold-seconds",
            help="How long to pump after each simulated click or route change.",
        ),
    ] = 0.35,
    idle_seconds: Annotated[
        float,
        typer.Option(
            "--idle-seconds",
            help="How long to leave each exercised screen idle before the next action.",
        ),
    ] = 3.0,
    tail_idle_seconds: Annotated[
        float,
        typer.Option(
            "--tail-idle-seconds",
            help="Final idle dwell on the hub after all navigation cycles complete.",
        ),
    ] = 10.0,
    with_playback: Annotated[
        bool,
        typer.Option(
            "--with-playback/--no-with-playback",
            help="Drive playlist and shuffle playback paths during the soak.",
        ),
    ] = True,
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed deterministic validation music before playback-driven navigation.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = DEFAULT_TEST_MUSIC_TARGET_DIR,
    skip_sleep: Annotated[
        bool, typer.Option("--skip-sleep", help="Skip the final sleep/wake exercise.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run the one-button target navigation and idle stability soak on LVGL hardware."""
    from loguru import logger

    configure_logging(verbose)

    ok, details = run_navigation_soak(
        config_dir=config_dir,
        cycles=cycles,
        hold_seconds=hold_seconds,
        idle_seconds=idle_seconds,
        tail_idle_seconds=tail_idle_seconds,
        with_playback=with_playback,
        provision_test_music=provision_test_music,
        test_music_dir=test_music_dir,
        skip_sleep=skip_sleep,
    )
    if ok:
        logger.info("Navigation soak passed: {}", details)
        return

    logger.error("Navigation soak failed: {}", details)
    raise typer.Exit(code=1)
