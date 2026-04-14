"""yoyopy/cli/remote/infra.py — infrastructure remote commands: config, service, power."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml

from yoyopy.cli.remote.ops import (
    DEPLOY_CONFIG_PATH,
    LOCAL_DEPLOY_CONFIG_PATH,
    PiDeployConfig,
    _resolve_remote_config,
    build_startup_verification_command,
    load_pi_deploy_config,
    pi_deploy_config_to_dict,
    run_remote,
    shell_quote,
    validate_config,
)


# ---------------------------------------------------------------------------
# Config helpers (inlined from pi_remote.py)
# ---------------------------------------------------------------------------

def build_local_override_template(base_config: PiDeployConfig) -> str:
    """Create the starter template for the gitignored local override file."""
    host = base_config.host or "rpi-zero"
    user = base_config.user or "pi"
    body = yaml.safe_dump(
        {
            "host": host,
            "user": user,
            "project_dir": base_config.project_dir,
            "branch": base_config.branch,
        },
        sort_keys=False,
    ).rstrip()
    return (
        "# Local Raspberry Pi overrides for this workstation.\n"
        "# This file is gitignored. Only machine-specific defaults belong here.\n"
        "# Precedence is: deploy/pi-deploy.yaml -> deploy/pi-deploy.local.yaml -> env -> CLI.\n"
        f"{body}\n"
    )


def ensure_local_pi_deploy_config(
    base_config: PiDeployConfig,
    *,
    local_override_path: Path | None = None,
) -> tuple[Path, bool]:
    """Create the gitignored local override file when it does not exist yet."""
    local_path = local_override_path or LOCAL_DEPLOY_CONFIG_PATH
    if local_path.exists():
        return local_path, False

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(
        build_local_override_template(base_config),
        encoding="utf-8",
    )
    return local_path, True


def build_config_editor_command(
    config_path: Path,
    *,
    editor: str | None = None,
) -> list[str]:
    """Resolve the best local editor command for the override file."""
    configured_editor = editor or os.getenv("VISUAL") or os.getenv("EDITOR")
    if configured_editor:
        return [*shlex.split(configured_editor), str(config_path)]

    if sys.platform.startswith("win"):
        return ["notepad", str(config_path)]

    if sys.platform == "darwin":
        return ["open", "-W", "-t", str(config_path)]

    for candidate in ("sensible-editor", "nano", "vi", "xdg-open"):
        if shutil.which(candidate):
            return [candidate, str(config_path)]

    return ["xdg-open", str(config_path)]


# ---------------------------------------------------------------------------
# Service command builder
# ---------------------------------------------------------------------------

def build_service_command(
    action: str,
    *,
    lines: int = 100,
    deploy_config: PiDeployConfig | None = None,
) -> str:
    """Create the remote systemd service command."""
    deploy = deploy_config or load_pi_deploy_config()
    service_name = 'yoyopod@"$(id -un)".service'
    verify_startup = build_startup_verification_command(deploy)

    if action == "status":
        return f"sudo systemctl status {service_name} --no-pager || true"

    if action == "install":
        return " && ".join(
            [
                "test -f deploy/systemd/yoyopod@.service",
                (
                    "printf 'YOYOPOD_PROJECT_DIR=%s\\n' "
                    f"{shell_quote(deploy.project_dir)} | "
                    "sudo tee /etc/default/yoyopod >/dev/null"
                ),
                "sudo cp deploy/systemd/yoyopod@.service /etc/systemd/system/yoyopod@.service",
                "sudo systemctl daemon-reload",
                f"sudo systemctl enable --now {service_name}",
                verify_startup,
                f"sudo systemctl status {service_name} --no-pager",
            ]
        )

    if action == "start":
        return (
            f"sudo systemctl start {service_name} && "
            f"{verify_startup} && "
            f"sudo systemctl status {service_name} --no-pager"
        )

    if action == "stop":
        return f"sudo systemctl stop {service_name} && sudo systemctl status {service_name} --no-pager || true"

    if action == "restart":
        return (
            f"sudo systemctl restart {service_name} && "
            f"{verify_startup} && "
            f"sudo systemctl status {service_name} --no-pager"
        )

    if action == "logs":
        return f"sudo journalctl -u {service_name} -n {lines} --no-pager"

    raise SystemExit(f"Unsupported service action: {action}")


# ---------------------------------------------------------------------------
# Power command builder
# ---------------------------------------------------------------------------

def build_power_command(*, verbose: bool = False) -> str:
    """Create the remote PiSugar power-status command."""
    parts = ["uv run yoyoctl pi power battery"]
    if verbose:
        parts.append("--verbose")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------

def power(
    host: Annotated[str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")] = "",
    user: Annotated[str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")] = "",
    project_dir: Annotated[str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")] = "",
    branch: Annotated[str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")] = "",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable verbose power helper logging.")] = False,
) -> None:
    """Inspect PiSugar power telemetry remotely."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    rc = run_remote(config, build_power_command(verbose=verbose))
    if rc != 0:
        raise typer.Exit(code=rc)


def config(
    host: Annotated[str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")] = "",
    user: Annotated[str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")] = "",
    project_dir: Annotated[str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")] = "",
    branch: Annotated[str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")] = "",
    action: Annotated[str, typer.Argument(help="Config action to run locally (show, paths, init-local, edit).")] = "show",
    editor: Annotated[Optional[str], typer.Option("--editor", help="Override the editor command for `config edit`.")] = None,
) -> None:
    """Show or edit the merged Raspberry Pi deploy config."""
    deploy_config = load_pi_deploy_config()
    base_path = DEPLOY_CONFIG_PATH
    local_path = LOCAL_DEPLOY_CONFIG_PATH

    if action == "show":
        print(yaml.safe_dump(pi_deploy_config_to_dict(deploy_config), sort_keys=False).rstrip())
        return

    if action == "paths":
        print(f"base: {base_path}")
        print(f"local: {local_path}")
        print(f"local_exists: {'yes' if local_path.exists() else 'no'}")
        return

    ensured_path, created = ensure_local_pi_deploy_config(
        deploy_config,
        local_override_path=local_path,
    )

    if action == "init-local":
        state = "Created" if created else "Already exists"
        print(f"{state}: {ensured_path}")
        return

    if action == "edit":
        command = build_config_editor_command(
            ensured_path,
            editor=editor,
        )
        print("")
        print(f"[pi-remote] local={'config-init' if created else 'config-edit'}")
        print(f"[pi-remote] file={ensured_path}")
        print(f"[pi-remote] cmd={shlex.join(command)}")
        print("")
        rc = subprocess.run(command, check=False).returncode
        if rc != 0:
            raise typer.Exit(code=rc)
        return

    raise SystemExit(f"Unsupported config action: {action}")


def service(
    host: Annotated[str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")] = "",
    user: Annotated[str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")] = "",
    project_dir: Annotated[str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")] = "",
    branch: Annotated[str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")] = "",
    action: Annotated[str, typer.Argument(help="Service action to run remotely (status, install, start, stop, restart, logs).")] = "status",
    lines: Annotated[int, typer.Option("--lines", help="How many journal lines to show for `service logs`.")] = 100,
) -> None:
    """Install or inspect the production YoyoPod systemd service."""
    config_obj = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config_obj)
    deploy_config = load_pi_deploy_config()
    rc = run_remote(
        config_obj,
        build_service_command(action, lines=lines, deploy_config=deploy_config),
    )
    if rc != 0:
        raise typer.Exit(code=rc)
