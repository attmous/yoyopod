"""Tests for Raspberry Pi remote workflow helpers."""

import pytest
import yaml

from yoyopod.cli.remote.ops import (
    DEPLOY_CONFIG_PATH,
    PiDeployConfig,
    RemoteConfig,
    build_archive_sync_extract_command,
    build_deploy_validation_command,
    build_local_preflight_commands,
    build_logs_command,
    build_native_shim_refresh_command,
    build_parser,
    build_restart_command,
    build_rsync_command,
    build_rtc_command,
    build_smoke_command,
    build_startup_verification_command,
    build_status_command,
    build_sync_command,
    build_sync_file_manifest,
    build_validation_inspection_command,
    build_whisplay_command,
    load_pi_deploy_config,
    quote_remote_project_dir,
    resolve_local_executable,
    resolve_local_validation_target,
    run_screenshot,
    should_use_direct_rsync,
    sync_path_is_excluded,
)
from yoyopod.cli.remote.infra import (
    build_config_editor_command,
    build_local_override_template,
    build_power_command,
    build_service_command,
)
from yoyopod.cli.remote.lvgl import build_lvgl_soak_command
from yoyopod.cli.remote.setup import build_setup_command, build_verify_setup_command
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace


def _tracked_project_dir() -> str:
    """Read the repo-owned default project dir from the tracked deploy contract."""

    payload = yaml.safe_load(DEPLOY_CONFIG_PATH.read_text(encoding="utf-8"))
    return str(payload["project_dir"])


DEFAULT_PROJECT_DIR = _tracked_project_dir()

DEPLOY_CONFIG = PiDeployConfig(
    host="rpi-zero",
    user="pi",
    project_dir=DEFAULT_PROJECT_DIR,
    branch="main",
    venv=".venv",
    start_cmd="python yoyopod.py",
    kill_processes=("python", "linphonec"),
    log_file="logs/yoyopod.log",
    error_log_file="logs/yoyopod_errors.log",
    pid_file="/tmp/yoyopod.pid",
    startup_marker="YoyoPod starting",
    screenshot_path="/tmp/yoyopod_screenshot.png",
    rsync_exclude=(".git/", ".cache/", "build/", "logs/"),
)


def test_quote_remote_project_dir_preserves_home_expansion() -> None:
    """Tilde-based project paths should still expand on the remote shell."""
    assert quote_remote_project_dir("~") == '"$HOME"'
    assert quote_remote_project_dir(DEFAULT_PROJECT_DIR) == f'"$HOME/{DEFAULT_PROJECT_DIR[2:]}"'


def test_quote_remote_project_dir_quotes_plain_paths() -> None:
    """Non-tilde paths should still be shell-escaped safely."""
    assert quote_remote_project_dir("/home/tifo/yoyo py") == "'/home/tifo/yoyo py'"


def test_load_pi_deploy_config_merges_local_override(tmp_path) -> None:
    """Machine-local config should override the shared defaults cleanly."""

    base_path = tmp_path / "pi-deploy.yaml"
    local_path = tmp_path / "pi-deploy.local.yaml"
    base_path.write_text(
        "\n".join(
            [
                'host: ""',
                'user: ""',
                f"project_dir: {DEFAULT_PROJECT_DIR}",
                "branch: main",
                "venv: .venv",
                "start_cmd: python yoyopod.py",
                "kill_processes: [python, linphonec]",
                "log_file: logs/yoyopod.log",
                "error_log_file: logs/yoyopod_errors.log",
                "pid_file: /tmp/yoyopod.pid",
                'startup_marker: "YoyoPod starting"',
                "screenshot_path: /tmp/yoyopod_screenshot.png",
                "rsync_exclude: [.git/, .cache/, build/, logs/]",
            ]
        ),
        encoding="utf-8",
    )
    local_path.write_text(
        "\n".join(
            [
                "host: 192.168.1.55",
                "user: pi",
                "project_dir: ~/custom-yoyo",
            ]
        ),
        encoding="utf-8",
    )

    config = load_pi_deploy_config(
        config_path=base_path,
        local_override_path=local_path,
    )

    assert config.host == "192.168.1.55"
    assert config.user == "pi"
    assert config.project_dir == "~/custom-yoyo"
    assert config.branch == "main"


def test_build_local_override_template_targets_machine_specific_fields() -> None:
    """The local override starter should focus on connection defaults."""

    template = build_local_override_template(DEPLOY_CONFIG)

    assert "machine-specific defaults" in template
    assert "host: rpi-zero" in template
    assert "user: pi" in template
    assert f"project_dir: {DEFAULT_PROJECT_DIR}" in template
    assert "branch: main" in template


