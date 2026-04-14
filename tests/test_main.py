import sys
from pathlib import Path
from types import SimpleNamespace

import yoyopy.main as main_module


def test_configure_logger_uses_shared_utility(monkeypatch, tmp_path) -> None:
    """Keep the app entrypoint aligned with the shared logging helper."""

    fake_settings = SimpleNamespace(logging=object())
    fake_runtime = object()
    calls = []
    fake_base_dir = tmp_path / "checkout-with-any-name"

    def fake_load_app_settings(config_dir: str) -> object:
        assert config_dir == "config"
        return fake_settings

    def fake_build_logging_runtime_config(settings, *, base_dir):
        assert settings is fake_settings.logging
        assert base_dir == fake_base_dir
        return fake_runtime

    def fake_init_logger(**kwargs) -> None:
        calls.append(kwargs)
        return fake_runtime

    monkeypatch.setattr(main_module, "load_app_settings", fake_load_app_settings)
    monkeypatch.setattr(
        main_module,
        "build_logging_runtime_config",
        fake_build_logging_runtime_config,
    )
    monkeypatch.setattr(main_module, "init_logger", fake_init_logger)
    fake_base_dir.mkdir()
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: fake_base_dir))

    runtime = main_module.configure_logger()

    assert runtime is fake_runtime
    assert calls == [
        {
            "config": fake_runtime,
            "console": True,
            "file_logging": True,
            "console_stream": sys.stderr,
            "announce": False,
        }
    ]


def test_capture_screenshot_prefers_readback_and_falls_back_to_shadow() -> None:
    """Default screenshot capture should try readback first, then shadow."""

    calls: list[tuple[str, str]] = []

    class Adapter:
        def save_screenshot_readback(self, path: str) -> bool:
            calls.append(("readback", path))
            return False

        def save_screenshot(self, path: str) -> bool:
            calls.append(("shadow", path))
            return True

    logs: list[tuple[str, tuple[object, ...]]] = []
    fake_log = SimpleNamespace(
        info=lambda *args: logs.append(("info", args)),
        warning=lambda *args: logs.append(("warning", args)),
    )

    result = main_module._capture_screenshot(
        adapter=Adapter(),
        screenshot_path="/tmp/test.png",
        app_log=fake_log,
        prefer_readback=True,
    )

    assert result is True
    assert calls == [("readback", "/tmp/test.png"), ("shadow", "/tmp/test.png")]
    assert logs[-1][0] == "info"


def test_capture_screenshot_handles_missing_adapter() -> None:
    """Missing adapters should return False without raising."""

    logs: list[tuple[str, tuple[object, ...]]] = []
    fake_log = SimpleNamespace(
        info=lambda *args: logs.append(("info", args)),
        warning=lambda *args: logs.append(("warning", args)),
    )

    result = main_module._capture_screenshot(
        adapter=None,
        screenshot_path="/tmp/test.png",
        app_log=fake_log,
        prefer_readback=True,
    )

    assert result is False
    assert logs[0][0] == "warning"
    assert str(logs[0][1][0]).startswith("Screenshot not available")


def test_request_screenshot_capture_queues_main_loop_callback(monkeypatch) -> None:
    """Signal-triggered screenshots should run on the app loop when possible."""

    queued_callbacks = []
    force_refresh_calls: list[str] = []
    refresh_screen_calls: list[str] = []
    capture_calls: list[tuple[object, str, bool, bool]] = []
    adapter = SimpleNamespace(_force_shadow_buffer_sync=False)

    class Display:
        def get_adapter(self) -> object:
            return adapter

        def get_ui_backend(self) -> object:
            return SimpleNamespace(
                force_refresh=lambda: force_refresh_calls.append("force_refresh")
            )

    class App:
        display = Display()
        screen_manager = SimpleNamespace(
            refresh_current_screen=lambda: refresh_screen_calls.append("refresh_screen")
        )

        def _queue_main_thread_callback(self, callback) -> None:
            queued_callbacks.append(callback)

    fake_log = SimpleNamespace(
        info=lambda *args: None,
        warning=lambda *args: None,
    )

    def fake_capture_screenshot(*, adapter, screenshot_path, app_log, prefer_readback) -> bool:
        capture_calls.append(
            (
                adapter,
                screenshot_path,
                prefer_readback,
                bool(getattr(adapter, "_force_shadow_buffer_sync", False)),
            )
        )
        return True

    monkeypatch.setattr(main_module, "_capture_screenshot", fake_capture_screenshot)

    main_module._request_screenshot_capture(
        app=App(),
        screenshot_path="/tmp/test.png",
        app_log=fake_log,
        prefer_readback=True,
    )

    assert len(queued_callbacks) == 1
    assert capture_calls == []

    queued_callbacks[0]()

    assert refresh_screen_calls == ["refresh_screen"]
    assert force_refresh_calls == ["force_refresh"]
    assert capture_calls == [(adapter, "/tmp/test.png", True, True)]
    assert adapter._force_shadow_buffer_sync is False
