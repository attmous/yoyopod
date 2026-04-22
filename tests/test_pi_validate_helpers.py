from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from yoyopod_cli import _pi_validate_helpers as helpers


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


def test_reset_selection_skips_watch_card_when_hub_exposes_it() -> None:
    class _Card:
        def __init__(self, title: str) -> None:
            self.title = title

    class _HubScreen:
        route_name = "hub"
        name = "hub"

        def __init__(self) -> None:
            self.selected_index = 4

        def cards(self) -> list[_Card]:
            return [_Card("Watch"), _Card("Listen"), _Card("Talk"), _Card("Ask"), _Card("Setup")]

    screen = _HubScreen()

    helpers._reset_selection(screen)

    assert screen.selected_index == 1


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