def test_build_config_editor_command_prefers_explicit_editor(tmp_path) -> None:
    """An explicit editor command should override platform defaults."""

    config_path = tmp_path / "pi-deploy.local.yaml"
    command = build_config_editor_command(config_path, editor="code --wait")

    assert command == ["code", "--wait", str(config_path)]


def test_build_sync_command_includes_uv_sync_by_default() -> None:
    """Remote sync should refresh dependencies unless explicitly skipped."""
    config = RemoteConfig(
        host="rpi-zero",
        user="pi",
        project_dir=DEFAULT_PROJECT_DIR,
        branch="main",
    )

    command_with_uv = build_sync_command(config, skip_uv_sync=False)
    command_without_uv = build_sync_command(config, skip_uv_sync=True)

    assert "git fetch --prune origin" in command_with_uv
    assert "git checkout --force -B main origin/main" in command_with_uv
    assert "git clean -fd" in command_with_uv
    assert "uv sync --extra dev" in command_with_uv
    assert "uv sync --extra dev" not in command_without_uv


def test_build_sync_command_supports_exact_sha_checkout() -> None:
    """Exact-SHA sync should verify ancestry and detach to the requested commit."""

    config = RemoteConfig(
        host="rpi-zero",
        user="pi",
        project_dir=DEFAULT_PROJECT_DIR,
        branch="feature/hardware-validate",
    )

    command = build_sync_command(
        config,
        skip_uv_sync=False,
        target_sha="1234567890abcdef1234567890abcdef12345678",
    )

    assert (
        "git checkout --force -B feature/hardware-validate origin/feature/hardware-validate"
        in command
    )
    assert (
        "git merge-base --is-ancestor 1234567890abcdef1234567890abcdef12345678 "
        "origin/feature/hardware-validate"
    ) in command
    assert "git checkout --force --detach 1234567890abcdef1234567890abcdef12345678" in command


def test_build_rsync_command_uses_excludes_and_remote_target() -> None:
    """Dirty-tree sync should use rsync excludes from the deploy config."""
    config = RemoteConfig(
        host="rpi-zero",
        user="pi",
        project_dir=DEFAULT_PROJECT_DIR,
        branch="main",
    )

    command = build_rsync_command(config, DEPLOY_CONFIG)

    assert command[:3] == ["rsync", "-avz", "--delete"]
    assert command[-2:] == ["./", f"pi@rpi-zero:{DEFAULT_PROJECT_DIR}/"]
    assert "--exclude" in command
    assert ".git/" in command
    assert "logs/" in command


def test_build_rsync_command_supports_custom_executable() -> None:
    """Dirty-tree sync should be able to use an absolute rsync path."""

    config = RemoteConfig(
        host="rpi-zero",
        user="pi",
        project_dir=DEFAULT_PROJECT_DIR,
        branch="main",
    )

    command = build_rsync_command(
        config,
        DEPLOY_CONFIG,
        executable=r"C:\msys64\usr\bin\rsync.exe",
    )

    assert command[0] == r"C:\msys64\usr\bin\rsync.exe"


def test_resolve_local_executable_uses_common_windows_rsync_paths(monkeypatch) -> None:
    """Windows helper should find rsync even when the current PATH has not refreshed yet."""

    monkeypatch.setattr("yoyopod.cli.remote.ops.sys.platform", "win32")
    monkeypatch.setattr("yoyopod.cli.remote.ops.shutil.which", lambda _program: None)
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == r"C:\msys64\usr\bin\rsync.exe")

    assert resolve_local_executable("rsync") == r"C:\msys64\usr\bin\rsync.exe"


def test_should_use_direct_rsync_disables_known_windows_msys_builds(monkeypatch) -> None:
    """Windows should prefer the archive fallback for MSYS/Git rsync builds."""

    monkeypatch.setattr("yoyopod.cli.remote.ops.sys.platform", "win32")
    monkeypatch.delenv("YOYOPOD_PI_FORCE_RSYNC", raising=False)

    assert should_use_direct_rsync(r"C:\msys64\usr\bin\rsync.exe") is False


