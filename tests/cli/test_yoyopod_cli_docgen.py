"""Tests for yoyopod_cli._docgen."""

from __future__ import annotations

from yoyopod_cli._docgen import generate_commands_md
from yoyopod_cli.main import app


def test_docgen_contains_all_shortcut_commands() -> None:
    md = generate_commands_md(app)
    for cmd in ("deploy", "status", "logs", "restart", "validate"):
        assert f"`yoyopod {cmd}`" in md, f"missing shortcut: {cmd}"


def test_docgen_contains_remote_commands() -> None:
    md = generate_commands_md(app)
    assert "## `yoyopod remote" in md
    for cmd in ("status", "sync", "logs", "config", "power", "rtc", "service"):
        assert cmd in md, f"missing remote command: {cmd}"


def test_docgen_contains_pi_commands() -> None:
    md = generate_commands_md(app)
    assert "## `yoyopod pi" in md
    for cmd in ("validate", "voip", "power", "network"):
        assert cmd in md


def test_docgen_contains_dev_commands() -> None:
    md = generate_commands_md(app)

    assert "## `yoyopod dev`" in md
    assert "`yoyopod dev docs`" in md
    assert "`yoyopod dev profile" not in md


def test_docgen_contains_release_commands() -> None:
    md = generate_commands_md(app)

    assert "## `yoyopod release`" in md
    assert "`yoyopod release current`" in md
    assert "`yoyopod release build`" in md


def test_docgen_contains_voice_commands() -> None:
    md = generate_commands_md(app)

    assert "## `yoyopod voice`" in md
    assert "`yoyopod voice trace last`" in md
    assert "`yoyopod voice dictionary validate`" in md


def test_docgen_does_not_contain_cut_commands() -> None:
    md = generate_commands_md(app)
    for cut in (
        "gallery",
        "tune",
        "whisplay",
        "registration-stability",
        "reconnect-drill",
        "call-soak",
        "navigation-soak",
        "lvgl-soak",
        "provision-test-music",
    ):
        assert cut not in md, f"cut command still present: {cut}"
