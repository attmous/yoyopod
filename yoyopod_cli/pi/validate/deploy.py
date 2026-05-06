"""Deploy validation subcommand."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Annotated, Any

import typer

from yoyopod_cli.pi.validate._common import (
    _CheckResult,
    _nearest_existing_parent,
    _print_summary,
    _resolve_runtime_path,
)
from yoyopod_cli.common import REPO_ROOT, configure_logging, resolve_config_dir
from yoyopod_cli.paths import load_pi_paths


def _config_files_check(config_path: Path) -> _CheckResult:
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
        return _CheckResult(
            name="config",
            status="fail",
            details=f"missing required config files: {', '.join(missing)}",
        )

    return _CheckResult(
        name="config",
        status="pass",
        details=", ".join(str(path.relative_to(REPO_ROOT)) for path in required_files),
    )


def _deploy_contract_check() -> tuple[_CheckResult, Any | None]:
    """Validate that the tracked deploy contract is readable."""
    try:
        deploy_config = load_pi_paths()
    except Exception as exc:
        return _CheckResult(name="deploy_contract", status="fail", details=str(exc)), None

    return (
        _CheckResult(
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


def _runtime_paths_check(deploy_config: Any) -> _CheckResult:
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
        return _CheckResult(
            name="runtime_paths",
            status="fail",
            details=", ".join(failures),
        )

    return _CheckResult(
        name="runtime_paths",
        status="pass",
        details=", ".join(details),
    )


def _entrypoint_check(deploy_config: Any) -> _CheckResult:
    """Validate repo entrypoints and the configured virtualenv activation path."""
    start_parts = shlex.split(deploy_config.start_cmd)
    if not start_parts:
        return _CheckResult(
            name="entrypoints",
            status="fail",
            details="start_cmd is empty in deploy/pi-deploy.yaml",
        )

    executable = Path(start_parts[0])
    if not executable.is_absolute():
        executable = REPO_ROOT / executable

    required_paths = {
        "runtime": executable,
        "dev_systemd": REPO_ROOT / "deploy" / "systemd" / "yoyopod-dev.service",
        "prod_systemd": REPO_ROOT / "deploy" / "systemd" / "yoyopod-prod.service",
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
        return _CheckResult(
            name="entrypoints",
            status="fail",
            details=f"missing required paths: {', '.join(missing)}",
        )

    resolved_executable = executable if executable.exists() else None
    if resolved_executable is None and not executable.is_absolute():
        which_result = shutil.which(str(executable))
        resolved_executable = Path(which_result) if which_result is not None else None
    if resolved_executable is None:
        return _CheckResult(
            name="entrypoints",
            status="fail",
            details=f"configured start executable is missing: {start_parts[0]}",
        )

    return _CheckResult(
        name="entrypoints",
        status="pass",
        details=(
            f"start_executable={resolved_executable}, "
            f"venv_activate={activate_path.relative_to(REPO_ROOT) if activate_path.is_relative_to(REPO_ROOT) else activate_path}"
        ),
    )


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
