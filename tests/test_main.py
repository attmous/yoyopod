import sys
from pathlib import Path
from types import SimpleNamespace

import yoyopy.main as main_module


def test_configure_logger_uses_shared_utility(monkeypatch) -> None:
    """Keep the app entrypoint aligned with the shared logging helper."""
    fake_settings = SimpleNamespace(logging=object())
    fake_runtime = object()
    calls = []

    def fake_load_app_settings(config_dir: str) -> object:
        assert config_dir == "config"
        return fake_settings

    def fake_build_logging_runtime_config(settings, *, base_dir):
        assert settings is fake_settings.logging
        assert base_dir == Path.cwd()
        assert (base_dir / "pyproject.toml").exists()
        assert base_dir.name.startswith("yoyo-py")
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
    assert logs == [("warning", ("Screenshot not available — no active display adapter",))]
