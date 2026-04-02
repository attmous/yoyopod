"""Tests for Raspberry Pi remote workflow helpers."""

from scripts.pi_remote import (
    RemoteConfig,
    build_sync_command,
    quote_remote_project_dir,
)


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
