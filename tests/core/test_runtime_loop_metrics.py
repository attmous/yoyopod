"""Runtime loop metrics integration tests."""

from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core.application import YoyoPodApp


class _ScreenManager:
    def __init__(self, *, refresh_result: bool = True) -> None:
        self.refresh_count = 0
        self.refresh_result = refresh_result
        self.screen_stack: list[object] = []

    def get_current_screen(self) -> object:
        return SimpleNamespace(route_name="hub")

    def refresh_current_screen_for_visible_tick(self) -> bool:
        self.refresh_count += 1
        return self.refresh_result


def test_visible_screen_refresh_records_action_to_visible_latency() -> None:
    app = YoyoPodApp()
    screen_manager = _ScreenManager()
    app.screen_manager = screen_manager
    app.app_state_runtime = SimpleNamespace(get_state_name=lambda: "idle")
    app.call_interruption_policy = SimpleNamespace(music_interrupted_by_call=False)
    app._screen_awake = True
    app.note_input_activity(SimpleNamespace(value="select"), 0, captured_at=100.0)
    app.note_handled_input(action_name="select", handled_at=100.020)

    app.runtime_loop.run_iteration(
        monotonic_now=100.100,
        current_time=200.0,
        last_screen_update=198.0,
        screen_update_interval=1.0,
    )

    snapshot = app.runtime_metrics.responsiveness_snapshot(now=101.0)
    assert screen_manager.refresh_count == 1
    assert snapshot["responsiveness_action_to_visible_count"] == 1
    assert snapshot["responsiveness_last_visible_action_name"] == "select"


def test_visible_screen_refresh_ignores_noop_visible_tick() -> None:
    app = YoyoPodApp()
    screen_manager = _ScreenManager(refresh_result=False)
    app.screen_manager = screen_manager
    app.app_state_runtime = SimpleNamespace(get_state_name=lambda: "idle")
    app.call_interruption_policy = SimpleNamespace(music_interrupted_by_call=False)
    app._screen_awake = True
    app.note_input_activity(SimpleNamespace(value="select"), 0, captured_at=100.0)
    app.note_handled_input(action_name="select", handled_at=100.020)

    app.runtime_loop.run_iteration(
        monotonic_now=100.100,
        current_time=200.0,
        last_screen_update=198.0,
        screen_update_interval=1.0,
    )

    snapshot = app.runtime_metrics.responsiveness_snapshot(now=101.0)
    assert screen_manager.refresh_count == 1
    assert snapshot["responsiveness_action_to_visible_count"] == 0


def test_timing_snapshot_includes_drain_duration() -> None:
    app = YoyoPodApp()
    app.runtime_loop.process_pending_main_thread_actions()

    snapshot = app.runtime_loop.timing_snapshot(now=1.0)

    assert "runtime_main_thread_drain_seconds" in snapshot
    assert snapshot["runtime_main_thread_drain_seconds"] is not None


def test_runtime_status_includes_responsiveness_and_loop_timing() -> None:
    app = YoyoPodApp()
    screen_manager = _ScreenManager()
    app.screen_manager = screen_manager
    app.app_state_runtime = SimpleNamespace(get_state_name=lambda: "idle")
    app.call_interruption_policy = SimpleNamespace(music_interrupted_by_call=False)
    app.runtime_loop.process_pending_main_thread_actions()

    status = app.status_service.get_status()

    assert "responsiveness_input_to_action_count" in status
    assert "responsiveness_action_to_visible_count" in status
    assert "runtime_main_thread_drain_seconds" in status
