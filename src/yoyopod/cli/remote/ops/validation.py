"""Remote validation orchestration for committed code flows."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from importlib import import_module
from typing import Optional, cast

import typer

from yoyopod.cli.remote.config import RemoteConfig, resolve_remote_config
from yoyopod.cli.remote.transport import (
    run_local,
    run_remote,
    validate_config,
)

from .commands import (
    build_deploy_validation_command,
    build_local_preflight_commands,
    build_provision_test_music_command,
    build_restart_command,
    build_smoke_command,
    build_sync_command,
    build_validation_inspection_command,
)

RunLocalCaptureFn = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _resolve_run_local_capture() -> RunLocalCaptureFn:
    """Resolve the package-level local capture helper for legacy monkeypatch seams."""

    ops_module = import_module("yoyopod.cli.remote.ops")
    return cast(RunLocalCaptureFn, ops_module.run_local_capture)


def _resolve_remote_config(
    host: str,
    user: str,
    project_dir: str,
    branch: str,
) -> RemoteConfig:
    """Backward-compatible wrapper for sibling remote CLI modules."""

    return resolve_remote_config(host, user, project_dir, branch)


def _capture_local_git(
    command: Sequence[str],
    *,
    action: str,
    run_local_capture_fn: RunLocalCaptureFn | None = None,
) -> str:
    """Run one local git command and return its trimmed stdout."""
    # Default through the package path so ``yoyopod.cli.remote.ops.run_local_capture``
    # remains the single monkeypatch target for legacy tests and callers.
    completed = (run_local_capture_fn or _resolve_run_local_capture())(command)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "unknown git failure"
        raise SystemExit(f"Failed to {action}: {details}")
    return completed.stdout.strip()


def resolve_local_validation_target(
    *,
    branch: str,
    sha: str | None,
) -> tuple[str, str]:
    """Resolve the branch/SHA pair for committed on-board validation."""
    run_local_capture_fn = _resolve_run_local_capture()
    status_output = _capture_local_git(
        ["git", "status", "--short"],
        action="check the local git status",
        run_local_capture_fn=run_local_capture_fn,
    )
    if status_output:
        raise SystemExit(
            "Local working tree has uncommitted changes. Commit and push before "
            "`yoyoctl remote validate`. Rare-case escape hatch: `yoyoctl remote rsync`."
        )

    current_branch = _capture_local_git(
        ["git", "branch", "--show-current"],
        action="resolve the current branch",
        run_local_capture_fn=run_local_capture_fn,
    )
    resolved_branch = branch.strip() or current_branch
    if not resolved_branch:
        raise SystemExit(
            "Could not resolve a validation branch from the local checkout. "
            "Pass `--branch <name>` when validating from a detached HEAD."
        )

    remote_branch_lookup = run_local_capture_fn(
        ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{resolved_branch}"]
    )
    if remote_branch_lookup.returncode != 0 or not remote_branch_lookup.stdout.strip():
        raise SystemExit(
            f"origin/{resolved_branch} is not pushed yet. Push the branch before board validation."
        )
    remote_branch_head = remote_branch_lookup.stdout.split()[0]

    if sha:
        resolved_sha = _capture_local_git(
            ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
            action=f"resolve commit {sha}",
            run_local_capture_fn=run_local_capture_fn,
        )
    elif current_branch == resolved_branch:
        resolved_sha = _capture_local_git(
            ["git", "rev-parse", "HEAD"],
            action="resolve HEAD",
            run_local_capture_fn=run_local_capture_fn,
        )
    else:
        resolved_sha = remote_branch_head

    if resolved_sha != remote_branch_head:
        raise SystemExit(
            f"origin/{resolved_branch} is at {remote_branch_head[:12]}, but the requested "
            f"validation commit is {resolved_sha[:12]}. Push the branch before board validation."
        )

    return resolved_branch, resolved_sha


def remote_validate(
    host: str = "",
    user: str = "",
    project_dir: str = "",
    branch: str = "",
    sha: Optional[str] = None,
    skip_uv_sync: bool = False,
    with_power: bool = False,
    with_rtc: bool = False,
    with_music: bool = False,
    provision_test_music: bool = True,
    test_music_dir: str = "",
    with_voip: bool = False,
    with_navigation_soak: bool = False,
    with_lvgl_soak: bool = False,
    verbose: bool = False,
    music_timeout: int = 5,
    voip_timeout: float = 90.0,
    lines: int = 20,
) -> None:
    """Validate a committed branch/SHA on the Pi, then leave the app running."""
    from yoyopod.cli.remote.config import load_pi_deploy_config

    resolved_branch, resolved_sha = resolve_local_validation_target(branch=branch, sha=sha)
    config = _resolve_remote_config(host, user, project_dir, resolved_branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    resolved_test_music_dir = test_music_dir or deploy_config.test_music_target_dir

    sync_exit_code = run_remote(
        config,
        build_sync_command(config, skip_uv_sync, target_sha=resolved_sha),
    )
    if sync_exit_code != 0:
        raise typer.Exit(code=sync_exit_code)

    deploy_exit_code = run_remote(
        config,
        build_deploy_validation_command(verbose=verbose),
    )
    if deploy_exit_code != 0:
        raise typer.Exit(code=deploy_exit_code)

    smoke_exit_code = run_remote(
        config,
        build_smoke_command(
            with_power=with_power,
            with_rtc=with_rtc,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_target_dir=(
                resolved_test_music_dir if (with_music or with_navigation_soak) else None
            ),
            with_voip=with_voip,
            with_navigation_soak=with_navigation_soak,
            with_lvgl_soak=with_lvgl_soak,
            verbose=verbose,
            music_timeout=music_timeout,
            voip_timeout=voip_timeout,
        ),
    )
    if smoke_exit_code != 0:
        raise typer.Exit(code=smoke_exit_code)

    restart_exit_code = run_remote(config, build_restart_command(deploy_config))
    if restart_exit_code != 0:
        raise typer.Exit(code=restart_exit_code)

    inspect_exit_code = run_remote(
        config,
        build_validation_inspection_command(deploy_config, lines=lines),
    )
    if inspect_exit_code != 0:
        raise typer.Exit(code=inspect_exit_code)


def remote_smoke(
    host: str = "",
    user: str = "",
    project_dir: str = "",
    branch: str = "",
    with_power: bool = False,
    with_rtc: bool = False,
    with_music: bool = False,
    provision_test_music: bool = True,
    test_music_dir: str = "",
    with_voip: bool = False,
    with_navigation_soak: bool = False,
    with_lvgl_soak: bool = False,
    verbose: bool = False,
    music_timeout: int = 5,
    voip_timeout: float = 90.0,
) -> None:
    """Run the Raspberry Pi smoke validator remotely."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    from yoyopod.cli.remote.config import load_pi_deploy_config

    deploy_config = load_pi_deploy_config()
    resolved_test_music_dir = test_music_dir or deploy_config.test_music_target_dir
    rc = run_remote(
        config,
        build_smoke_command(
            with_power=with_power,
            with_rtc=with_rtc,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_target_dir=(
                resolved_test_music_dir if (with_music or with_navigation_soak) else None
            ),
            with_voip=with_voip,
            with_navigation_soak=with_navigation_soak,
            with_lvgl_soak=with_lvgl_soak,
            verbose=verbose,
            music_timeout=music_timeout,
            voip_timeout=voip_timeout,
        ),
    )
    if rc != 0:
        raise typer.Exit(code=rc)


