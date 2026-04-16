"""src/yoyopod/cli/remote/ops.py — operational remote commands: status, sync, smoke, preflight."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Annotated, Optional, Sequence

import typer

from yoyopod.cli.common import REPO_ROOT
from yoyopod.cli.remote.config import (
    DEFAULT_PI_PROJECT_DIR,
    DEPLOY_CONFIG_PATH,
    LOCAL_DEPLOY_CONFIG_PATH,
    PiDeployConfig,
    RemoteConfig,
    load_pi_deploy_config,
    pi_deploy_config_to_dict,
    resolve_remote_config,
)
from yoyopod.cli.remote.transport import (
    quote_remote_project_dir,
    run_local,
    run_local_capture,
    run_remote,
    run_remote_capture,
    shell_quote,
    validate_config,
)

__all__ = [
    "DEFAULT_PI_PROJECT_DIR",
    "DEPLOY_CONFIG_PATH",
    "LOCAL_DEPLOY_CONFIG_PATH",
    "PiDeployConfig",
    "RemoteConfig",
    "_resolve_remote_config",
    "load_pi_deploy_config",
    "pi_deploy_config_to_dict",
    "quote_remote_project_dir",
    "resolve_local_validation_target",
]


def _activate_script_path(venv: str) -> str:
    """Return the shell path for activating the configured virtualenv."""
    normalized = venv.rstrip("/")
    if normalized.endswith("/bin/activate"):
        return normalized
    return f"{normalized}/bin/activate"


def _resolve_remote_config(
    host: str,
    user: str,
    project_dir: str,
    branch: str,
) -> RemoteConfig:
    """Backward-compatible wrapper for sibling remote CLI modules."""

    return resolve_remote_config(host, user, project_dir, branch)


def _capture_local_git(command: Sequence[str], *, action: str) -> str:
    """Run one local git command and return its trimmed stdout."""
    completed = run_local_capture(command)
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
    status_output = _capture_local_git(
        ["git", "status", "--short"],
        action="check the local git status",
    )
    if status_output:
        raise SystemExit(
            "Local working tree has uncommitted changes. Commit and push before "
            "`yoyoctl remote validate`. Rare-case escape hatch: `yoyoctl remote rsync`."
        )

    current_branch = _capture_local_git(
        ["git", "branch", "--show-current"],
        action="resolve the current branch",
    )
    resolved_branch = branch.strip() or current_branch
    if not resolved_branch:
        raise SystemExit(
            "Could not resolve a validation branch from the local checkout. "
            "Pass `--branch <name>` when validating from a detached HEAD."
        )

    remote_branch_lookup = run_local_capture(
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
        )
    elif current_branch == resolved_branch:
        resolved_sha = _capture_local_git(
            ["git", "rev-parse", "HEAD"],
            action="resolve HEAD",
        )
    else:
        resolved_sha = remote_branch_head

    if resolved_sha != remote_branch_head:
        raise SystemExit(
            f"origin/{resolved_branch} is at {remote_branch_head[:12]}, but the requested "
            f"validation commit is {resolved_sha[:12]}. Push the branch before board validation."
        )

    return resolved_branch, resolved_sha


# ---------------------------------------------------------------------------
# Startup verification and native shim helpers
# ---------------------------------------------------------------------------


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
            f"pid=\"$(tr -d '\\n' < {pid_file})\"",
            'test -n "$pid"',
            'kill -0 "$pid"',
            (
                f"for _ in $(seq 1 {attempts}); do "
                f"if test -f {log_file} && "
                f'grep -F {startup_marker} {log_file} | tail -n 1 | grep -F "pid=$pid" >/dev/null; then '
                "break; "
                "fi; "
                "sleep 1; "
                "done"
            ),
            f'grep -F {startup_marker} {log_file} | tail -n 1 | grep -F "pid=$pid"',
        ]
    )


def build_native_shim_refresh_command(deploy_config: PiDeployConfig) -> str:
    """Create the remote command that rebuilds missing or stale native shims."""
    activate_script = shell_quote(_activate_script_path(deploy_config.venv))
    return (
        "{ "
        f"source {activate_script} && python - <<'PY'\n"
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def newest_mtime(paths: list[Path]) -> float:\n"
        "    newest = 0.0\n"
        "    for path in paths:\n"
        "        if not path.exists():\n"
        "            continue\n"
        "        if path.is_dir():\n"
        "            for candidate in path.rglob('*'):\n"
        "                if candidate.is_file():\n"
        "                    newest = max(newest, candidate.stat().st_mtime)\n"
        "            continue\n"
        "        newest = max(newest, path.stat().st_mtime)\n"
        "    return newest\n"
        "\n"
        "\n"
        "def is_stale(binary: Path, sources: list[Path]) -> bool:\n"
        "    if not binary.exists():\n"
        "        return True\n"
        "    return newest_mtime(sources) > binary.stat().st_mtime\n"
        "\n"
        "\n"
        "jobs = [\n"
        "    (\n"
        "        'LVGL',\n"
        "        Path('src/yoyopod/ui/lvgl_binding/native/build/libyoyopod_lvgl_shim.so'),\n"
        "        [Path('src/yoyopod/ui/lvgl_binding/native')],\n"
        "        ['uv', 'run', 'yoyoctl', 'build', 'lvgl'],\n"
        "    ),\n"
        "    (\n"
        "        'Liblinphone',\n"
        "        Path('src/yoyopod/voip/liblinphone_binding/native/build/libyoyopod_liblinphone_shim.so'),\n"
        "        [Path('src/yoyopod/voip/liblinphone_binding/native')],\n"
        "        ['uv', 'run', 'yoyoctl', 'build', 'liblinphone'],\n"
        "    ),\n"
        "]\n"
        "\n"
        "for label, output, sources, command in jobs:\n"
        "    if not is_stale(output, sources):\n"
        "        continue\n"
        "    print(f'[pi-remote] info=rebuilding {label} native shim')\n"
        "    subprocess.run(command, check=True)\n"
        "PY\n"
        "} "
    )


def build_restart_command(deploy_config: PiDeployConfig) -> str:
    """Create the remote restart command for the production app."""
    pid_file = shell_quote(deploy_config.pid_file)
    activate_script = shell_quote(_activate_script_path(deploy_config.venv))
    service_name = 'yoyopod@"$(id -un)".service'

    cleanup_commands = [
        f"rm -f {pid_file}",
    ]
    for process_name in deploy_config.kill_processes:
        cleanup_commands.append(f"killall -9 {shell_quote(process_name)} >/dev/null 2>&1 || true")

    cleanup_sequence = "; ".join(cleanup_commands)
    manual_restart = (
        f"(test -f {pid_file} && kill -9 $(cat {pid_file}) >/dev/null 2>&1) || true; "
        "killall -9 python >/dev/null 2>&1 || true; "
        f"{cleanup_sequence}; "
        f"source {activate_script} && (nohup {deploy_config.start_cmd} > /dev/null 2>&1 &)"
    )
    managed_restart = (
        f"if systemctl cat {service_name} >/dev/null 2>&1; then "
        f"sudo systemctl stop {service_name} >/dev/null 2>&1 || true; "
        f"{cleanup_sequence}; "
        f"sudo systemctl start {service_name}; "
        f"else {manual_restart}; "
        "fi"
    )
    return " && ".join(
        [
            build_native_shim_refresh_command(deploy_config),
            managed_restart,
            build_startup_verification_command(deploy_config),
        ]
    )


def build_validation_inspection_command(
    deploy_config: PiDeployConfig | None = None,
    *,
    lines: int = 20,
) -> str:
    """Inspect the latest startup marker and recent logs after validation."""
    deploy = deploy_config or load_pi_deploy_config()
    log_file = shell_quote(deploy.log_file)
    startup_marker = shell_quote(deploy.startup_marker)
    return " && ".join(
        [
            "echo '== Latest Startup Marker ==' ",
            (
                f"if test -f {log_file}; "
                f"then grep -F {startup_marker} {log_file} | tail -n 1 || true; "
                "else echo 'missing'; fi"
            ),
            "echo",
            "echo '== Recent Logs ==' ",
            (
                f"if test -f {log_file}; "
                f"then tail -n {lines} {log_file}; "
                "else echo 'missing'; fi"
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Rsync / archive sync helpers
# ---------------------------------------------------------------------------


def resolve_local_executable(program: str) -> str | None:
    """Resolve one local executable, including common Windows install paths."""
    resolved = shutil.which(program)
    if resolved:
        return resolved

    if not sys.platform.startswith("win"):
        return None

    candidate_paths: list[Path] = []
    if program.lower() == "rsync":
        candidate_paths.extend(
            [
                Path(r"C:\msys64\usr\bin\rsync.exe"),
                Path(r"C:\Program Files\Git\usr\bin\rsync.exe"),
                Path(r"C:\Program Files\Git\bin\rsync.exe"),
            ]
        )
    elif program.lower() == "scp":
        candidate_paths.extend(
            [
                Path(r"C:\Windows\System32\OpenSSH\scp.exe"),
            ]
        )

    for candidate in candidate_paths:
        if candidate.exists():
            return str(candidate)
    return None


def should_use_direct_rsync(rsync_binary: str | None) -> bool:
    """Return whether the local rsync binary is safe for direct remote sync."""
    if not rsync_binary:
        return False

    force_rsync = os.getenv("YOYOPOD_PI_FORCE_RSYNC", "").strip().lower()
    if force_rsync in {"1", "true", "yes", "on"}:
        return True

    if not sys.platform.startswith("win"):
        return True

    normalized = str(Path(rsync_binary)).replace("/", "\\").lower()
    known_windows_rsyncs = {
        r"c:\msys64\usr\bin\rsync.exe",
        r"c:\program files\git\usr\bin\rsync.exe",
        r"c:\program files\git\bin\rsync.exe",
    }
    return normalized not in known_windows_rsyncs


def sync_path_is_excluded(
    rel_path: str,
    patterns: Sequence[str],
    *,
    is_dir: bool,
) -> bool:
    """Return whether one repo-relative path should be skipped during sync."""
    normalized = rel_path.strip("/")
    if not normalized:
        return False

    segments = normalized.split("/")
    basename = segments[-1]
    for pattern in patterns:
        candidate = str(pattern).strip()
        if not candidate:
            continue

        if candidate.endswith("/"):
            dir_pattern = candidate.rstrip("/")
            if any(fnmatch.fnmatch(segment, dir_pattern) for segment in segments):
                return True
            continue

        if fnmatch.fnmatch(normalized, candidate) or fnmatch.fnmatch(basename, candidate):
            return True

    return False


def build_sync_file_manifest(
    repo_root: Path,
    deploy_config: PiDeployConfig,
) -> list[str]:
    """Collect the repo-relative file list that should be mirrored to the Pi."""
    manifest: list[str] = []
    for current_root, dirnames, filenames in os.walk(repo_root):
        current_root_path = Path(current_root)
        relative_root = current_root_path.relative_to(repo_root)

        kept_dirnames: list[str] = []
        for dirname in sorted(dirnames):
            rel_dir = (relative_root / dirname).as_posix()
            if rel_dir == ".":
                rel_dir = dirname
            if sync_path_is_excluded(rel_dir, deploy_config.rsync_exclude, is_dir=True):
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in sorted(filenames):
            rel_file = (relative_root / filename).as_posix()
            if rel_file == ".":
                rel_file = filename
            if sync_path_is_excluded(rel_file, deploy_config.rsync_exclude, is_dir=False):
                continue
            manifest.append(rel_file)

    return manifest


def build_rsync_command(
    config: RemoteConfig,
    deploy_config: PiDeployConfig,
    *,
    executable: str = "rsync",
) -> list[str]:
    """Create the local rsync command for a dirty-tree sync."""
    command = [executable, "-avz", "--delete"]
    for pattern in deploy_config.rsync_exclude:
        command.extend(["--exclude", pattern])

    remote_dir = config.project_dir.rstrip("/")
    command.extend(["./", f"{config.ssh_target}:{remote_dir}/"])
    return command


def build_archive_sync_extract_command(
    config: RemoteConfig,
    *,
    archive_path: str,
    manifest_path: str,
) -> str:
    """Create the remote command that unpacks and mirrors an scp-uploaded archive."""
    project_dir_literal = repr(config.project_dir)
    archive_path_literal = repr(archive_path)
    manifest_path_literal = repr(manifest_path)
    return f"""python - <<'PY'
