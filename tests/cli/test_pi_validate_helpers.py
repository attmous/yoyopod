from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from yoyopod_cli import _pi_validate_helpers as helpers
from yoyopod_cli import pi_validate_helpers as public_helpers


def test_wait_for_route_accepts_transition_completed_in_final_pump(
    monkeypatch,
) -> None:
    state = {"now": 0.0, "route": "hub"}

    def fake_monotonic() -> float:
        return float(state["now"])

    def fake_current_route(_app: object) -> str:
        return str(state["route"])

    def fake_pump_app(_app: object, duration_seconds: float) -> None:
        assert duration_seconds == 0.05
        state["route"] = "ask"
        state["now"] = 1.2

    monkeypatch.setattr(helpers.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(helpers, "_current_route", fake_current_route)
    monkeypatch.setattr(helpers, "_pump_app", fake_pump_app)

    helpers._wait_for_route(object(), "ask", timeout_seconds=1.0)


def test_default_app_factory_wraps_imported_app_with_stable_soak_surface(
    monkeypatch,
) -> None:
    class _FakeApp:
        def __init__(self, *, config_dir: str, simulate: bool) -> None:
            self.config_dir = config_dir
            self.simulate = simulate
            self.display = SimpleNamespace(backend_kind="lvgl")
            self.screen_manager = None
            self.input_manager = None
            self.local_music_service = None
            self.music_backend = None
            self.runtime_loop = SimpleNamespace(configured_voip_iterate_interval_seconds=0.25)
            self.recovery_service = None
            self.power_runtime = None
            self.screen_power_service = None
            self.event_bus = None
            self.context = None
            self._screen_timeout_seconds = 12.5
            self._shutdown_completed = True
            self._last_user_activity_at = 0.0

        def setup(self) -> bool:
            return True

        def stop(self) -> None:
            return None

    fake_app_module = ModuleType("yoyopod.app")
    fake_app_module.YoyoPodApp = _FakeApp
    monkeypatch.setitem(sys.modules, "yoyopod.app", fake_app_module)
    monkeypatch.setattr(helpers.time, "monotonic", lambda: 100.0)

    handle = helpers._default_app_factory(config_dir="test-config", simulate=True)
    wrapped_app = getattr(handle, "_app")

    assert handle.config_dir == "test-config"
    assert handle.simulate is True
    assert handle.voip_iterate_interval_seconds == 0.25
    assert handle.screen_timeout_seconds == 12.5
    assert handle.shutdown_completed is True

    handle.simulate_inactivity(idle_for_seconds=7.0)

    assert wrapped_app._last_user_activity_at == 93.0


def test_public_pi_validate_helpers_alias_reexports_internal_helpers() -> None:
    assert public_helpers.run_navigation_soak is helpers.run_navigation_soak
    assert public_helpers.run_navigation_idle_soak is helpers.run_navigation_idle_soak


def test_pump_app_polls_worker_supervisor(monkeypatch) -> None:
    calls: list[str] = []
    monotonic_values = iter([0.0, 0.0, 0.01, 0.2])

    app = SimpleNamespace(
        runtime_loop=SimpleNamespace(
            process_pending_main_thread_actions=lambda: calls.append("main"),
            pump_lvgl_backend=lambda now: calls.append(f"lvgl:{now}"),
        ),
        worker_supervisor=SimpleNamespace(poll=lambda: calls.append("worker")),
        recovery_service=SimpleNamespace(attempt_manager_recovery=lambda: calls.append("recovery")),
        power_runtime=SimpleNamespace(
            poll_status=lambda *, now: calls.append(f"power:{now}"),
            feed_watchdog_if_due=lambda now: calls.append(f"watchdog:{now}"),
        ),
        screen_power_service=SimpleNamespace(
            update_screen_power=lambda now: calls.append(f"screen:{now}"),
        ),
    )

    monkeypatch.setattr(helpers.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(helpers.time, "sleep", lambda _seconds: None)

    helpers._pump_app(app, 0.1)

    assert calls == [
        "main",
        "worker",
        "recovery",
        "power:0.01",
        "lvgl:0.01",
        "watchdog:0.01",
        "screen:0.01",
    ]


def test_navigation_idle_soak_resets_hub_selection_between_cycles(
    monkeypatch,
) -> None:
    class _FakeScreen:
        def __init__(self, route_name: str, *, selected_index: int = 0) -> None:
            self.route_name = route_name
            self.name = route_name
            self.selected_index = selected_index

    class _FakeScreenManager:
        def __init__(self) -> None:
            self.hub = _FakeScreen("hub")
            self.listen = _FakeScreen("listen")
            self.power = _FakeScreen("power")
            self.current_screen = self.hub

        def replace_screen(self, screen_name: str) -> None:
            self.current_screen = getattr(self, screen_name)

    class _FakeApp:
        def __init__(self, *, config_dir: str, simulate: bool) -> None:
            self.config_dir = config_dir
            self.simulate = simulate
            self.display = SimpleNamespace(backend_kind="lvgl")
            self.screen_manager = _FakeScreenManager()
            self.local_music_service = None
            self.music_backend = None

        def setup(self) -> bool:
            return True

        def stop(self) -> None:
            return None

    fake_app_module = ModuleType("yoyopod.app")
    fake_app_module.YoyoPodApp = _FakeApp
    monkeypatch.setitem(sys.modules, "yoyopod.app", fake_app_module)
    monkeypatch.setattr(helpers, "_pump_app", lambda app, duration_seconds: None)
    monkeypatch.setattr(
        helpers,
        "build_navigation_soak_plan",
        lambda *, with_music: (
            helpers.NavigationSoakStep("replace", "Reset to the root hub", target="hub"),
            helpers.NavigationSoakStep(
                "action",
                "Open Listen from the hub",
                action=helpers.InputAction.SELECT,
                wait_for_route="listen",
            ),
            helpers.NavigationSoakStep(
                "action",
                "Return to the hub",
                action=helpers.InputAction.BACK,
                wait_for_route="hub",
            ),
        ),
    )

    def fake_dispatch_action(app: _FakeApp, action: helpers.InputAction) -> None:
        if action == helpers.InputAction.SELECT:
            app.screen_manager.current_screen = (
                app.screen_manager.listen
                if app.screen_manager.hub.selected_index == 0
                else app.screen_manager.power
            )
            return

        if action == helpers.InputAction.BACK:
            app.screen_manager.hub.selected_index = 3
            app.screen_manager.current_screen = app.screen_manager.hub
            return

        raise AssertionError(f"unexpected action: {action}")

    monkeypatch.setattr(helpers, "_dispatch_action", fake_dispatch_action)

    report = helpers.run_navigation_idle_soak(
        cycles=2,
        hold_seconds=0.1,
        idle_seconds=0.0,
        skip_sleep=True,
    )

    assert report.final_route == "hub"


def test_navigation_idle_soak_resets_reopened_listen_selection(
    monkeypatch,
) -> None:
    class _FakeScreen:
        def __init__(self, route_name: str, *, selected_index: int = 0) -> None:
            self.route_name = route_name
            self.name = route_name
            self.selected_index = selected_index

    class _FakeScreenManager:
        def __init__(self) -> None:
            self.hub = _FakeScreen("hub")
            self.listen = _FakeScreen("listen")
            self.playlists = _FakeScreen("playlists")
            self.recent_tracks = _FakeScreen("recent_tracks")
            self.current_screen = self.hub

        def replace_screen(self, screen_name: str) -> None:
            self.current_screen = getattr(self, screen_name)

    class _FakeApp:
        def __init__(self, *, config_dir: str, simulate: bool) -> None:
            self.config_dir = config_dir
            self.simulate = simulate
            self.display = SimpleNamespace(backend_kind="lvgl")
            self.screen_manager = _FakeScreenManager()
            self.local_music_service = None
            self.music_backend = None

        def setup(self) -> bool:
            return True

        def stop(self) -> None:
            return None

    fake_app_module = ModuleType("yoyopod.app")
    fake_app_module.YoyoPodApp = _FakeApp
    monkeypatch.setitem(sys.modules, "yoyopod.app", fake_app_module)
    monkeypatch.setattr(helpers, "_pump_app", lambda app, duration_seconds: None)
    monkeypatch.setattr(
        helpers,
        "build_navigation_soak_plan",
        lambda *, with_music: (
            helpers.NavigationSoakStep("replace", "Reset to the root hub", target="hub"),
            helpers.NavigationSoakStep(
                "action",
                "Open Listen from the hub",
                action=helpers.InputAction.SELECT,
                wait_for_route="listen",
                reset_selection_after_wait=True,
            ),
            helpers.NavigationSoakStep(
                "action",
                "Open Playlists from Listen",
                action=helpers.InputAction.SELECT,
                wait_for_route="playlists",
                reset_selection_after_wait=True,
            ),
            helpers.NavigationSoakStep(
                "action",
                "Return to Listen",
                action=helpers.InputAction.BACK,
                wait_for_route="listen",
                reset_selection_after_wait=True,
            ),
        ),
    )

    def fake_dispatch_action(app: _FakeApp, action: helpers.InputAction) -> None:
        current_route = app.screen_manager.current_screen.route_name
        if current_route == "hub" and action == helpers.InputAction.SELECT:
            app.screen_manager.current_screen = app.screen_manager.listen
            return

        if current_route == "listen" and action == helpers.InputAction.SELECT:
            app.screen_manager.current_screen = (
                app.screen_manager.playlists
                if app.screen_manager.listen.selected_index == 0
                else app.screen_manager.recent_tracks
            )
            return

        if current_route in {"playlists", "recent_tracks"} and action == helpers.InputAction.BACK:
            app.screen_manager.listen.selected_index = 1
            app.screen_manager.current_screen = app.screen_manager.listen
            return

        raise AssertionError(f"unexpected route/action: {current_route} / {action}")

    monkeypatch.setattr(helpers, "_dispatch_action", fake_dispatch_action)

    report = helpers.run_navigation_idle_soak(
        cycles=2,
        hold_seconds=0.1,
        idle_seconds=0.0,
        skip_sleep=True,
    )

    assert report.final_route == "listen"


def test_navigation_idle_soak_preserves_hub_progress_within_cycle(
    monkeypatch,
) -> None:
    class _FakeScreen:
        def __init__(self, route_name: str, *, selected_index: int = 0) -> None:
            self.route_name = route_name
            self.name = route_name
            self.selected_index = selected_index

    class _FakeScreenManager:
        def __init__(self) -> None:
            self.hub = _FakeScreen("hub")
            self.call = _FakeScreen("call")
            self.ask = _FakeScreen("ask")
            self.current_screen = self.hub

        def replace_screen(self, screen_name: str) -> None:
            self.current_screen = getattr(self, screen_name)

    class _FakeApp:
        def __init__(self, *, config_dir: str, simulate: bool) -> None:
            self.config_dir = config_dir
            self.simulate = simulate
            self.display = SimpleNamespace(backend_kind="lvgl")
            self.screen_manager = _FakeScreenManager()
            self.local_music_service = None
            self.music_backend = None

        def setup(self) -> bool:
            return True

        def stop(self) -> None:
            return None

    fake_app_module = ModuleType("yoyopod.app")
    fake_app_module.YoyoPodApp = _FakeApp
    monkeypatch.setitem(sys.modules, "yoyopod.app", fake_app_module)
    monkeypatch.setattr(helpers, "_pump_app", lambda app, duration_seconds: None)
    monkeypatch.setattr(
        helpers,
        "build_navigation_soak_plan",
        lambda *, with_music: (
            helpers.NavigationSoakStep("replace", "Reset to the root hub", target="hub"),
            helpers.NavigationSoakStep(
                "action",
                "Advance to Talk",
                action=helpers.InputAction.ADVANCE,
            ),
            helpers.NavigationSoakStep(
                "action",
                "Open Talk",
                action=helpers.InputAction.SELECT,
                wait_for_route="call",
            ),
            helpers.NavigationSoakStep(
                "action",
                "Return to the hub from Talk",
                action=helpers.InputAction.BACK,
                wait_for_route="hub",
            ),
            helpers.NavigationSoakStep(
                "action",
                "Advance to Ask",
                action=helpers.InputAction.ADVANCE,
            ),
            helpers.NavigationSoakStep(
                "action",
                "Open Ask",
                action=helpers.InputAction.SELECT,
                wait_for_route="ask",
            ),
        ),
    )

    def fake_dispatch_action(app: _FakeApp, action: helpers.InputAction) -> None:
        current_route = app.screen_manager.current_screen.route_name
        if current_route == "hub" and action == helpers.InputAction.ADVANCE:
            app.screen_manager.hub.selected_index += 1
            return

        if current_route == "hub" and action == helpers.InputAction.SELECT:
            app.screen_manager.current_screen = (
                app.screen_manager.call
                if app.screen_manager.hub.selected_index == 1
                else app.screen_manager.ask
            )
            return

        if current_route == "call" and action == helpers.InputAction.BACK:
            app.screen_manager.current_screen = app.screen_manager.hub
            return

        raise AssertionError(f"unexpected route/action: {current_route} / {action}")

    monkeypatch.setattr(helpers, "_dispatch_action", fake_dispatch_action)

    report = helpers.run_navigation_idle_soak(
        cycles=1,
        hold_seconds=0.1,
        idle_seconds=0.0,
        skip_sleep=True,
    )

    assert report.final_route == "ask"


def test_navigation_soak_runner_hub_mode_uses_public_cards_method() -> None:
    class _Card:
        def __init__(self, mode: str) -> None:
            self.mode = mode

    class _HubScreen:
        route_name = "hub"

        def __init__(self) -> None:
            self.selected_index = 1

        def cards(self) -> list[_Card]:
            return [_Card("listen"), _Card("talk"), _Card("ask")]

    hub_screen = _HubScreen()
    runner = helpers.NavigationSoakRunner(
        config_dir="config",
        cycles=1,
        hold_seconds=0.1,
        idle_seconds=0.0,
        tail_idle_seconds=0.0,
        with_playback=False,
        provision_test_music=False,
        test_music_dir="music",
        skip_sleep=True,
    )
    runner._app = SimpleNamespace(
        screen_manager=SimpleNamespace(get_current_screen=lambda: hub_screen),
    )

    assert runner._hub_mode() == "talk"


def test_navigation_soak_runner_clips_playback_idle_to_avoid_exhausting_fixture_tracks() -> None:
    """Playback dwell should stay short enough that the tiny validation queue is still skippable."""

    idle_calls: list[tuple[str, float]] = []
    simulated_actions: list[str] = []
    runner = helpers.NavigationSoakRunner(
        config_dir="config",
        cycles=1,
        hold_seconds=0.1,
        idle_seconds=3.0,
        tail_idle_seconds=0.0,
        with_playback=True,
        provision_test_music=False,
        test_music_dir="music",
        skip_sleep=True,
    )
    runner._pump = SimpleNamespace(run_for=lambda _seconds: None)
    runner._require_screen = lambda screen_name: None
    runner._wait_for_playback_started = lambda context_label: None
    runner._wait_for_track_change = lambda **_kwargs: None
    runner._current_track_name = lambda: "Alpha Beacon"
    runner._idle_phase = lambda label, seconds: idle_calls.append((label, seconds))
    runner._simulate_action = lambda action, **kwargs: simulated_actions.append(kwargs["label"])

    runner._exercise_now_playing(phase_label="shuffle_playback", back_target="listen")

    assert idle_calls == [
        ("shuffle_playback_idle", 1.0),
        ("shuffle_playback_post_next_idle", 1.0),
    ]
    assert simulated_actions == [
        "shuffle_playback pause",
        "shuffle_playback resume",
        "shuffle_playback next track",
        "shuffle_playback back",
    ]
