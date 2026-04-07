"""Tests for Raspberry Pi remote workflow helpers."""

from scripts.pi_remote import (
    PiDeployConfig,
    RemoteConfig,
    build_config_editor_command,
    build_local_preflight_commands,
    build_local_override_template,
    build_logs_command,
    build_lvgl_soak_command,
    build_power_command,
    build_restart_command,
    build_rtc_command,
    build_rsync_command,
    build_service_command,
    build_smoke_command,
    build_startup_verification_command,
    build_status_command,
    build_sync_command,
    build_whisplay_command,
    load_pi_deploy_config,
    quote_remote_project_dir,
)
from argparse import Namespace

DEPLOY_CONFIG = PiDeployConfig(
    host="rpi-zero",
    user="pi",
    project_dir="~/yoyo-py",
    branch="main",
    venv=".venv",
    start_cmd="python yoyopod.py",
    kill_processes=("python", "linphonec"),
    log_file="logs/yoyopod.log",
    error_log_file="logs/yoyopod_errors.log",
    pid_file="/tmp/yoyopod.pid",
    startup_marker="YoyoPod starting",
    screenshot_path="/tmp/yoyopod_screenshot.png",
    rsync_exclude=(".git/", "logs/"),
)


def test_quote_remote_project_dir_preserves_home_expansion() -> None:
    """Tilde-based project paths should still expand on the remote shell."""
    assert quote_remote_project_dir("~") == '"$HOME"'
    assert quote_remote_project_dir("~/yoyo-py") == '"$HOME/yoyo-py"'


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
                "user: \"\"",
                "project_dir: ~/yoyo-py",
                "branch: main",
                "venv: .venv",
                "start_cmd: python yoyopod.py",
                "kill_processes: [python, linphonec]",
                "log_file: logs/yoyopod.log",
                "error_log_file: logs/yoyopod_errors.log",
                "pid_file: /tmp/yoyopod.pid",
                'startup_marker: "YoyoPod starting"',
                "screenshot_path: /tmp/yoyopod_screenshot.png",
                "rsync_exclude: [.git/, logs/]",
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
    assert "project_dir: ~/yoyo-py" in template
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
        project_dir="~/yoyo-py",
        branch="main",
    )

    assert "uv sync --extra dev" in build_sync_command(config, skip_uv_sync=False)
    assert "uv sync --extra dev" not in build_sync_command(config, skip_uv_sync=True)


def test_build_rsync_command_uses_excludes_and_remote_target() -> None:
    """Dirty-tree sync should use rsync excludes from the deploy config."""
    config = RemoteConfig(
        host="rpi-zero",
        user="pi",
        project_dir="~/yoyo-py",
        branch="main",
    )

    command = build_rsync_command(config, DEPLOY_CONFIG)

    assert command[:3] == ["rsync", "-avz", "--delete"]
    assert command[-2:] == ["./", "pi@rpi-zero:~/yoyo-py/"]
    assert "--exclude" in command
    assert ".git/" in command
    assert "logs/" in command


def test_build_smoke_command_adds_optional_checks() -> None:
    """Smoke command should include optional service-check flags when requested."""
    args = Namespace(
        with_power=True,
        with_rtc=True,
        with_mopidy=True,
        with_voip=True,
        with_lvgl_soak=True,
        verbose=True,
        mopidy_timeout=10,
        voip_timeout=15.0,
    )

    command = build_smoke_command(args)

    assert command.startswith("uv run python scripts/pi_smoke.py")
    assert "--with-power" in command
    assert "--with-rtc" in command
    assert "--with-mopidy" in command
    assert "--with-voip" in command
    assert "--with-lvgl-soak" in command
    assert "--verbose" in command
    assert "--mopidy-timeout 10" in command
    assert "--voip-timeout 15.0" in command


def test_build_local_preflight_commands_cover_compile_and_pytest() -> None:
    """Preflight should run both compileall and pytest locally."""
    commands = build_local_preflight_commands()

    assert commands[0][0] == "compileall"
    assert commands[0][1][1:3] == ["-m", "compileall"]
    assert "scripts/pisugar_rtc.py" in commands[0][1]
    assert "scripts/pisugar_power.py" in commands[0][1]
    assert "scripts/whisplay_tune.py" in commands[0][1]
    assert "scripts/lvgl_soak.py" in commands[0][1]
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

    assert command.startswith("uv run python scripts/whisplay_tune.py")
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

    assert status_command == "uv run python scripts/pisugar_rtc.py status"
    assert set_alarm_command.startswith("uv run python scripts/pisugar_rtc.py --verbose set-alarm")
    assert "--time 2026-04-06T07:30:00+02:00" in set_alarm_command
    assert "--repeat-mask 31" in set_alarm_command


def test_build_power_command_supports_verbose_status() -> None:
    """Power helper command should forward the optional verbose flag."""
    command = build_power_command(Namespace(verbose=True))

    assert command == "uv run python scripts/pisugar_power.py --verbose"


def test_build_lvgl_soak_command_supports_cycles_and_sleep_toggle() -> None:
    """LVGL soak helper should forward the relevant duration flags."""

    command = build_lvgl_soak_command(
        Namespace(
            verbose=True,
            cycles=3,
            hold_seconds=0.35,
            skip_sleep=True,
        )
    )

    assert command.startswith("uv run python scripts/lvgl_soak.py")
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

    assert "kill -9 $(cat /tmp/yoyopod.pid)" in command
    assert "killall -9 python" in command
    assert "killall -9 linphonec" in command
    assert "source .venv/bin/activate && nohup python yoyopod.py > /dev/null 2>&1 &" in command
    assert "grep -F 'YoyoPod starting' logs/yoyopod.log" in command


def test_build_service_command_supports_install_and_logs() -> None:
    """Service helper should build install and log commands for the systemd unit."""

    install_args = Namespace(service_action="install", lines=100)
    logs_args = Namespace(service_action="logs", lines=25)

    install_command = build_service_command(install_args, DEPLOY_CONFIG)
    logs_command = build_service_command(logs_args, DEPLOY_CONFIG)

    assert "deploy/systemd/yoyopod@.service" in install_command
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
    assert "kill -0 \"$pid\"" in command
    assert "grep -F 'YoyoPod starting' logs/yoyopod.log" in command
    assert "grep -F \"pid=$pid\"" in command