import fnmatch
import json
import os
import tarfile
from pathlib import Path


def is_excluded(rel_path: str, patterns: tuple[str, ...]) -> bool:
    normalized = rel_path.strip("/")
    if not normalized:
        return False

    segments = normalized.split("/")
    basename = segments[-1]
    for pattern in patterns:
        candidate = str(pattern).strip()
        if not candidate:
            continue

        if candidate.endswith("/"):
            dir_pattern = candidate.rstrip("/")
            if any(fnmatch.fnmatch(segment, dir_pattern) for segment in segments):
                return True
            continue

        if fnmatch.fnmatch(normalized, candidate) or fnmatch.fnmatch(basename, candidate):
            return True

    return False


project_dir = Path(os.path.expanduser({project_dir_literal})).resolve()
archive_path = Path({archive_path_literal})
manifest_path = Path({manifest_path_literal})

with manifest_path.open("r", encoding="utf-8") as handle:
    payload = json.load(handle)

expected_files = set(payload["files"])
exclude_patterns = tuple(payload["exclude"])
project_dir.mkdir(parents=True, exist_ok=True)

with tarfile.open(archive_path, "r:gz") as archive:
    members = archive.getmembers()
    for member in members:
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise SystemExit(f"Unsafe archive member: {{member.name}}")
    archive.extractall(project_dir)

