from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core.bootstrap.components_boot import ComponentsBoot


class _FailingDisplay:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("Python display must not initialize in Rust UI mode")


def _fake_input_manager(*args, **kwargs):
    raise AssertionError("Python input must not initialize in Rust UI mode")


class _FailingScreenManager:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("Python screen manager must not initialize in Rust UI mode")


class _Settings:
    display = SimpleNamespace(
        hardware="whisplay",
        whisplay_renderer="lvgl",
        lvgl_buffer_lines=40,
        rust_ui_enabled=True,
        rust_ui_worker_path="src/crates/ui-host/build/yoyopod-ui-host",
    )
    input = SimpleNamespace()


class _ScreenPowerService:
    def __init__(self) -> None:
        self.configured_at: float | None = None
        self.metrics_updates: list[float] = []

    def configure_screen_power(self, initial_now: float) -> None:
        self.configured_at = initial_now

    def update_screen_runtime_metrics(self, now: float) -> None:
        self.metrics_updates.append(now)


def test_components_boot_skips_python_ui_hardware_when_rust_ui_enabled() -> None:
    screen_power_service = _ScreenPowerService()
    app = SimpleNamespace(
        simulate=False,
        app_settings=_Settings(),
        media_settings=SimpleNamespace(music=SimpleNamespace(default_volume=80)),
        display=None,
        context=None,
        config_manager=None,
        output_volume=None,
        music_backend=None,
        audio_volume_controller=None,
        screen_power_service=screen_power_service,
        voice_note_events=SimpleNamespace(sync_talk_summary_context=lambda: None),
        music_fsm=None,
        call_fsm=None,
        call_interruption_policy=None,
        input_manager=None,
        screen_manager=None,
        _lvgl_backend=None,
        _lvgl_input_bridge=None,
        runtime_loop=SimpleNamespace(last_lvgl_pump_at=0.0),
        note_input_activity=lambda *args, **kwargs: None,
        note_handled_input=lambda *args, **kwargs: None,
        note_visible_refresh=lambda *args, **kwargs: None,
        scheduler=SimpleNamespace(run_on_main=lambda fn: fn()),
    )
    boot = ComponentsBoot(
        app,
        logger=SimpleNamespace(
            info=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        ),
        display_cls=_FailingDisplay,
        get_input_manager_fn=_fake_input_manager,
        screen_manager_cls=_FailingScreenManager,
        lvgl_input_bridge_cls=object,
        contract_error_cls=RuntimeError,
        build_contract_message_fn=lambda message: message,
    )

    assert boot.init_core_components()
    assert app.display is None
    assert app.input_manager is None
    assert app.screen_manager is None
    assert app.context is not None
    assert screen_power_service.configured_at is not None
