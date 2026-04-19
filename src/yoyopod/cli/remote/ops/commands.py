"""Command builders for remote operations."""

from __future__ import annotations

import argparse
import shlex
import sys

from yoyopod.cli.remote.config import PiDeployConfig, RemoteConfig, load_pi_deploy_config
from yoyopod.cli.remote.transport import shell_quote


def _activate_script_path(venv: str) -> str:
    """Return the shell path for activating the configured virtualenv."""
    normalized = venv.rstrip("/")
    if normalized.endswith("/bin/activate"):
        return normalized
    return f"{normalized}/bin/activate"


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
        "        Path('src/yoyopod/communication/integrations/liblinphone_binding/native/build/libyoyopod_liblinphone_shim.so'),\n"
        "        [Path('src/yoyopod/communication/integrations/liblinphone_binding/native')],\n"
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
    with_navigation_soak: bool = False,
    with_lvgl_soak: bool = False,
    provision_test_music: bool = True,
    test_music_target_dir: str | None = None,
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
        if not provision_test_music:
            music_command += " --no-provision-test-music"
        elif test_music_target_dir:
            music_command += f" --test-music-dir {shlex.quote(test_music_target_dir)}"
        commands.append(music_command)
    if with_voip:
        voip_command = "uv run yoyoctl pi validate voip"
        if verbose:
            voip_command += " --verbose"
        if voip_timeout != 90.0:
            voip_command += f" --timeout {voip_timeout}"
        commands.append(voip_command)

    if with_navigation_soak:
        navigation_command = "uv run yoyoctl pi validate navigation"
        if verbose:
            navigation_command += " --verbose"
        if not provision_test_music:
            navigation_command += " --no-provision-test-music"
        elif test_music_target_dir:
            navigation_command += f" --test-music-dir {shlex.quote(test_music_target_dir)}"
        commands.append(navigation_command)

    if with_lvgl_soak:
        stability_command = "uv run yoyoctl pi validate stability"
        if with_music:
            stability_command += " --with-music"
            if not provision_test_music:
                stability_command += " --no-provision-test-music"
            elif test_music_target_dir:
                stability_command += f" --test-music-dir {shlex.quote(test_music_target_dir)}"
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


def build_provision_test_music_command(
    *,
    target_dir: str,
    verbose: bool = False,
) -> str:
    """Create the remote command that seeds the deterministic test-music library."""
    parts = [
        "uv run yoyoctl pi music provision-test-library",
        "--target-dir",
        shlex.quote(target_dir),
    ]
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


__all__ = [
    "build_deploy_validation_command",
    "build_logs_command",
    "build_local_preflight_commands",
    "build_native_shim_refresh_command",
    "build_provision_test_music_command",
    "build_restart_command",
    "build_rtc_command",
    "build_smoke_command",
    "build_startup_verification_command",
    "build_status_command",
    "build_sync_command",
    "build_validation_inspection_command",
    "build_whisplay_command",
]