for path in sorted(project_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
    rel_path = path.relative_to(project_dir).as_posix()
    if is_excluded(rel_path, exclude_patterns):
        continue

    if path.is_file() or path.is_symlink():
        if rel_path not in expected_files:
            path.unlink()
        continue

    try:
        path.rmdir()
    except OSError:
        pass

archive_path.unlink(missing_ok=True)
manifest_path.unlink(missing_ok=True)
PY"""


def run_rsync_deploy(
    config: RemoteConfig,
    deploy_config: PiDeployConfig,
    *,
    skip_restart: bool,
) -> int:
    """Rsync the local working tree to the Pi and optionally restart the app."""
    rsync_binary = resolve_local_executable("rsync")
    if should_use_direct_rsync(rsync_binary):
        if rsync_binary is None:
            raise SystemExit(
                "Direct rsync requested, but the local rsync binary could not be resolved."
            )
        exit_code = run_local(
            build_rsync_command(config, deploy_config, executable=rsync_binary),
            "rsync",
        )
    else:
        scp_binary = resolve_local_executable("scp")
        if not scp_binary:
            raise SystemExit(
                "Neither `rsync` nor `scp` is available locally. "
                "Install one of them or run from a machine with SSH copy tools."
            )

        print("")
        if rsync_binary:
            print(
                "[pi-remote] info=local Windows rsync is not reliable for remote Unix paths; "
                "falling back to archive+scp sync"
            )
        else:
            print("[pi-remote] info=local rsync not found, falling back to archive+scp sync")
        print("")

        manifest = build_sync_file_manifest(REPO_ROOT, deploy_config)
        remote_archive_path = "/tmp/yoyopod_sync.tar.gz"
        remote_manifest_path = "/tmp/yoyopod_sync_manifest.json"

        with tempfile.TemporaryDirectory(prefix="yoyopod-sync-") as temp_dir_raw:
            temp_dir = Path(temp_dir_raw)
            archive_path = temp_dir / "yoyopod_sync.tar.gz"
            manifest_path = temp_dir / "yoyopod_sync_manifest.json"

            with tarfile.open(archive_path, "w:gz") as archive:
                for rel_path in manifest:
                    archive.add(REPO_ROOT / rel_path, arcname=rel_path)

            manifest_payload = {
                "files": manifest,
                "exclude": list(deploy_config.rsync_exclude),
            }
            manifest_path.write_text(
                json.dumps(manifest_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            upload_command = [
                scp_binary,
                str(archive_path),
                str(manifest_path),
                f"{config.ssh_target}:/tmp/",
            ]
            exit_code = run_local(upload_command, "scp-sync-upload")
            if exit_code == 0:
                exit_code = run_remote(
                    config,
                    build_archive_sync_extract_command(
                        config,
                        archive_path=remote_archive_path,
                        manifest_path=remote_manifest_path,
                    ),
                )

    if exit_code != 0 or skip_restart:
        return exit_code

    return run_remote(config, build_restart_command(deploy_config))


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------


def build_status_command(deploy_config: PiDeployConfig | None = None) -> str:
    """Create the remote status command."""
    deploy = deploy_config or load_pi_deploy_config()
    return " && ".join(
        [
            "echo '== Git ==' ",
            'branch="$(git branch --show-current)"',
            'if test -n "$branch"; then echo "$branch"; else echo DETACHED; fi',
            "git rev-parse --short HEAD",
            "git status --short",
            "echo",
            "echo '== Music Backend ==' ",
            "pgrep -af mpv || true",
            "echo",
            "echo '== YoyoPod Service ==' ",
            'systemctl is-active "yoyopod@$(id -un).service" || true',
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


def build_sync_command(
    config: RemoteConfig,
    skip_uv_sync: bool,
    *,
    target_sha: str | None = None,
) -> str:
    """Create the remote committed-code sync command."""
    branch_literal = shlex.quote(config.branch)
    origin_branch_literal = shlex.quote(f"origin/{config.branch}")
    commands = [
        "git fetch --prune origin",
        "git clean -fd",
        f"git checkout --force -B {branch_literal} {origin_branch_literal}",
        "git clean -fd",
    ]
    if target_sha:
        target_sha_literal = shlex.quote(target_sha)
        commands.extend(
            [
                f"git rev-parse --verify {target_sha_literal}^{{commit}} >/dev/null",
                f"git merge-base --is-ancestor {target_sha_literal} {origin_branch_literal}",
                f"git checkout --force --detach {target_sha_literal}",
            ]
        )
    if not skip_uv_sync:
        commands.append("uv sync --extra dev")
    return " && ".join(commands)


def build_smoke_command(
    *,
    with_power: bool = False,
    with_rtc: bool = False,
    with_music: bool = False,
    with_voip: bool = False,
    with_lvgl_soak: bool = False,
    verbose: bool = False,
    music_timeout: int = 5,
    voip_timeout: float = 90.0,
) -> str:
    """Create the remote target-validation command set."""
    commands = ["uv run yoyoctl pi validate smoke"]
    if with_power:
        commands[-1] += " --with-power"
    if with_rtc:
        commands[-1] += " --with-rtc"
    if verbose:
        commands[-1] += " --verbose"

    if with_music:
        music_command = "uv run yoyoctl pi validate music"
        if verbose:
            music_command += " --verbose"
        if music_timeout != 5:
            music_command += f" --timeout {music_timeout}"
        commands.append(music_command)

    if with_voip:
        voip_command = "uv run yoyoctl pi validate voip"
        if verbose:
            voip_command += " --verbose"
        if voip_timeout != 90.0:
            voip_command += f" --timeout {voip_timeout}"
        commands.append(voip_command)

    if with_lvgl_soak:
        stability_command = "uv run yoyoctl pi validate stability"
        if verbose:
            stability_command += " --verbose"
        commands.append(stability_command)

    return " && ".join(commands)


def build_deploy_validation_command(*, verbose: bool = False) -> str:
    """Create the remote deploy-readiness validation command."""
    parts = ["uv run yoyoctl pi validate deploy"]
    if verbose:
        parts.append("--verbose")
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
                "yoyopod",
                "tests",
                "src/yoyopod/cli/pi/smoke.py",
                "src/yoyopod/cli/pi/validate.py",
                "src/yoyopod/cli/pi/voip.py",
                "src/yoyopod/power/backend.py",
                "src/yoyopod/power/manager.py",
                "src/yoyopod/ui/lvgl_binding/__init__.py",
            ],
        ),
        (
            "pytest",
            ["uv", "run", "pytest", "-q"],
        ),
    ]


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


def status(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
) -> None:
    """Show remote repo, music backend, and process status."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    rc = run_remote(config, build_status_command(deploy_config))
    if rc != 0:
        raise typer.Exit(code=rc)


def sync(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    sha: Annotated[
        Optional[str],
        typer.Option(
            "--sha",
            help="Exact commit SHA to check out after syncing the branch onto the Raspberry Pi.",
        ),
    ] = None,
    skip_uv_sync: Annotated[
        bool, typer.Option("--skip-uv-sync", help="Skip `uv sync --extra dev` after pulling.")
    ] = False,
) -> None:
    """Sync the stable Pi checkout to one committed branch or exact commit."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    rc = run_remote(config, build_sync_command(config, skip_uv_sync, target_sha=sha))
    if rc != 0:
        raise typer.Exit(code=rc)


def validate(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str,
        typer.Option(
            "--branch",
            help="Git branch to validate on the Raspberry Pi. Defaults to the current local branch.",
        ),
    ] = "",
    sha: Annotated[
        Optional[str],
        typer.Option(
            "--sha",
            help="Exact commit SHA to validate. Defaults to local HEAD when validating the current branch.",
        ),
    ] = None,
    skip_uv_sync: Annotated[
        bool,
        typer.Option(
            "--skip-uv-sync", help="Skip `uv sync --extra dev` during the remote sync step."
        ),
    ] = False,
    with_power: Annotated[
        bool, typer.Option("--with-power", help="Include PiSugar power checks.")
    ] = False,
    with_rtc: Annotated[
        bool, typer.Option("--with-rtc", help="Include PiSugar RTC checks.")
    ] = False,
    with_music: Annotated[
        bool, typer.Option("--with-music", help="Include music-backend startup checks.")
    ] = False,
    with_voip: Annotated[
        bool, typer.Option("--with-voip", help="Include SIP registration checks.")
    ] = False,
    with_lvgl_soak: Annotated[
        bool,
        typer.Option(
            "--with-lvgl-soak", help="Include a short LVGL transition and sleep/wake soak."
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Enable verbose smoke-script logging.")
    ] = False,
    music_timeout: Annotated[
        int, typer.Option("--music-timeout", help="Music-backend startup timeout in seconds.")
    ] = 5,
    voip_timeout: Annotated[
        float, typer.Option("--voip-timeout", help="VoIP registration timeout in seconds.")
    ] = 90.0,
    lines: Annotated[
        int,
        typer.Option("--lines", help="Number of recent startup log lines to show after launch."),
    ] = 20,
) -> None:
    """Validate a committed branch/SHA on the Pi, then leave the app running."""
    resolved_branch, resolved_sha = resolve_local_validation_target(branch=branch, sha=sha)
    config = resolve_remote_config(host, user, project_dir, resolved_branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()

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
            with_voip=with_voip,
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


def smoke(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    with_power: Annotated[
        bool, typer.Option("--with-power", help="Include PiSugar power checks.")
    ] = False,
    with_rtc: Annotated[
        bool, typer.Option("--with-rtc", help="Include PiSugar RTC checks.")
    ] = False,
    with_music: Annotated[
        bool, typer.Option("--with-music", help="Include music-backend startup checks.")
    ] = False,
    with_voip: Annotated[
        bool, typer.Option("--with-voip", help="Include SIP registration checks.")
    ] = False,
    with_lvgl_soak: Annotated[
        bool,
        typer.Option(
            "--with-lvgl-soak", help="Include a short LVGL transition and sleep/wake soak."
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Enable verbose smoke-script logging.")
    ] = False,
    music_timeout: Annotated[
        int, typer.Option("--music-timeout", help="Music-backend startup timeout in seconds.")
    ] = 5,
    voip_timeout: Annotated[
        float, typer.Option("--voip-timeout", help="VoIP registration timeout in seconds.")
    ] = 90.0,
) -> None:
    """Run the Raspberry Pi smoke validator remotely."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    rc = run_remote(
        config,
        build_smoke_command(
            with_power=with_power,
            with_rtc=with_rtc,
            with_music=with_music,
            with_voip=with_voip,
            with_lvgl_soak=with_lvgl_soak,
            verbose=verbose,
            music_timeout=music_timeout,
            voip_timeout=voip_timeout,
        ),
    )
    if rc != 0:
        raise typer.Exit(code=rc)


