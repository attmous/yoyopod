"""Regression tests for core bootstrap wiring."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import yoyopod.core.bootstrap as boot_module
from yoyopod.core import AppContext
from yoyopod.core.audio_volume import OutputVolumeController
from yoyopod.core.bootstrap.components_boot import ComponentsBoot
from yoyopod.core.bootstrap import RuntimeBootService
from yoyopod.core.bootstrap.screens_boot import ScreensBoot
from yoyopod.core.bootstrap.managers_boot import ManagersBoot
from yoyopod.core.bus import Bus
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.workers import WorkerProcessConfig
from yoyopod.integrations.voice import VoiceSettings
from yoyopod.backends.voice import (
    CloudWorkerSpeechToTextBackend,
    CloudWorkerTextToSpeechBackend,
)


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
        self.backend_kind = "unavailable"
        self._ui_backend = SimpleNamespace(
            initialized=False,
            initialize=self._initialize_backend,
        )

    def _initialize_backend(self) -> bool:
        self._ui_backend.initialized = True
        return True

    def get_ui_backend(self):
        return self._ui_backend

    def refresh_backend_kind(self) -> str:
        self.backend_kind = "lvgl" if self._ui_backend.initialized else "unavailable"
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
                whisplay_renderer="lvgl",
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
        self._screen_awake = True

    def note_input_activity(self, _data=None) -> None:
        return None

    def note_handled_input(self, *, action_name: str | None, handled_at: float) -> None:
        return None

    def note_visible_refresh(self, *, refreshed_at: float) -> None:
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
        self.warm_start_calls = 0

    def on_track_change(self, callback) -> None:
        self.track_callback = callback

    def on_playback_state_change(self, callback) -> None:
        self.playback_state_callback = callback

    def on_connection_change(self, callback) -> None:
        self.connection_change_callbacks.append(callback)

    def warm_start(self) -> None:
        self.warm_start_calls += 1


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


class _DummyScreen:
    def __init__(self, *_args, **_kwargs) -> None:
        return None


class _FakeScreenManager:
    def __init__(self) -> None:
        self.registered: list[str] = []
        self.pushed: list[str] = []

    def register_screen(self, name: str, _screen: object) -> None:
        self.registered.append(name)

    def push_screen(self, name: str) -> None:
        self.pushed.append(name)


def _components_boot_for(app: object) -> ComponentsBoot:
    return ComponentsBoot(
        app,
        logger=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
            exception=lambda *_args, **_kwargs: None,
        ),
        display_cls=None,
        get_input_manager_fn=None,
        screen_manager_cls=None,
        lvgl_input_bridge_cls=None,
        contract_error_cls=RuntimeError,
        build_contract_message_fn=lambda message: message,
    )


def _quiet_logger() -> SimpleNamespace:
    return SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        exception=lambda *_args, **_kwargs: None,
    )


def _install_dummy_screen_modules(monkeypatch) -> None:
    screens = {
        "yoyopod.ui.screens.music.now_playing": "NowPlayingScreen",
        "yoyopod.ui.screens.music.playlist": "PlaylistScreen",
        "yoyopod.ui.screens.music.recent": "RecentTracksScreen",
        "yoyopod.ui.screens.navigation.ask": "AskScreen",
        "yoyopod.ui.screens.navigation.home": "HomeScreen",
        "yoyopod.ui.screens.navigation.hub": "HubScreen",
        "yoyopod.ui.screens.navigation.listen": "ListenScreen",
        "yoyopod.ui.screens.navigation.menu": "MenuScreen",
        "yoyopod.ui.screens.system.power": "PowerScreen",
        "yoyopod.ui.screens.voip.call_history": "CallHistoryScreen",
        "yoyopod.ui.screens.voip.contact_list": "ContactListScreen",
        "yoyopod.ui.screens.voip.in_call": "InCallScreen",
        "yoyopod.ui.screens.voip.incoming_call": "IncomingCallScreen",
        "yoyopod.ui.screens.voip.outgoing_call": "OutgoingCallScreen",
        "yoyopod.ui.screens.voip.quick_call": "CallScreen",
        "yoyopod.ui.screens.voip.talk_contact": "TalkContactScreen",
        "yoyopod.ui.screens.voip.voice_note": "VoiceNoteScreen",
    }
    for module_name, class_name in screens.items():
        module = ModuleType(module_name)
        setattr(module, class_name, _DummyScreen)
        monkeypatch.setitem(sys.modules, module_name, module)


def _cloud_voice_config(*, stt_backend: str, tts_backend: str) -> SimpleNamespace:
    return SimpleNamespace(
        assistant=SimpleNamespace(
            mode="cloud",
            commands_enabled=True,
            ai_requests_enabled=True,
            screen_read_enabled=False,
            stt_enabled=True,
            tts_enabled=True,
            stt_backend=stt_backend,
            tts_backend=tts_backend,
            vosk_model_path="models/vosk-model-small-en-us",
            vosk_model_keep_loaded=True,
            sample_rate_hz=16000,
            record_seconds=4,
            tts_rate_wpm=155,
            tts_voice="en",
        ),
        audio=SimpleNamespace(
            speaker_device_id="",
            capture_device_id="",
        ),
        worker=SimpleNamespace(
            enabled=True,
            domain="voice",
            provider="mock",
            request_timeout_seconds=12.0,
            max_audio_seconds=30.0,
            stt_model="gpt-4o-mini-transcribe",
            tts_model="gpt-4o-mini-tts",
            tts_voice="alloy",
            tts_instructions="Speak clearly and briefly for a small handheld device.",
            local_feedback_enabled=True,
        ),
    )


def _build_cloud_screen_app(*, stt_backend: str, tts_backend: str) -> SimpleNamespace:
    return SimpleNamespace(
        display=SimpleNamespace(),
        context=AppContext(),
        screen_manager=_FakeScreenManager(),
        audio_volume_controller=SimpleNamespace(
            get_output_volume=lambda: 61,
            volume_up=lambda _step: 66,
            volume_down=lambda _step: 56,
        ),
        config_manager=SimpleNamespace(
            get_voice_settings=lambda: _cloud_voice_config(
                stt_backend=stt_backend,
                tts_backend=tts_backend,
            )
        ),
        voice_worker_client=object(),
        input_manager=None,
        people_directory=None,
        voip_manager=None,
        local_music_service=None,
    )


def test_setup_voice_worker_registers_starts_and_subscribes_when_cloud_enabled(
    monkeypatch,
) -> None:
    """Cloud voice mode should wire the worker process and client exactly once."""

    monkeypatch.setenv("OPENAI_API_KEY", "secret-from-process")
    scheduler = MainThreadScheduler()
    bus = Bus(main_thread_id=scheduler.main_thread_id)
    registered: list[tuple[str, WorkerProcessConfig]] = []
    started: list[str] = []
    health_probes: list[object] = []
    monkeypatch.setattr(
        "yoyopod.core.bootstrap.components_boot._start_voice_worker_health_probe",
        lambda client, logger: health_probes.append(client),
    )

    class _FakeWorkerSupervisor:
        def register(self, domain: str, config: WorkerProcessConfig) -> None:
            registered.append((domain, config))

        def start(self, domain: str) -> bool:
            started.append(domain)
            return True

    app = SimpleNamespace(
        config_manager=SimpleNamespace(
            get_voice_settings=lambda: SimpleNamespace(
                assistant=SimpleNamespace(mode="cloud"),
                worker=SimpleNamespace(
                    enabled=True,
                    domain="voice",
                    provider="openai",
                    argv=["python", "fake_worker.py"],
                    request_timeout_seconds=3.5,
                    stt_model="stt-from-yaml",
                    tts_model="tts-from-yaml",
                    tts_voice="voice-from-yaml",
                    tts_instructions="instructions from yaml",
                ),
            )
        ),
        scheduler=scheduler,
        bus=bus,
        worker_supervisor=_FakeWorkerSupervisor(),
        voice_worker_client=None,
    )
    boot = _components_boot_for(app)

    assert boot.setup_voice_worker() is True

    assert app.voice_worker_client is not None
    assert len(registered) == 1
    domain, worker_config = registered[0]
    assert domain == "voice"
    assert worker_config.name == "voice"
    assert worker_config.argv == ["python", "fake_worker.py"]
    assert worker_config.cwd is None
    assert worker_config.env is not None
    assert worker_config.env["OPENAI_API_KEY"] == "secret-from-process"
    assert worker_config.env["YOYOPOD_VOICE_WORKER_PROVIDER"] == "openai"
    assert worker_config.env["YOYOPOD_CLOUD_STT_MODEL"] == "stt-from-yaml"
    assert worker_config.env["YOYOPOD_CLOUD_TTS_MODEL"] == "tts-from-yaml"
    assert worker_config.env["YOYOPOD_CLOUD_TTS_VOICE"] == "voice-from-yaml"
    assert worker_config.env["YOYOPOD_CLOUD_TTS_INSTRUCTIONS"] == "instructions from yaml"
    assert started == ["voice"]
    assert bus.subscription_counts()["WorkerMessageReceivedEvent"] == 1
    assert bus.subscription_counts()["WorkerDomainStateChangedEvent"] == 1
    assert health_probes == [app.voice_worker_client]

    first_client = app.voice_worker_client
    assert boot.setup_voice_worker() is False

    assert app.voice_worker_client is first_client
    assert len(registered) == 1
    assert started == ["voice"]


def test_setup_voice_worker_clears_client_when_start_fails(monkeypatch) -> None:
    """A failed worker start should leave cloud STT/TTS unavailable at setup time."""

    scheduler = MainThreadScheduler()
    bus = Bus(main_thread_id=scheduler.main_thread_id)
    health_probes: list[object] = []
    monkeypatch.setattr(
        "yoyopod.core.bootstrap.components_boot._start_voice_worker_health_probe",
        lambda client, logger: health_probes.append(client),
    )

    class _FailingWorkerSupervisor:
        def register(self, domain: str, config: WorkerProcessConfig) -> None:
            return None

        def start(self, domain: str) -> bool:
            return False

    app = SimpleNamespace(
        config_manager=SimpleNamespace(
            get_voice_settings=lambda: SimpleNamespace(
                assistant=SimpleNamespace(mode="cloud"),
                worker=SimpleNamespace(
                    enabled=True,
                    domain="voice",
                    provider="mock",
                    argv=["python", "fake_worker.py"],
                    request_timeout_seconds=3.5,
                ),
            )
        ),
        scheduler=scheduler,
        bus=bus,
        worker_supervisor=_FailingWorkerSupervisor(),
        voice_worker_client=None,
    )

    assert _components_boot_for(app).setup_voice_worker() is False
    assert app.voice_worker_client is None
    assert health_probes == []


def test_cloud_voice_factory_preserves_local_stt_when_only_tts_uses_worker(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _install_dummy_screen_modules(monkeypatch)

    class _CapturingVoiceRuntime:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "yoyopod.core.bootstrap.screens_boot.VoiceRuntimeCoordinator",
        _CapturingVoiceRuntime,
    )
    app = _build_cloud_screen_app(stt_backend="vosk", tts_backend="cloud-worker")

    assert ScreensBoot(app, logger=_quiet_logger()).setup_screens() is True

    factory = captured["voice_service_factory"]
    assert callable(factory)
    manager = factory(
        VoiceSettings(
            mode="cloud",
            stt_backend="vosk",
            tts_backend="cloud-worker",
            cloud_worker_enabled=True,
        )
    )

    assert manager.settings.stt_backend == "vosk"
    assert manager.settings.tts_backend == "cloud-worker"
    assert not isinstance(manager.stt_backend, CloudWorkerSpeechToTextBackend)
    assert isinstance(manager.tts_backend, CloudWorkerTextToSpeechBackend)


def test_cloud_voice_factory_preserves_local_tts_when_only_stt_uses_worker(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _install_dummy_screen_modules(monkeypatch)

    class _CapturingVoiceRuntime:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "yoyopod.core.bootstrap.screens_boot.VoiceRuntimeCoordinator",
        _CapturingVoiceRuntime,
    )
    app = _build_cloud_screen_app(stt_backend="cloud-worker", tts_backend="espeak-ng")

    assert ScreensBoot(app, logger=_quiet_logger()).setup_screens() is True

    factory = captured["voice_service_factory"]
    assert callable(factory)
    manager = factory(
        VoiceSettings(
            mode="cloud",
            stt_backend="cloud-worker",
            tts_backend="espeak-ng",
            cloud_worker_enabled=True,
        )
    )

    assert manager.settings.stt_backend == "cloud-worker"
    assert manager.settings.tts_backend == "espeak-ng"
    assert isinstance(manager.stt_backend, CloudWorkerSpeechToTextBackend)
    assert not isinstance(manager.tts_backend, CloudWorkerTextToSpeechBackend)


def test_init_core_components_schedules_screen_actions_for_lvgl_backend(monkeypatch) -> None:
    """Boot wiring should serialize screen actions on the shared scheduler for LVGL displays."""

    scheduled_callback = object()
    fake_input_manager = _FakeInputManager()
    captured = {}

    monkeypatch.setattr(boot_module, "Display", _FakeDisplay)
    monkeypatch.setattr(
        boot_module,
        "get_input_manager",
        lambda **_kwargs: fake_input_manager,
    )

    def _capture_screen_manager(
        display,
        input_manager,
        action_scheduler=None,
        on_action_handled=None,
        on_visible_refresh=None,
        is_screen_visible=None,
    ):
        captured["display"] = display
        captured["input_manager"] = input_manager
        captured["action_scheduler"] = action_scheduler
        captured["on_action_handled"] = on_action_handled
        captured["on_visible_refresh"] = on_visible_refresh
        captured["is_screen_visible"] = is_screen_visible
        return SimpleNamespace(
            display=display,
            input_manager=input_manager,
            action_scheduler=action_scheduler,
            on_action_handled=on_action_handled,
            on_visible_refresh=on_visible_refresh,
            is_screen_visible=is_screen_visible,
        )

    monkeypatch.setattr(boot_module, "ScreenManager", _capture_screen_manager)

    app = _FakeApp(scheduler=scheduled_callback)

    assert RuntimeBootService(app).init_core_components() is True
    assert captured["display"].backend_kind == "lvgl"
    assert captured["input_manager"] is fake_input_manager
    assert captured["action_scheduler"] is scheduled_callback
    assert captured["on_action_handled"].__self__ is app
    assert captured["on_action_handled"].__func__ is _FakeApp.note_handled_input
    assert captured["on_visible_refresh"].__self__ is app
    assert captured["on_visible_refresh"].__func__ is _FakeApp.note_visible_refresh
    assert captured["is_screen_visible"]() is True
    assert fake_input_manager.started is True


def test_init_core_components_refuses_whisplay_when_lvgl_backend_does_not_start(
    monkeypatch,
) -> None:
    """Production Whisplay startup should fail instead of downgrading to PIL."""

    class _FakeLvglBackend:
        def __init__(self) -> None:
            self.initialized = False

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
            self.backend_kind = "unavailable"
            self._adapter = SimpleNamespace(DISPLAY_TYPE="whisplay")
            self._ui_backend = _FakeLvglBackend()

        def get_ui_backend(self):
            return self._ui_backend

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


def test_init_core_components_refuses_simulation_when_lvgl_backend_does_not_start(
    monkeypatch,
) -> None:
    """Simulation should fail loudly when the native LVGL shim is unavailable."""

    class _FakeLvglBackend:
        def __init__(self) -> None:
            self.initialized = False

        def initialize(self) -> bool:
            return False

    class _FakeSimulationDisplay(_FakeDisplay):
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
            self.backend_kind = "unavailable"
            self._adapter = SimpleNamespace(DISPLAY_TYPE="simulation")
            self._ui_backend = _FakeLvglBackend()

        def get_ui_backend(self):
            return self._ui_backend

        def get_adapter(self) -> object:
            return self._adapter

    fake_input_manager = _FakeInputManager()
    logged_exceptions = []

    monkeypatch.setattr(boot_module, "Display", _FakeSimulationDisplay)
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
    app.simulate = True
    app.app_settings.display.hardware = "simulation"
    app.app_settings.display.whisplay_renderer = "lvgl"

    assert RuntimeBootService(app).init_core_components() is False
    assert len(logged_exceptions) == 1
    assert isinstance(logged_exceptions[0], RuntimeError)
    assert "yoyopod build simulation" in str(logged_exceptions[0])
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
    assert music_backend.warm_start_calls == 1


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
            self.start_calls = 0

        def start(self) -> bool:
            self.start_calls += 1
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
            self.started_in_background = False

        @classmethod
        def from_config_manager(cls, _config_manager, event_publisher=None):
            assert event_publisher is not None
            return cls()

        def start(self) -> None:
            self.started = True

        def start_background(self, *, on_failure=None):
            self.started_in_background = True
            return SimpleNamespace()

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
    assert app.music_backend.start_calls == 0
    assert app.network_manager.started is False
    assert app.network_manager.started_in_background is True
    assert sync_calls == ["synced"]
