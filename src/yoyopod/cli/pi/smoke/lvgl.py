"""LVGL smoke check helpers."""

from __future__ import annotations

from pathlib import Path

from yoyopod.cli.pi.music_fixtures import DEFAULT_TEST_MUSIC_TARGET_DIR

from .types import CheckResult


def _lvgl_soak_check(
    config_dir: Path,
    *,
    with_music: bool = False,
    provision_test_music: bool = True,
    test_music_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR,
) -> CheckResult:
    """Run the target navigation and idle soak on the active LVGL app path."""
    from yoyopod.cli.pi.stability import NavigationSoakError, run_navigation_idle_soak

    try:
        report = run_navigation_idle_soak(
            config_dir=str(config_dir),
            simulate=False,
            cycles=1,
            hold_seconds=0.15,
            idle_seconds=0.5,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_dir=test_music_dir,
        )
    except NavigationSoakError as exc:
        return CheckResult(name="lvgl_soak", status="fail", details=str(exc))

    return CheckResult(
        name="lvgl_soak",
        status="pass",
        details=report.summary(),
    )
