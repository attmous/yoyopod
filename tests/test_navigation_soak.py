"""Regression test — navigation-soak is now a flag on remote validate."""
from __future__ import annotations

from yoyopod_cli.remote_validate import _build_validate


def test_with_navigation_flag_appends_navigation_stage() -> None:
    shell = _build_validate(
        branch="main",
        with_music=False,
        with_voip=False,
        with_lvgl_soak=False,
        with_navigation=True,
    )
    assert "yoyopod pi validate navigation" in shell


def test_without_flag_skips_navigation_stage() -> None:
    shell = _build_validate(
        branch="main",
        with_music=False,
        with_voip=False,
        with_lvgl_soak=False,
        with_navigation=False,
    )
    assert "yoyopod pi validate navigation" not in shell
