"""Regression tests for boot-time runtime wiring."""

from __future__ import annotations

from types import SimpleNamespace

import yoyopod.runtime.boot as boot_module
from yoyopod.runtime.boot import RuntimeBootService


class _FakeDisplay:
    WIDTH = 240
    HEIGHT = 240
    ORIENTATION = 0
    COLOR_BLACK = 0
    COLOR_WHITE = 1

    def __init__(
        self,
        *,
        hardware: str,
        simulate: bool,
        whisplay_renderer: str,
        whisplay_lvgl_buffer_lines: int,
    ) -> None:
        self.hardware = hardware
        self.simulate = simulate
        self.whisplay_renderer = whisplay_renderer
        self.whisplay_lvgl_buffer_lines = whisplay_lvgl_buffer_lines
        self.backend_kind = "pil"

    def get_ui_backend(self):
        return None

    def refresh_backend_kind(self) -> str:
        return self.backend_kind

    def clear(self, *_args, **_kwargs) -> None:
        return None

    def text(self, *_args, **_kwargs) -> None:
        return None

    def update(self) -> None:
        return None

    def get_adapter(self) -> object:
        return object()


class _FakeInputManager:
    def __init__(self) -> None:
        self.interaction_profile = "one_button"
        self.activity_callbacks = []
        self.started = False

    def on_activity(self, callback) -> None:
        self.activity_callbacks.append(callback)

    def start(self) -> None:
        self.started = True


class _FakeConfigManager:
    def get_max_output_volume(self) -> int:
        return 80

    def get_sip_identity(self) -> str:
        return ""

    def get_sip_username(self) -> str:
        return ""

    def get_voice_settings(self):
        return SimpleNamespace(
            assistant=SimpleNamespace(
                commands_enabled=False,
                ai_requests_enabled=False,
                screen_read_enabled=True,
                stt_enabled=False,
                tts_enabled=False,
            ),
            audio=SimpleNamespace(
                speaker_device_id="",
                capture_device_id="",
            ),
        )


class _FakeScreenPowerService:
    def configure_screen_power(self, *, initial_now: float) -> None:
        return None

    def update_screen_runtime_metrics(self, _now: float) -> None:
        return None

    def queue_user_activity_event(self, _data=None) -> None:
        return None


class _FakeApp:
    def __init__(self, scheduler) -> None:
        self.app_settings = SimpleNamespace(
            display=SimpleNamespace(
                hardware="auto",
                whisplay_renderer="pil",
                lvgl_buffer_lines=40,
            ),
            input=SimpleNamespace(),
        )
        self.simulate = True
        self.config_manager = _FakeConfigManager()
        self.screen_power_service = _FakeScreenPowerService()
        self.runtime_loop = SimpleNamespace(
            queue_main_thread_callback=scheduler,
            queue_lvgl_input_action=lambda _data=None: None,
        )
        self.cloud_manager = SimpleNamespace(sync_context_state=lambda: None)
        self.call_history_store = None
        self.voip_manager = None
        self.context = None
        self.display = None
        self.input_manager = None
        self.screen_manager = None
        self.music_fsm = None
        self.call_fsm = None
        self.call_interruption_policy = None
        self._lvgl_backend = None
        self._lvgl_input_bridge = None

    def note_input_activity(self, _data=None) -> None:
        return None


def test_init_core_components_schedules_screen_actions_for_pil_backend(monkeypatch) -> None:
    """Boot wiring should serialize screen actions on the runtime loop for pil displays too."""

    scheduled_callback = object()
    fake_input_manager = _FakeInputManager()
    captured = {}

    monkeypatch.setattr(boot_module, "Display", _FakeDisplay)
    monkeypatch.setattr(
        boot_module,
        "get_input_manager",
        lambda **_kwargs: fake_input_manager,
    )

    def _capture_screen_manager(display, input_manager, action_scheduler=None):
        captured["display"] = display
        captured["input_manager"] = input_manager
        captured["action_scheduler"] = action_scheduler
        return SimpleNamespace(
            display=display,
            input_manager=input_manager,
            action_scheduler=action_scheduler,
        )

    monkeypatch.setattr(boot_module, "ScreenManager", _capture_screen_manager)

    app = _FakeApp(scheduler=scheduled_callback)

    assert RuntimeBootService(app).init_core_components() is True
    assert captured["display"].backend_kind == "pil"
    assert captured["input_manager"] is fake_input_manager
    assert captured["action_scheduler"] is scheduled_callback
    assert fake_input_manager.started is True


def test_init_core_components_refuses_whisplay_when_lvgl_backend_does_not_start(
    monkeypatch,
) -> None:
    """Production Whisplay startup should fail instead of downgrading to PIL."""

    class _FakeLvglBackend:
        def initialize(self) -> bool:
            return False

    class _FakeWhisplayDisplay(_FakeDisplay):
        def __init__(
            self,
            *,
            hardware: str,
            simulate: bool,
            whisplay_renderer: str,
            whisplay_lvgl_buffer_lines: int,
        ) -> None:
            super().__init__(
                hardware=hardware,
                simulate=simulate,
                whisplay_renderer=whisplay_renderer,
                whisplay_lvgl_buffer_lines=whisplay_lvgl_buffer_lines,
            )
            self.backend_kind = "pil"
            self._adapter = SimpleNamespace(DISPLAY_TYPE="whisplay")

        def get_ui_backend(self):
            return _FakeLvglBackend()

        def get_adapter(self) -> object:
            return self._adapter

    fake_input_manager = _FakeInputManager()

    monkeypatch.setattr(boot_module, "Display", _FakeWhisplayDisplay)
    monkeypatch.setattr(
        boot_module,
        "get_input_manager",
        lambda **_kwargs: fake_input_manager,
    )

    app = _FakeApp(scheduler=object())
    app.simulate = False
    app.app_settings.display.hardware = "whisplay"
    app.app_settings.display.whisplay_renderer = "lvgl"

    assert RuntimeBootService(app).init_core_components() is False
    assert app.input_manager is None
    assert fake_input_manager.started is False