def test_should_use_direct_rsync_supports_force_override(monkeypatch) -> None:
    """An explicit env override should allow direct rsync for debugging."""

    monkeypatch.setattr("yoyopod.cli.remote.ops.sys.platform", "win32")
    monkeypatch.setenv("YOYOPOD_PI_FORCE_RSYNC", "1")

    assert should_use_direct_rsync(r"C:\msys64\usr\bin\rsync.exe") is True


def test_sync_path_is_excluded_supports_dir_and_glob_patterns() -> None:
    """Fallback sync should match the same directory and file excludes as rsync."""

    patterns = (".git/", "__pycache__/", "*.pyc", "*.egg-info/")

    assert sync_path_is_excluded(".git/config", patterns, is_dir=False) is True
    assert sync_path_is_excluded("pkg/__pycache__", patterns, is_dir=True) is True
    assert sync_path_is_excluded("pkg/module.pyc", patterns, is_dir=False) is True
    assert sync_path_is_excluded("dist/demo.egg-info/PKG-INFO", patterns, is_dir=False) is True
    assert sync_path_is_excluded("src/yoyopod/app.py", patterns, is_dir=False) is False


def test_build_sync_file_manifest_skips_excluded_entries(tmp_path) -> None:
    """Archive fallback should only include files that rsync would have mirrored."""

    deploy_config = PiDeployConfig(
        host="rpi-zero",
        user="pi",
        project_dir=DEFAULT_PROJECT_DIR,
        branch="main",
        venv=".venv",
        start_cmd="python yoyopod.py",
        kill_processes=("python", "linphonec"),
        log_file="logs/yoyopod.log",
        error_log_file="logs/yoyopod_errors.log",
        pid_file="/tmp/yoyopod.pid",
        startup_marker="YoyoPod starting",
        screenshot_path="/tmp/yoyopod_screenshot.png",
        rsync_exclude=(".git/", ".cache/", "__pycache__/", "*.pyc", "build/", "logs/"),
    )

    (tmp_path / "src" / "yoyopod").mkdir(parents=True)
    (tmp_path / "src" / "yoyopod" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "lvgl").mkdir()
    (tmp_path / ".cache" / "lvgl" / "CMakeLists.txt").write_text("cmake\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"pyc")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "yoyopod.log").write_text("runtime\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "native.so").write_bytes(b"binary")

    manifest = build_sync_file_manifest(tmp_path, deploy_config)

    assert manifest == ["src/yoyopod/app.py"]


def test_build_native_shim_refresh_command_covers_both_native_builds() -> None:
    """Restart should be able to rebuild LVGL and Liblinphone when the Pi artifacts are stale."""

    command = build_native_shim_refresh_command(DEPLOY_CONFIG)

    assert "'yoyoctl', 'build', 'lvgl'" in command
    assert "'yoyoctl', 'build', 'liblinphone'" in command
    assert "libyoyopod_lvgl_shim.so" in command
    assert "libyoyopod_liblinphone_shim.so" in command
    assert "[pi-remote] info=rebuilding" in command
    assert command.endswith("} ")


def test_build_archive_sync_extract_command_targets_remote_project_dir() -> None:
    """Fallback sync should unpack into the configured project dir and mirror a manifest."""

    config = RemoteConfig(
        host="rpi-zero",
        user="pi",
        project_dir=DEFAULT_PROJECT_DIR,
        branch="main",
    )

    command = build_archive_sync_extract_command(
        config,
        archive_path="/tmp/yoyopod_sync.tar.gz",
        manifest_path="/tmp/yoyopod_sync_manifest.json",
    )

    assert "python - <<'PY'" in command
    assert f"Path(os.path.expanduser('{DEFAULT_PROJECT_DIR}')).resolve()" in command
    assert "payload = json.load(handle)" in command
    assert "archive.extractall(project_dir)" in command


def test_build_smoke_command_adds_optional_checks() -> None:
    """Smoke command should include optional service-check flags when requested."""
    command = build_smoke_command(
        with_power=True,
        with_rtc=True,
        with_music=True,
        with_voip=True,
        with_lvgl_soak=True,
        verbose=True,
        music_timeout=10,
        voip_timeout=15.0,
    )

    assert command.startswith("uv run yoyoctl pi validate smoke")
    assert "--with-power" in command
    assert "--with-rtc" in command
    assert "uv run yoyoctl pi validate music" in command
    assert "uv run yoyoctl pi validate voip" in command
    assert "uv run yoyoctl pi validate stability" in command
    assert "--verbose" in command
    assert "--timeout 10" in command
    assert "--timeout 15.0" in command


