"""Tests for Raspberry Pi remote workflow helpers."""

from scripts.pi_remote import (
    RemoteConfig,
    build_local_preflight_commands,
    build_smoke_command,
    build_sync_command,
    build_whisplay_command,
    quote_remote_project_dir,
)
from argparse import Namespace


def test_quote_remote_project_dir_preserves_home_expansion() -> None:
    """Tilde-based project paths should still expand on the remote shell."""
    assert quote_remote_project_dir("~") == '"$HOME"'
    assert quote_remote_project_dir("~/yoyo-py") == '"$HOME/yoyo-py"'


def test_quote_remote_project_dir_quotes_plain_paths() -> None:
    """Non-tilde paths should still be shell-escaped safely."""
    assert quote_remote_project_dir("/home/tifo/yoyo py") == "'/home/tifo/yoyo py'"


def test_build_sync_command_includes_uv_sync_by_default() -> None:
    """Remote sync should refresh dependencies unless explicitly skipped."""
    config = RemoteConfig(
        host="rpi-zero",
        project_dir="~/yoyo-py",
        branch="main",
    )

    assert "uv sync --extra dev" in build_sync_command(config, skip_uv_sync=False)
    assert "uv sync --extra dev" not in build_sync_command(config, skip_uv_sync=True)


def test_build_smoke_command_adds_optional_checks() -> None:
    """Smoke command should include optional service-check flags when requested."""
    args = Namespace(
        with_mopidy=True,
        with_voip=True,
        verbose=True,
        mopidy_timeout=10,
        voip_timeout=15.0,
    )

    command = build_smoke_command(args)

    assert command.startswith("uv run python scripts/pi_smoke.py")
    assert "--with-mopidy" in command
    assert "--with-voip" in command
    assert "--verbose" in command
    assert "--mopidy-timeout 10" in command
    assert "--voip-timeout 15.0" in command


def test_build_local_preflight_commands_cover_compile_and_pytest() -> None:
    """Preflight should run both compileall and pytest locally."""
    commands = build_local_preflight_commands()

    assert commands[0][0] == "compileall"
    assert commands[0][1][1:3] == ["-m", "compileall"]
    assert "scripts/whisplay_tune.py" in commands[0][1]
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