def remote_provision_test_music(
    host: str = "",
    user: str = "",
    project_dir: str = "",
    branch: str = "",
    target_dir: str = "",
    verbose: bool = False,
) -> None:
    """Provision the deterministic validation music library on the Raspberry Pi."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    from yoyopod.cli.remote.config import load_pi_deploy_config

    deploy_config = load_pi_deploy_config()
    resolved_target_dir = target_dir or deploy_config.test_music_target_dir
    rc = run_remote(
        config,
        build_provision_test_music_command(
            target_dir=resolved_target_dir,
            verbose=verbose,
        ),
    )
    if rc != 0:
        raise typer.Exit(code=rc)


def remote_preflight(
    host: str = "",
    user: str = "",
    project_dir: str = "",
    branch: str = "",
    skip_local: bool = False,
    skip_sync: bool = False,
    skip_uv_sync: bool = False,
    with_power: bool = False,
    with_rtc: bool = False,
    with_music: bool = False,
    provision_test_music: bool = True,
    test_music_dir: str = "",
    with_voip: bool = False,
    with_navigation_soak: bool = False,
    with_lvgl_soak: bool = False,
    verbose: bool = False,
    music_timeout: int = 5,
    voip_timeout: float = 90.0,
) -> None:
    """Run local checks, sync the Pi, and execute the Pi smoke pass."""
    config = _resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    from yoyopod.cli.remote.config import load_pi_deploy_config

    deploy_config = load_pi_deploy_config()
    resolved_test_music_dir = test_music_dir or deploy_config.test_music_target_dir

    if not skip_local:
        for label, command in build_local_preflight_commands():
            exit_code = run_local(command, label)
            if exit_code != 0:
                raise typer.Exit(code=exit_code)

    if not skip_sync:
        exit_code = run_remote(
            config,
            build_sync_command(config, skip_uv_sync),
        )
        if exit_code != 0:
            raise typer.Exit(code=exit_code)

    rc = run_remote(
        config,
        build_smoke_command(
            with_power=with_power,
            with_rtc=with_rtc,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_target_dir=(
                resolved_test_music_dir if (with_music or with_navigation_soak) else None
            ),
            with_voip=with_voip,
            with_navigation_soak=with_navigation_soak,
            with_lvgl_soak=with_lvgl_soak,
            verbose=verbose,
            music_timeout=music_timeout,
            voip_timeout=voip_timeout,
        ),
    )
    if rc != 0:
        raise typer.Exit(code=rc)


__all__ = [
    "_capture_local_git",
    "_resolve_remote_config",
    "remote_preflight",
    "remote_provision_test_music",
    "remote_smoke",
    "remote_validate",
    "resolve_local_validation_target",
]