def test_build_deploy_validation_command_targets_pi_suite() -> None:
    """Deploy validation should call the focused target-side suite."""
    command = build_deploy_validation_command(verbose=True)

    assert command == "uv run yoyoctl pi validate deploy --verbose"


def test_build_validation_inspection_command_reports_marker_and_logs() -> None:
    """Post-validate inspection should show the startup marker and recent file logs."""

    command = build_validation_inspection_command(DEPLOY_CONFIG, lines=25)

    assert "== Latest Startup Marker ==" in command
    assert "grep -F 'YoyoPod starting' logs/yoyopod.log | tail -n 1" in command
    assert "== Recent Logs ==" in command
    assert "tail -n 25 logs/yoyopod.log" in command


def test_build_local_preflight_commands_cover_compile_and_pytest() -> None:
    """Preflight should run both compileall and pytest locally."""
    commands = build_local_preflight_commands()

    assert commands[0][0] == "compileall"
    assert commands[0][1][1:3] == ["-m", "compileall"]
    assert "src/yoyopod/cli/pi/smoke.py" in commands[0][1]
    assert "src/yoyopod/cli/pi/validate.py" in commands[0][1]
    assert "src/yoyopod/cli/pi/voip.py" in commands[0][1]
    assert "src/yoyopod/power/backend.py" in commands[0][1]
    assert commands[1] == ("pytest", ["uv", "run", "pytest", "-q"])


def test_build_whisplay_command_adds_timing_overrides() -> None:
    """Whisplay tuning command should forward optional timing overrides."""
    args = Namespace(
        verbose=True,
        no_display=True,
        duration_seconds=45.0,
        debounce_ms=75,
        double_tap_ms=240,
        long_hold_ms=900,
    )

    command = build_whisplay_command(args)

    assert command.startswith("uv run yoyoctl pi tune")
    assert "--verbose" in command
    assert "--no-display" in command
    assert "--duration-seconds 45.0" in command
    assert "--debounce-ms 75" in command
    assert "--double-tap-ms 240" in command
    assert "--long-hold-ms 900" in command


def test_build_rtc_command_supports_status_and_set_alarm() -> None:
    """RTC helper command should support both read-only status and alarm updates."""

    status_args = Namespace(
        verbose=False,
        rtc_action="status",
        time=None,
        repeat_mask=127,
    )
    set_alarm_args = Namespace(
        verbose=True,
        rtc_action="set-alarm",
        time="2026-04-06T07:30:00+02:00",
        repeat_mask=31,
    )

    status_command = build_rtc_command(status_args)
    set_alarm_command = build_rtc_command(set_alarm_args)

    assert status_command == "uv run yoyoctl pi power rtc status"
    assert set_alarm_command.startswith("uv run yoyoctl pi power rtc --verbose set-alarm")
    assert "--time 2026-04-06T07:30:00+02:00" in set_alarm_command
    assert "--repeat-mask 31" in set_alarm_command


def test_build_power_command_supports_verbose_status() -> None:
    """Power helper command should forward the optional verbose flag."""
    command = build_power_command(verbose=True)

    assert command == "uv run yoyoctl pi power battery --verbose"


def test_build_setup_command_supports_feature_flags_and_dry_run() -> None:
    """Remote setup wrapper should invoke the repo-owned Pi bootstrap command."""

    command = build_setup_command(
        with_voice=True,
        with_network=True,
        with_pisugar=True,
        skip_uv_sync=True,
        skip_builds=True,
        dry_run=True,
    )

    assert command.startswith('export PATH="$HOME/.local/bin:$PATH"; uv run yoyoctl setup pi')
    assert "--with-voice" in command
    assert "--with-network" in command
    assert "--with-pisugar" in command
    assert "--skip-uv-sync" in command
    assert "--skip-builds" in command
    assert "--dry-run" in command


def test_build_verify_setup_command_supports_feature_flags() -> None:
    """Remote setup verifier should reuse the repo-owned Pi verification command."""

    command = build_verify_setup_command(
        with_voice=True,
        with_network=False,
        with_pisugar=True,
    )

    assert command.startswith(
        'export PATH="$HOME/.local/bin:$PATH"; uv run yoyoctl setup verify-pi'
    )
    assert "--with-voice" in command
    assert "--with-pisugar" in command
    assert "--with-network" not in command


