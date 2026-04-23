"""Unit tests for SSH transport helpers."""

from __future__ import annotations

import pytest

from yoyopod_cli.remote_shared import RemoteConnection
from yoyopod_cli.remote_transport import (
    build_ssh_command,
    quote_remote_project_dir,
    shell_quote,
    validate_config,
)


def test_shell_quote_escapes() -> None:
    assert shell_quote("foo bar") == "'foo bar'"
    assert shell_quote("clean") == "clean"


def test_quote_remote_project_dir_tilde() -> None:
    assert quote_remote_project_dir("~") == '"$HOME"'
    assert quote_remote_project_dir("~/yoyopod-core") == '"$HOME/yoyopod-core"'


def test_quote_remote_project_dir_absolute() -> None:
    assert quote_remote_project_dir("/opt/yoyopod") == "/opt/yoyopod"


def test_quote_remote_project_dir_escapes_shell_metacharacters() -> None:
    assert quote_remote_project_dir("~/$(id)") == '"$HOME/\\$(id)"'
    assert quote_remote_project_dir("~/`whoami`") == '"$HOME/\\`whoami\\`"'
    assert quote_remote_project_dir('~/with"quote') == '"$HOME/with\\"quote"'


def test_build_ssh_command_without_tty() -> None:
    conn = RemoteConnection(host="rpi-zero", user="pi", project_dir="~/yoyopod-core", branch="main")
    parts = build_ssh_command(conn, "ls")
    assert len(parts) == 3
    assert parts[0] == "ssh"
    assert parts[1] == "pi@rpi-zero"
    assert parts[2].startswith("bash -lc ")
    assert '"$HOME/yoyopod-core"' in parts[2]
    assert "&& ls" in parts[2]


def test_build_ssh_command_with_tty() -> None:
    conn = RemoteConnection(host="rpi-zero", user="", project_dir="~", branch="main")
    parts = build_ssh_command(conn, "htop", tty=True)
    assert len(parts) == 4
    assert parts[0] == "ssh"
    assert parts[1] == "-t"
    assert parts[2] == "rpi-zero"
    assert parts[3].startswith("bash -lc ")


def test_build_ssh_command_without_workdir_skips_cd_wrapper() -> None:
    conn = RemoteConnection(host="rpi-zero", user="pi", project_dir="~/yoyopod-core", branch="main")
    parts = build_ssh_command(conn, "systemctl is-active yoyopod-slot.service", workdir=None)
    assert len(parts) == 3
    assert parts[0] == "ssh"
    assert parts[1] == "pi@rpi-zero"
    assert parts[2].startswith("bash -lc ")
    assert "cd " not in parts[2]
    assert "systemctl is-active yoyopod-slot.service" in parts[2]


def test_validate_config_raises_on_empty_host() -> None:
    conn = RemoteConnection(host="", user="pi", project_dir="~/yoyopod-core", branch="main")
    with pytest.raises(SystemExit, match="Missing Raspberry Pi host"):
        validate_config(conn)


def test_validate_config_accepts_non_empty_host() -> None:
    conn = RemoteConnection(host="rpi-zero", user="pi", project_dir="~/yoyopod-core", branch="main")
    validate_config(conn)