def preflight(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    skip_local: Annotated[
        bool,
        typer.Option(
            "--skip-local", help="Skip local compile/test verification before remote work."
        ),
    ] = False,
    skip_sync: Annotated[
        bool, typer.Option("--skip-sync", help="Skip the remote git pull and dependency sync step.")
    ] = False,
    skip_uv_sync: Annotated[
        bool,
        typer.Option(
            "--skip-uv-sync", help="Skip `uv sync --extra dev` during the remote sync step."
        ),
    ] = False,
    with_power: Annotated[
        bool,
        typer.Option("--with-power", help="Include PiSugar power checks in the remote smoke pass."),
    ] = False,
    with_rtc: Annotated[
        bool,
        typer.Option("--with-rtc", help="Include PiSugar RTC checks in the remote smoke pass."),
    ] = False,
    with_music: Annotated[
        bool,
        typer.Option(
            "--with-music", help="Include music-backend startup checks in the remote smoke pass."
        ),
    ] = False,
    with_voip: Annotated[
        bool,
        typer.Option(
            "--with-voip", help="Include SIP registration checks in the remote smoke pass."
        ),
    ] = False,
    with_lvgl_soak: Annotated[
        bool,
        typer.Option(
            "--with-lvgl-soak", help="Include the LVGL soak helper in the remote smoke pass."
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Enable verbose smoke-script logging.")
    ] = False,
    music_timeout: Annotated[
        int, typer.Option("--music-timeout", help="Music-backend startup timeout in seconds.")
    ] = 5,
    voip_timeout: Annotated[
        float, typer.Option("--voip-timeout", help="VoIP registration timeout in seconds.")
    ] = 90.0,
) -> None:
    """Run local checks, sync the Pi, and execute the Pi smoke pass."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)

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
            with_voip=with_voip,
            with_lvgl_soak=with_lvgl_soak,
            verbose=verbose,
            music_timeout=music_timeout,
            voip_timeout=voip_timeout,
        ),
    )
    if rc != 0:
        raise typer.Exit(code=rc)


def restart(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Restart the yoyopod app on the Pi."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    rc = run_remote(config, build_restart_command(deploy_config))
    if rc != 0:
        raise typer.Exit(code=rc)


def logs(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    lines: Annotated[int, typer.Option("--lines", help="Number of log lines to tail.")] = 50,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output.")] = False,
    errors: Annotated[
        bool, typer.Option("--errors", help="Tail the error log instead of the main log.")
    ] = False,
    filter: Annotated[
        Optional[str], typer.Option("--filter", help="Grep filter to apply to log output.")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Tail yoyopod logs on the Pi."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    args = argparse.Namespace(
        errors=errors,
        follow=follow,
        filter=filter,
        lines=lines,
    )
    rc = run_remote(config, build_logs_command(args, deploy_config), tty=follow)
    if rc != 0:
        raise typer.Exit(code=rc)


def screenshot(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    output: Annotated[
        str, typer.Option("--output", help="Local output file path.")
    ] = "screenshot.png",
    readback: Annotated[
        bool,
        typer.Option(
            "--readback", help="Use LVGL readback (SIGUSR1) instead of shadow path (SIGUSR2)."
        ),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Capture a screenshot from the Pi display."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    args = argparse.Namespace(readback=readback, output=output)
    rc = run_screenshot(config, deploy_config, args)
    if rc != 0:
        raise typer.Exit(code=rc)


def rsync(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    skip_restart: Annotated[
        bool, typer.Option("--skip-restart", help="Skip restart after sync.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Rare-case escape hatch: mirror the local dirty working tree to the Pi."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    deploy_config = load_pi_deploy_config()
    print(
        "[pi-remote] warning=dirty-tree rsync is a debugging escape hatch; prefer `yoyoctl remote validate` for committed branch/SHA validation"
    )
    rc = run_rsync_deploy(config, deploy_config, skip_restart=skip_restart)
    if rc != 0:
        raise typer.Exit(code=rc)


def whisplay(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    duration_seconds: Annotated[
        float, typer.Option("--duration-seconds", help="Session duration in seconds.")
    ] = 30.0,
    debounce_ms: Annotated[
        Optional[int], typer.Option("--debounce-ms", help="Debounce threshold in ms.")
    ] = None,
    double_tap_ms: Annotated[
        Optional[int], typer.Option("--double-tap-ms", help="Double-tap window in ms.")
    ] = None,
    long_hold_ms: Annotated[
        Optional[int], typer.Option("--long-hold-ms", help="Long-hold threshold in ms.")
    ] = None,
    no_display: Annotated[
        bool, typer.Option("--no-display", help="Disable display rendering.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Run the Whisplay gesture-tuning helper remotely."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    args = argparse.Namespace(
        verbose=verbose,
        no_display=no_display,
        duration_seconds=duration_seconds,
        debounce_ms=debounce_ms,
        double_tap_ms=double_tap_ms,
        long_hold_ms=long_hold_ms,
    )
    rc = run_remote(config, build_whisplay_command(args), tty=True)
    if rc != 0:
        raise typer.Exit(code=rc)


def rtc(
    host: Annotated[
        str, typer.Option("--host", help="SSH host or alias for the Raspberry Pi.")
    ] = "",
    user: Annotated[
        str, typer.Option("--user", help="SSH user for the Raspberry Pi (optional).")
    ] = "",
    project_dir: Annotated[
        str, typer.Option("--project-dir", help="Project directory on the Raspberry Pi.")
    ] = "",
    branch: Annotated[
        str, typer.Option("--branch", help="Git branch to sync on the Raspberry Pi.")
    ] = "",
    action: Annotated[
        str,
        typer.Argument(help="RTC action: status, sync-to, sync-from, set-alarm, disable-alarm."),
    ] = "status",
    time: Annotated[
        Optional[str], typer.Option("--time", help="Alarm time in ISO 8601 format (for set-alarm).")
    ] = None,
    repeat_mask: Annotated[
        int, typer.Option("--repeat-mask", help="Repeat bitmask (default: every day).")
    ] = 127,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable debug logging.")] = False,
) -> None:
    """Inspect or control PiSugar RTC state remotely."""
    config = resolve_remote_config(host, user, project_dir, branch)
    validate_config(config)
    args = argparse.Namespace(
        verbose=verbose,
        rtc_action=action,
        time=time,
        repeat_mask=repeat_mask,
    )
    rc = run_remote(config, build_rtc_command(args))
    if rc != 0:
        raise typer.Exit(code=rc)


# ---------------------------------------------------------------------------
# Compat builder functions (argparse.Namespace-based, used by tests and legacy
# callers; these mirror the old scripts/pi_remote.py builder API)
# ---------------------------------------------------------------------------


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


def build_whisplay_command(args: argparse.Namespace) -> str:
    """Create the remote Whisplay tuning command."""
    parts = ["uv run yoyoctl pi tune"]
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
    parts = ["uv run yoyoctl pi power rtc"]
    if args.verbose:
        parts.append("--verbose")
    parts.append(args.rtc_action)
    if args.rtc_action == "set-alarm":
        if not args.time:
            raise SystemExit("--time is required for `rtc set-alarm`")
        parts.extend(["--time", shlex.quote(args.time)])
        if args.repeat_mask != 127:
            parts.extend(["--repeat-mask", str(args.repeat_mask)])
    return " ".join(parts)


def build_parser(deploy_config: PiDeployConfig) -> argparse.ArgumentParser:
    """Create the legacy argparse command-line parser (mirrors old scripts/pi_remote.py)."""
    parser = argparse.ArgumentParser(
        description=(
            "Run common YoyoPod Raspberry Pi development tasks over SSH. "
            "Defaults can be provided with YOYOPOD_PI_HOST, "
            "YOYOPOD_PI_USER, YOYOPOD_PI_PROJECT_DIR, and YOYOPOD_PI_BRANCH, "
            "or through deploy/pi-deploy.yaml plus the optional "
            "deploy/pi-deploy.local.yaml override."
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
        help=f"Project directory on the Raspberry Pi (default: {DEFAULT_PI_PROJECT_DIR})",
    )
    parser.add_argument(
        "--branch",
        default=os.getenv("YOYOPOD_PI_BRANCH", deploy_config.branch),
        help="Git branch to sync on the Raspberry Pi (default: main)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser(
        "config",
        help="Show or edit the merged Raspberry Pi deploy config",
    )
    config_parser.add_argument(
        "config_action",
        nargs="?",
        default="show",
        choices=["show", "paths", "init-local", "edit"],
        help="Config action to run locally (default: show)",
    )
    config_parser.add_argument(
        "--editor",
        help="Override the editor command for `config edit`",
    )

    subparsers.add_parser(
        "status",
        help="Show remote repo, music backend, and process status",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync the stable Pi checkout to one committed branch or exact commit",
    )
    sync_parser.add_argument(
        "--sha",
        help="Exact commit SHA to check out after syncing the branch",
    )
    sync_parser.add_argument(
        "--skip-uv-sync",
        action="store_true",
        help="Skip `uv sync --extra dev` after syncing the requested revision",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate one committed branch/SHA on the Pi and leave the app running",
    )
    validate_parser.add_argument(
        "--sha",
        help="Exact commit SHA to validate (defaults to local HEAD for the current branch)",
    )
    validate_parser.add_argument("--skip-uv-sync", action="store_true")
    validate_parser.add_argument("--with-power", action="store_true")
    validate_parser.add_argument("--with-rtc", action="store_true")
    validate_parser.add_argument("--with-music", action="store_true")
    validate_parser.add_argument("--with-voip", action="store_true")
    validate_parser.add_argument("--with-lvgl-soak", action="store_true")
    validate_parser.add_argument("--verbose", action="store_true")
    validate_parser.add_argument("--music-timeout", type=int, default=5)
    validate_parser.add_argument("--voip-timeout", type=float, default=90.0)
    validate_parser.add_argument("--lines", type=int, default=20)

    screenshot_parser = subparsers.add_parser(
        "screenshot",
        help="Capture a screenshot from the running app on the Raspberry Pi",
    )
    screenshot_parser.add_argument(
        "--readback",
        action="store_true",
        help=(
            "Use LVGL readback/default capture (SIGUSR1) instead of the "
            "legacy shadow-first path (SIGUSR2)"
        ),
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
    smoke_parser.add_argument("--with-power", action="store_true")
    smoke_parser.add_argument("--with-rtc", action="store_true")
    smoke_parser.add_argument("--with-music", action="store_true")
    smoke_parser.add_argument("--with-voip", action="store_true")
    smoke_parser.add_argument("--with-lvgl-soak", action="store_true")
    smoke_parser.add_argument("--verbose", action="store_true")
    smoke_parser.add_argument("--music-timeout", type=int, default=5)
    smoke_parser.add_argument("--voip-timeout", type=float, default=10.0)

    whisplay_parser = subparsers.add_parser(
        "whisplay",
        help="Run the Whisplay gesture-tuning helper remotely",
    )
    whisplay_parser.add_argument("--verbose", action="store_true")
    whisplay_parser.add_argument("--duration-seconds", type=float, default=30.0)
    whisplay_parser.add_argument("--debounce-ms", type=int)
    whisplay_parser.add_argument("--double-tap-ms", type=int)
    whisplay_parser.add_argument("--long-hold-ms", type=int)
    whisplay_parser.add_argument("--no-display", action="store_true")

    lvgl_soak_parser = subparsers.add_parser(
        "lvgl-soak",
        help="Run the LVGL Whisplay soak helper remotely",
    )
    lvgl_soak_parser.add_argument("--cycles", type=int, default=2)
    lvgl_soak_parser.add_argument("--hold-seconds", type=float, default=0.2)
    lvgl_soak_parser.add_argument("--skip-sleep", action="store_true")
    lvgl_soak_parser.add_argument("--verbose", action="store_true")

    rtc_parser = subparsers.add_parser(
        "rtc",
        help="Inspect or control PiSugar RTC state remotely",
    )
    rtc_parser.add_argument(
        "rtc_action",
        nargs="?",
        default="status",
        choices=["status", "sync-to", "sync-from", "set-alarm", "disable-alarm"],
    )
    rtc_parser.add_argument("--time")
    rtc_parser.add_argument("--repeat-mask", type=int, default=127)
    rtc_parser.add_argument("--verbose", action="store_true")

    power_parser = subparsers.add_parser(
        "power",
        help="Inspect PiSugar power telemetry remotely",
    )
    power_parser.add_argument("--verbose", action="store_true")

    logs_parser = subparsers.add_parser(
        "logs",
        help="Tail the file-based YoyoPod logs on the Raspberry Pi",
    )
    logs_parser.add_argument("--errors", action="store_true")
    logs_parser.add_argument("--follow", action="store_true")
    logs_parser.add_argument("--filter")
    logs_parser.add_argument("--lines", type=int, default=100)

    service_parser = subparsers.add_parser(
        "service",
        help="Install or inspect the production YoyoPod systemd service",
    )
    service_parser.add_argument(
        "service_action",
        nargs="?",
        default="status",
        choices=["status", "install", "start", "stop", "restart", "logs"],
    )
    service_parser.add_argument("--lines", type=int, default=100)

    rsync_parser = subparsers.add_parser(
        "rsync",
        help="Rare-case escape hatch: mirror the local dirty working tree to the Pi",
    )
    rsync_parser.add_argument("--skip-restart", action="store_true")

    return parser


def run_screenshot(
    config: RemoteConfig,
    deploy_config: PiDeployConfig,
    args: argparse.Namespace,
) -> int:
    """Capture a screenshot from the remote app and copy it locally."""
    wait_seconds = 20
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

    clear_result = run_remote_capture(
        config,
        f"rm -f {screenshot_path}",
    )
    if clear_result.returncode != 0:
        print("Failed to clear the previous screenshot on the Raspberry Pi.")
        if clear_result.stderr.strip():
            print(clear_result.stderr.strip())
        return clear_result.returncode

    signal_name = "USR1" if args.readback else "USR2"
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
        (
            f"for _ in $(seq 1 {wait_seconds}); do "
            f"test -f {screenshot_path} && echo READY && exit 0; "
            "sleep 1; "
            "done; "
            "echo MISSING"
        ),
    )
    if verify_result.returncode != 0 or verify_result.stdout.strip() != "READY":
        print(
            "Screenshot was not created on the Raspberry Pi. "
            "Confirm the app is running and screenshot handlers are installed. "
            "If the app is wedged, inspect `yoyoctl remote logs --errors` for the "
            "traceback dump and runtime snapshot triggered by the screenshot signal."
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
    print("[pi-remote] local=screenshot-copy")
    print(f"[pi-remote] cmd={shlex.join(scp_command)}")
    print("")
    copy_result = subprocess.run(scp_command, check=False)
    if copy_result.returncode == 0:
        print(f"Saved screenshot to {output_path}")
    return copy_result.returncode
