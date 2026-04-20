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
