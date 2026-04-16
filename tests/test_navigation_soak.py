"""Tests for the target navigation and stability soak helpers."""

from pathlib import Path

from yoyopod.cli.pi.stability import NavigationSoakReport, build_navigation_soak_plan
from yoyopod.ui.input import InputAction


def test_build_navigation_soak_plan_without_music_skips_playback_steps() -> None:
    """The base soak should cover navigation without forcing playback actions."""

    plan = build_navigation_soak_plan(with_music=False)

    assert plan[0].kind == "replace"
    assert plan[0].target == "hub"
    assert all(step.wait_for_route != "now_playing" for step in plan)
    assert all(step.action != InputAction.PLAY_PAUSE for step in plan if step.action is not None)
    assert all(step.action != InputAction.NEXT_TRACK for step in plan if step.action is not None)
    assert plan[-1].wait_for_route == "hub"


def test_build_navigation_soak_plan_with_music_adds_now_playing_actions() -> None:
    """Playback-enabled soak should include playlist loading and transport actions."""

    plan = build_navigation_soak_plan(with_music=True)
    wait_routes = [step.wait_for_route for step in plan]
    actions = [step.action for step in plan if step.action is not None]

    assert "now_playing" in wait_routes
    assert InputAction.PLAY_PAUSE in actions
    assert InputAction.NEXT_TRACK in actions
    assert any(step.expect_track_loaded for step in plan)


def test_navigation_soak_report_summary_includes_music_details() -> None:
    """The final summary should expose the key playback and route details."""

    report = NavigationSoakReport(
        cycles=2,
        actions=14,
        transitions=9,
        final_route="hub",
        sleep_details="sleep/wake ok",
        music_enabled=True,
        music_state="playing",
        track_name="Alpha Beacon",
        music_dir=Path("/tmp/yoyopod-music"),
    )

    summary = report.summary()

    assert "cycles=2" in summary
    assert "actions=14" in summary
    assert "final_screen=hub" in summary
    assert "music_state=playing" in summary
    assert "track=Alpha Beacon" in summary
    assert "music_dir=/tmp/yoyopod-music" in summary
