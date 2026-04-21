"""Regression tests for core bootstrap wiring."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import yoyopod.core.bootstrap as boot_module
from yoyopod.core.audio_volume import OutputVolumeController
from yoyopod.core import AppContext
from yoyopod.core.bootstrap import RuntimeBootService
from yoyopod.core.bootstrap.managers_boot import ManagersBoot


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
        self.scheduler = SimpleNamespace(run_on_main=scheduler)
        self.cloud_manager = SimpleNamespace(sync_context_state=lambda: None)
        self.call_history_store = None
        self.voip_manager = None
        self.voice_note_events = SimpleNamespace(sync_talk_summary_context=lambda: None)
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


class _FakeMusicBackend:
    def __init__(self) -> None:
        self.track_callback = None
        self.playback_state_callback = None
        self.connection_change_callbacks: list[object] = []

    def on_track_change(self, callback) -> None:
        self.track_callback = callback

    def on_playback_state_change(self, callback) -> None:
        self.playback_state_callback = callback

    def on_connection_change(self, callback) -> None:
        self.connection_change_callbacks.append(callback)


class _FakeCallRuntime:
    def handle_incoming_call(self, *_args) -> None:
        return None

    def handle_call_state_change(self, *_args) -> None:
        return None

    def handle_registration_change(self, *_args) -> None:
        return None

    def handle_availability_change(self, *_args) -> None:
        return None


class _FakeMusicRuntime:
    def handle_track_change(self, *_args) -> None:
        return None

    def handle_playback_state_change(self, *_args) -> None:
        return None

    def handle_availability_change(self, *_args) -> None:
        return None


def test_init_core_components_schedules_screen_actions_for_pil_backend(monkeypatch) -> None:
    """Boot wiring should serialize screen actions on the shared scheduler for pil displays."""

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
    """VoIP callbacks should wire straight to the call runtime handlers."""

    voip_manager = _FakeVoipManager()
    call_runtime = _FakeCallRuntime()
    synced = {"talk": 0, "active": 0}
    voice_note_events = SimpleNamespace(
        handle_voice_note_summary_changed=lambda *_args: None,
        handle_voice_note_activity_changed=lambda *_args: None,
        handle_voice_note_failure=lambda *_args: None,
        sync_talk_summary_context=lambda: synced.__setitem__("talk", synced["talk"] + 1),
        sync_active_voice_note_context=lambda: synced.__setitem__("active", synced["active"] + 1),
    )
    app = SimpleNamespace(
        voip_manager=voip_manager,
        call_runtime=call_runtime,
        voice_note_events=voice_note_events,
        context=None,
        call_history_store=None,
    )
    RuntimeBootService(app).setup_voip_callbacks()

    assert voip_manager.incoming_call_callback.__name__ == "handle_incoming_call"
    assert voip_manager.call_state_callback.__name__ == "handle_call_state_change"
    assert voip_manager.registration_callback.__name__ == "handle_registration_change"
    assert voip_manager.availability_callback.__name__ == "handle_availability_change"
    assert voip_manager.message_summary_callback is voice_note_events.handle_voice_note_summary_changed
    assert voip_manager.message_received_callback is voice_note_events.handle_voice_note_activity_changed
    assert voip_manager.message_delivery_callback is voice_note_events.handle_voice_note_activity_changed
    assert voip_manager.message_failure_callback is voice_note_events.handle_voice_note_failure
    assert synced == {"talk": 1, "active": 1}


def test_setup_music_callbacks_schedule_playback_handlers_on_main_thread() -> None:
    """Music callbacks should schedule playback handlers back onto the main thread."""

    music_backend = _FakeMusicBackend()
    handled: list[tuple[str, object]] = []
    music_runtime = SimpleNamespace(
        handle_track_change=lambda track: handled.append(("track", track)),
        handle_playback_state_change=lambda state: handled.append(("state", state)),
        handle_availability_change=lambda available, reason: handled.append(
            ("availability", (available, reason))
        ),
    )
    audio_volume_controller = SimpleNamespace(
        sync_output_volume_on_music_connect=lambda available, reason: handled.append(
            ("volume", (available, reason))
        )
    )
    app = SimpleNamespace(
        music_backend=music_backend,
        music_runtime=music_runtime,
        audio_volume_controller=audio_volume_controller,
        scheduler=SimpleNamespace(run_on_main=lambda fn: fn()),
    )
    RuntimeBootService(app).setup_music_callbacks()

    music_backend.track_callback("track-1")
    music_backend.playback_state_callback("playing")
    for callback in music_backend.connection_change_callbacks:
        callback(True, "connected")

    assert handled == [
        ("track", "track-1"),
        ("state", "playing"),
        ("volume", (True, "connected")),
        ("availability", (True, "connected")),
    ]


def test_setup_event_subscriptions_keeps_legacy_runtime_helper_flow() -> None:
    """The compatibility alias should still ensure runtime helpers."""

    service = RuntimeBootService(SimpleNamespace())
    calls: list[str] = []
    service.ensure_runtime_helpers = lambda: calls.append("ensure")

    service.setup_event_subscriptions()

    assert calls == ["ensure"]


def test_managers_boot_starts_network_and_syncs_context_without_event_wiring() -> None:
    """Network startup should use the dedicated runtime handler instead of deleted wiring glue."""

    sync_calls: list[str] = []

    class _FakeVoipConfig:
        iterate_interval_ms = 20

        @classmethod
        def from_config_manager(cls, _config_manager):
            return cls()

    class _FakeVoipManager:
        def __init__(self, *_args, **_kwargs) -> None:
            self.running = False
            self.registration_state = "none"

        def start(self) -> bool:
            return False

    class _FakeMusicConfig:
        music_dir = "data/test_music"

        @classmethod
        def from_config_manager(cls, _config_manager):
            return cls()

    class _FakeMusicBackend:
        def __init__(self, _config) -> None:
            self.is_connected = False

        def start(self) -> bool:
            return False

    class _FakeLocalMusicService:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

    class _FakeOutputVolumeController:
        def __init__(self, _music_backend) -> None:
            return None

    class _FakePowerManager:
        def __init__(self) -> None:
            self.config = SimpleNamespace(enabled=False, poll_interval_seconds=30.0)

        @classmethod
        def from_config_manager(cls, _config_manager):
            return cls()

    class _FakeNetworkManager:
        def __init__(self) -> None:
            self.config = SimpleNamespace(enabled=True)
            self.started = False

        @classmethod
        def from_config_manager(cls, _config_manager, event_publisher=None):
            assert event_publisher is not None
            return cls()

        def start(self) -> None:
            self.started = True

    class _FakeCloudManager:
        def __init__(self, *, app, config_manager) -> None:
            self.app = app
            self.config_manager = config_manager
            self.prepare_calls = 0

        def prepare_boot(self) -> None:
            self.prepare_calls += 1

    display = SimpleNamespace(
        COLOR_BLACK=0,
        COLOR_WHITE=1,
        clear=lambda *_args, **_kwargs: None,
        text=lambda *_args, **_kwargs: None,
        update=lambda: None,
    )
    app = SimpleNamespace(
        display=display,
        config_manager=_FakeConfigManager(),
        people_directory=None,
        recent_track_store=None,
        context=AppContext(),
        runtime_loop=SimpleNamespace(queue_main_thread_callback=lambda *_args, **_kwargs: None),
        scheduler=SimpleNamespace(run_on_main=lambda fn: fn()),
        output_volume=None,
        audio_volume_controller=None,
        simulate=False,
        network_events=SimpleNamespace(
            sync_network_context_from_manager=lambda: sync_calls.append("synced")
        ),
    )

    service = ManagersBoot(
        app,
        logger=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
            exception=lambda *_args, **_kwargs: None,
        ),
        voip_config_cls=_FakeVoipConfig,
        voip_manager_cls=_FakeVoipManager,
        music_config_cls=_FakeMusicConfig,
        mpv_backend_cls=_FakeMusicBackend,
        local_music_service_cls=_FakeLocalMusicService,
        output_volume_controller_cls=_FakeOutputVolumeController,
        power_manager_cls=_FakePowerManager,
        network_manager_cls=_FakeNetworkManager,
        cloud_manager_cls=_FakeCloudManager,
    )

    assert service.init_managers() is True
    assert app.network_manager.started is True
    assert sync_calls == ["synced"]
