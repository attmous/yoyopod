"""Regression tests for boot-time runtime wiring."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import yoyopod.runtime.boot as boot_module
from yoyopod.runtime.boot import RuntimeBootService
from yoyopod.runtime.boot.wiring_boot import WiringBoot


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


class _FakeVoipManager:
    def __init__(self) -> None:
        self.incoming_call_callback = None
        self.call_state_callback = None
        self.registration_callback = None
        self.availability_callback = None
        self.message_summary_callback = None
        self.message_received_callback = None
        self.message_delivery_callback = None
        self.message_failure_callback = None

    def on_incoming_call(self, callback) -> None:
        self.incoming_call_callback = callback

    def on_call_state_change(self, callback) -> None:
        self.call_state_callback = callback

    def on_registration_change(self, callback) -> None:
        self.registration_callback = callback

    def on_availability_change(self, callback) -> None:
        self.availability_callback = callback

    def on_message_summary_change(self, callback) -> None:
        self.message_summary_callback = callback

    def on_message_received(self, callback) -> None:
        self.message_received_callback = callback

    def on_message_delivery_change(self, callback) -> None:
        self.message_delivery_callback = callback

    def on_message_failure(self, callback) -> None:
        self.message_failure_callback = callback


class _FakeCallCoordinator:
    def handle_incoming_call(self, *_args) -> None:
        return None

    def handle_call_state_change(self, *_args) -> None:
        return None

    def handle_registration_change(self, *_args) -> None:
        return None

    def handle_availability_change(self, *_args) -> None:
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
    logged_exceptions = []

    monkeypatch.setattr(boot_module, "Display", _FakeWhisplayDisplay)
    monkeypatch.setattr(
        boot_module,
        "get_input_manager",
        lambda **_kwargs: fake_input_manager,
    )
    monkeypatch.setattr(
        boot_module.logger,
        "exception",
        lambda *_args, **_kwargs: logged_exceptions.append(sys.exc_info()[1]),
    )

    app = _FakeApp(scheduler=object())
    app.simulate = False
    app.app_settings.display.hardware = "whisplay"
    app.app_settings.display.whisplay_renderer = "lvgl"

    assert RuntimeBootService(app).init_core_components() is False
    assert len(logged_exceptions) == 1
    assert isinstance(logged_exceptions[0], boot_module.WhisplayProductionRenderContractError)
    assert app.input_manager is None
    assert fake_input_manager.started is False


def test_setup_voip_callbacks_bind_direct_call_handlers() -> None:
    """VoIP callbacks should wire straight to the coordinator handlers on main-thread delivery."""

    voip_manager = _FakeVoipManager()
    call_coordinator = _FakeCallCoordinator()
    voice_note_events = SimpleNamespace(
        handle_voice_note_summary_changed=lambda *_args: None,
        handle_voice_note_activity_changed=lambda *_args: None,
        handle_voice_note_failure=lambda *_args: None,
        sync_active_voice_note_context=lambda: None,
    )
    app = SimpleNamespace(
        voip_manager=voip_manager,
        call_coordinator=call_coordinator,
        event_wiring=SimpleNamespace(voice_note_events=voice_note_events),
        context=None,
        call_history_store=None,
    )
    wiring = WiringBoot(
        app,
        logger=SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None),
    )
    wiring.ensure_coordinators = lambda: None

    wiring.setup_voip_callbacks()

    assert voip_manager.incoming_call_callback.__name__ == "handle_incoming_call"
    assert voip_manager.call_state_callback.__name__ == "handle_call_state_change"
    assert voip_manager.registration_callback.__name__ == "handle_registration_change"
    assert voip_manager.availability_callback.__name__ == "handle_availability_change"
    assert voip_manager.message_summary_callback is voice_note_events.handle_voice_note_summary_changed
    assert voip_manager.message_received_callback is voice_note_events.handle_voice_note_activity_changed
    assert voip_manager.message_delivery_callback is voice_note_events.handle_voice_note_activity_changed
    assert voip_manager.message_failure_callback is voice_note_events.handle_voice_note_failure