def test_resolve_local_validation_target_uses_clean_head_and_remote_branch(monkeypatch) -> None:
    """Committed board validation should resolve the current branch and exact pushed HEAD."""

    responses = {
        ("git", "status", "--short"): SimpleNamespace(returncode=0, stdout="", stderr=""),
        ("git", "branch", "--show-current"): SimpleNamespace(
            returncode=0,
            stdout="feature/117\n",
            stderr="",
        ),
        ("git", "ls-remote", "--exit-code", "origin", "refs/heads/feature/117"): SimpleNamespace(
            returncode=0,
            stdout="abc1234567890abc1234567890abc1234567890\trefs/heads/feature/117\n",
            stderr="",
        ),
        ("git", "rev-parse", "HEAD"): SimpleNamespace(
            returncode=0,
            stdout="abc1234567890abc1234567890abc1234567890\n",
            stderr="",
        ),
    }

    def fake_run_local_capture(command):
        return responses[tuple(command)]

    monkeypatch.setattr("yoyopod.cli.remote.ops.run_local_capture", fake_run_local_capture)

    assert resolve_local_validation_target(branch="", sha=None) == (
        "feature/117",
        "abc1234567890abc1234567890abc1234567890",
    )


def test_resolve_local_validation_target_rejects_dirty_worktree(monkeypatch) -> None:
    """Dirty local state should stop the committed validation flow immediately."""

    def fake_run_local_capture(_command):
        return SimpleNamespace(returncode=0, stdout=" M src/yoyopod/app.py\n", stderr="")

    monkeypatch.setattr("yoyopod.cli.remote.ops.run_local_capture", fake_run_local_capture)

    with pytest.raises(SystemExit, match="Commit and push before `yoyoctl remote validate`"):
        resolve_local_validation_target(branch="", sha=None)


def test_build_lvgl_soak_command_supports_cycles_and_sleep_toggle() -> None:
    """LVGL soak helper should forward the relevant duration flags."""

    command = build_lvgl_soak_command(
        verbose=True,
        cycles=3,
        hold_seconds=0.35,
        skip_sleep=True,
    )

    assert command.startswith("uv run yoyoctl pi lvgl soak")
    assert "--verbose" in command
    assert "--cycles 3" in command
    assert "--hold-seconds 0.35" in command
    assert "--skip-sleep" in command


def test_build_status_command_reports_yoyopod_service_and_pisugar_server() -> None:
    """Status output should include the production YoyoPod service and PiSugar daemon."""

    command = build_status_command(DEPLOY_CONFIG)

    assert 'systemctl is-active "yoyopod@$(id -un).service" || true' in command
    assert "systemctl is-active pisugar-server || true" in command
    assert "/tmp/yoyopod.pid" in command
    assert "YoyoPod starting" in command


def test_build_restart_command_reuses_pid_and_startup_contract() -> None:
    """Restart should kill stale processes, relaunch the app, and verify startup."""

    command = build_restart_command(DEPLOY_CONFIG)

    assert "'yoyoctl', 'build', 'lvgl'" in command
    assert "'yoyoctl', 'build', 'liblinphone'" in command
    assert (
        'if systemctl cat yoyopod@"$(id -un)".service >/dev/null 2>&1; then sudo systemctl stop yoyopod@"$(id -un)".service >/dev/null 2>&1 || true;'
        in command
    )
    assert 'sudo systemctl start yoyopod@"$(id -un)".service;' in command
    assert "rm -f /tmp/yoyopod.pid" in command
    assert "killall -9 python" in command
    assert "killall -9 linphonec" in command
    assert (
        'sudo systemctl stop yoyopod@"$(id -un)".service >/dev/null 2>&1 || true; '
        "rm -f /tmp/yoyopod.pid; "
        "killall -9 python >/dev/null 2>&1 || true; "
        "killall -9 linphonec >/dev/null 2>&1 || true; "
        'sudo systemctl start yoyopod@"$(id -un)".service;'
    ) in command
    assert "source .venv/bin/activate && (nohup python yoyopod.py > /dev/null 2>&1 &)" in command
    assert "grep -F 'YoyoPod starting' logs/yoyopod.log" in command


def test_build_parser_describes_current_screenshot_signal_contract() -> None:
    """CLI help should match the screenshot signal mapping used by main.py."""

    parser = build_parser(DEPLOY_CONFIG)
    screenshot_parser = next(
        action for action in parser._actions if getattr(action, "dest", "") == "command"
    ).choices["screenshot"]
    readback_action = next(
        action for action in screenshot_parser._actions if getattr(action, "dest", "") == "readback"
    )

    assert "SIGUSR1" in readback_action.help
    assert "SIGUSR2" in readback_action.help


def test_run_screenshot_uses_sigusr1_for_readback(monkeypatch, tmp_path) -> None:
    """The explicit readback path should target the app's SIGUSR1 handler."""

    recorded_commands: list[str] = []

    def fake_run_remote_capture(_config, command: str):
        recorded_commands.append(command)
        if command.startswith("test -f "):
            return SimpleNamespace(returncode=0, stdout="ALIVE\n", stderr="")
        if command.startswith("kill -"):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="READY\n", stderr="")

    def fake_subprocess_run(command, check=False):
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("yoyopod.cli.remote.ops.run_remote_capture", fake_run_remote_capture)
    monkeypatch.setattr("yoyopod.cli.remote.ops.subprocess.run", fake_subprocess_run)

    args = Namespace(readback=True, output=str(tmp_path / "pi_screenshot.png"))
    exit_code = run_screenshot(
        RemoteConfig(host="rpi-zero", user="pi", project_dir=DEFAULT_PROJECT_DIR, branch="main"),
        DEPLOY_CONFIG,
        args,
    )

    assert exit_code == 0
    assert any(command.startswith("rm -f ") for command in recorded_commands)
    assert any(command.startswith("kill -USR1 ") for command in recorded_commands)
    assert any(command.startswith("for _ in $(seq 1 20); do ") for command in recorded_commands)


def test_run_screenshot_uses_sigusr2_for_default_shadow_path(monkeypatch, tmp_path) -> None:
    """The default CLI path should preserve the legacy shadow-first capture contract."""

    recorded_commands: list[str] = []

    def fake_run_remote_capture(_config, command: str):
        recorded_commands.append(command)
        if command.startswith("test -f "):
            return SimpleNamespace(returncode=0, stdout="ALIVE\n", stderr="")
        if command.startswith("kill -"):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="READY\n", stderr="")

    def fake_subprocess_run(command, check=False):
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("yoyopod.cli.remote.ops.run_remote_capture", fake_run_remote_capture)
    monkeypatch.setattr("yoyopod.cli.remote.ops.subprocess.run", fake_subprocess_run)

    args = Namespace(readback=False, output=str(tmp_path / "pi_screenshot.png"))
    exit_code = run_screenshot(
        RemoteConfig(host="rpi-zero", user="pi", project_dir=DEFAULT_PROJECT_DIR, branch="main"),
        DEPLOY_CONFIG,
        args,
    )

    assert exit_code == 0
    assert any(command.startswith("rm -f ") for command in recorded_commands)
    assert any(command.startswith("kill -USR2 ") for command in recorded_commands)
    assert any(command.startswith("for _ in $(seq 1 20); do ") for command in recorded_commands)


def test_build_service_command_supports_install_and_logs() -> None:
    """Service helper should build install and log commands for the systemd unit."""

    install_command = build_service_command("install", deploy_config=DEPLOY_CONFIG)
    logs_command = build_service_command("logs", lines=25, deploy_config=DEPLOY_CONFIG)

    assert "deploy/systemd/yoyopod@.service" in install_command
    assert "printf 'YOYOPOD_PROJECT_DIR=%s\\n'" in install_command
    assert DEFAULT_PROJECT_DIR in install_command
    assert "/etc/default/yoyopod" in install_command
    assert 'sudo systemctl enable --now yoyopod@"$(id -un)".service' in install_command
    assert "/tmp/yoyopod.pid" in install_command
    assert "YoyoPod starting" in install_command
    assert logs_command == 'sudo journalctl -u yoyopod@"$(id -un)".service -n 25 --no-pager'


def test_build_logs_command_supports_error_filtering_and_follow() -> None:
    """File log tails should support error-only, grep filters, and follow mode."""

    args = Namespace(errors=True, follow=True, filter="voip", lines=50)

    command = build_logs_command(args, DEPLOY_CONFIG)

    assert "tail -n 50 -F logs/yoyopod_errors.log" in command
    assert "grep --line-buffered -i -- voip" in command


def test_build_startup_verification_command_checks_pid_and_marker() -> None:
    """Startup verification should cross-check the PID file against the startup log line."""

    command = build_startup_verification_command(DEPLOY_CONFIG, attempts=3)

    assert "test -f /tmp/yoyopod.pid" in command
    assert 'kill -0 "$pid"' in command
    assert "grep -F 'YoyoPod starting' logs/yoyopod.log" in command
    assert 'grep -F "pid=$pid"' in command
