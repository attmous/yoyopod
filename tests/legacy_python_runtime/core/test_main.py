import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import yoyopod.main as main_module
import yoyopod.core.diagnostics.watchdog as diagnostics_module
import yoyopod.ui.display.screenshot as screenshot_module
from yoyopod.core.diagnostics.watchdog import ResponsivenessWatchdogDecision
from yoyopod.core import RUNTIME_REQUIRED_CONFIG_FILES


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

    result = screenshot_module._capture_screenshot(
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

    result = screenshot_module._capture_screenshot(
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

    monkeypatch.setattr(screenshot_module, "_capture_screenshot", fake_capture_screenshot)

    screenshot_module._request_screenshot_capture(
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


def test_log_signal_snapshot_serializes_runtime_state() -> None:
    """Signal-triggered diagnostics should emit JSON-safe runtime state."""

    logs: list[tuple[object, ...]] = []
    fake_log = SimpleNamespace(
        error=lambda *args: logs.append(args),
    )
    app = SimpleNamespace(
        get_status=lambda: {
            "current_screen": "hub",
            "rtc_time": datetime(2026, 4, 16, 0, 9, tzinfo=timezone.utc),
            "recent_calls": [{"when": datetime(2026, 4, 15, 23, 59, tzinfo=timezone.utc)}],
        }
    )

    diagnostics_module._log_signal_snapshot(
        app=app,
        app_log=fake_log,
        signal_name="SIGUSR1",
        prefer_readback=True,
    )

    assert len(logs) == 1
    assert logs[0][0] == "Freeze diagnostics snapshot: {}"
    payload = json.loads(logs[0][1])
    assert payload["signal"] == "SIGUSR1"
    assert payload["capture_mode"] == "readback-first"
    assert payload["status"]["current_screen"] == "hub"
    assert payload["status"]["rtc_time"] == "2026-04-16T00:09:00+00:00"
    assert payload["status"]["recent_calls"][0]["when"] == "2026-04-15T23:59:00+00:00"


def test_log_setup_failure_guidance_uses_shared_runtime_config_contract() -> None:
    """Bootstrap guidance should enumerate the shared runtime config surface."""

    logs: list[tuple[object, ...]] = []
    fake_log = SimpleNamespace(
        error=lambda *args: logs.append(args),
    )

    diagnostics_module._log_setup_failure_guidance(fake_log)

    for relative_path in RUNTIME_REQUIRED_CONFIG_FILES:
        assert (f"  - {relative_path.as_posix()} exists",) in logs


def test_capture_responsiveness_watchdog_evidence_writes_artifacts(
    monkeypatch,
    tmp_path,
) -> None:
    """Automatic watchdog captures should write a JSON snapshot and traceback artifact."""

    logs: list[tuple[object, ...]] = []
    fake_log = SimpleNamespace(
        error=lambda *args: logs.append(args),
        warning=lambda *args: logs.append(args),
    )
    capture_dir = tmp_path / "captures"
    recorded: list[dict[str, object]] = []

    class App:
        app_settings = SimpleNamespace(
            diagnostics=SimpleNamespace(responsiveness_capture_dir=str(capture_dir))
        )

        def record_responsiveness_capture(self, **kwargs) -> None:
            recorded.append(kwargs)

    monkeypatch.setattr(
        diagnostics_module.faulthandler,
        "dump_traceback",
        lambda *, file, all_threads: file.write(f"TRACEBACK all_threads={all_threads}\n"),
    )

    decision = ResponsivenessWatchdogDecision(
        reason="coordinator_stall_after_input",
        suspected_scope="input_to_runtime_handoff",
        summary="input kept moving but the coordinator stalled",
    )
    status = {
        "state": "menu",
        "current_screen": "menu",
        "loop_heartbeat_age_seconds": 6.0,
        "input_activity_age_seconds": 0.4,
        "handled_input_activity_age_seconds": 6.2,
    }

    diagnostics_module._capture_responsiveness_watchdog_evidence(
        app=App(),
        app_log=fake_log,
        error_log_path=tmp_path / "yoyopod_errors.log",
        decision=decision,
        status=status,
    )

    snapshot_files = sorted(capture_dir.glob("*.json"))
    traceback_files = sorted(capture_dir.glob("*.traceback.txt"))

    assert len(snapshot_files) == 1
    assert len(traceback_files) == 1
    snapshot_payload = json.loads(snapshot_files[0].read_text(encoding="utf-8"))
    assert snapshot_payload["source"] == "responsiveness_watchdog"
    assert snapshot_payload["reason"] == "coordinator_stall_after_input"
    assert snapshot_payload["status"]["loop_heartbeat_age_seconds"] == 6.0
    assert "TRACEBACK all_threads=True" in traceback_files[0].read_text(encoding="utf-8")
    assert recorded[0]["reason"] == "coordinator_stall_after_input"
    assert recorded[0]["artifacts"]["snapshot"] == str(snapshot_files[0])
    assert logs[-1][0] == "Responsiveness watchdog captured evidence: {}"


def test_capture_responsiveness_watchdog_evidence_reuses_single_capture_timestamp(
    monkeypatch,
    tmp_path,
) -> None:
    """Snapshot payload and artifact stem should come from the same timestamp."""

    first_capture_at = datetime(2026, 4, 20, 21, 6, 7, tzinfo=timezone.utc)
    now_calls: list[timezone] = []
    capture_dir = tmp_path / "captures"

    class FakeDateTime:
        @classmethod
        def now(cls, tz):
            now_calls.append(tz)
            return first_capture_at

    class App:
        app_settings = SimpleNamespace(
            diagnostics=SimpleNamespace(responsiveness_capture_dir=str(capture_dir))
        )

    monkeypatch.setattr(diagnostics_module, "datetime", FakeDateTime)
    monkeypatch.setattr(
        diagnostics_module.faulthandler,
        "dump_traceback",
        lambda *, file, all_threads: file.write(f"TRACEBACK all_threads={all_threads}\n"),
    )

    diagnostics_module._capture_responsiveness_watchdog_evidence(
        app=App(),
        app_log=SimpleNamespace(error=lambda *args: None, warning=lambda *args: None),
        error_log_path=tmp_path / "yoyopod_errors.log",
        decision=ResponsivenessWatchdogDecision(
            reason="coordinator_stall_after_input",
            suspected_scope="input_to_runtime_handoff",
            summary="input kept moving but the coordinator stalled",
        ),
        status={"state": "menu"},
    )

    snapshot_path = next(capture_dir.glob("*.json"))
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert now_calls == [timezone.utc]
    assert payload["captured_at"] == first_capture_at.isoformat()
    assert snapshot_path.stem == (
        f"{first_capture_at.strftime('%Y%m%dT%H%M%SZ')}-coordinator_stall_after_input"
    )


def test_install_traceback_dump_handlers_registers_faulthandler_chain(
    monkeypatch,
    tmp_path,
) -> None:
    """Traceback dumps should chain onto the existing screenshot signal handlers."""

    if not all(hasattr(signal, name) for name in ("SIGUSR1", "SIGUSR2")):
        pytest.skip("screenshot dump signals are unavailable on this platform")

    register_calls: list[tuple[int, bool, bool]] = []
    unregister_calls: list[int] = []
    logs: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        diagnostics_module.faulthandler,
        "register",
        lambda signum, *, file, all_threads, chain: register_calls.append(
            (signum, all_threads, chain)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        diagnostics_module.faulthandler,
        "unregister",
        lambda signum: unregister_calls.append(signum),
        raising=False,
    )
    fake_log = SimpleNamespace(
        info=lambda *args: logs.append(("info", args)),
        warning=lambda *args: logs.append(("warning", args)),
    )

    dump_stream, installed = diagnostics_module._install_traceback_dump_handlers(
        signals=(signal.SIGUSR1, signal.SIGUSR2),
        dump_path=tmp_path / "yoyopod_errors.log",
        app_log=fake_log,
    )

    assert installed == (signal.SIGUSR1, signal.SIGUSR2)
    assert register_calls == [
        (signal.SIGUSR1, True, True),
        (signal.SIGUSR2, True, True),
    ]
    assert dump_stream is not None
    assert dump_stream.closed is False

    diagnostics_module._uninstall_traceback_dump_handlers(
        signals=installed,
        dump_stream=dump_stream,
    )

    assert unregister_calls == [signal.SIGUSR1, signal.SIGUSR2]
    assert dump_stream.closed is True


def test_main_restores_previous_signal_handlers_before_stop(monkeypatch) -> None:
    """Main should restore SIGTERM and screenshot handlers during teardown."""

    if not all(hasattr(signal, name) for name in ("SIGUSR1", "SIGUSR2")):
        pytest.skip("screenshot dump signals are unavailable on this platform")

    events: list[tuple[object, ...]] = []
    previous_handlers = {
        signal.SIGTERM: object(),
        signal.SIGUSR1: object(),
        signal.SIGUSR2: object(),
    }
    current_handlers = dict(previous_handlers)

    class FakeApp:
        app_settings = SimpleNamespace(
            diagnostics=SimpleNamespace(responsiveness_watchdog_enabled=False)
        )

        def __init__(self, *, config_dir: str, simulate: bool) -> None:
            assert config_dir == "config"
            assert simulate is False

        def setup(self) -> bool:
            return True

        def get_status(self, refresh_output_volume: bool = False) -> dict[str, object]:
            return {
                "auto_resume": False,
                "voip_available": True,
                "music_available": True,
            }

        def run(self) -> None:
            events.append(("run",))

        def stop(self) -> None:
            events.append(("stop",))

    def fake_getsignal(signum: int) -> object:
        return current_handlers[signum]

    def fake_signal(signum: int, handler: object) -> None:
        events.append(("signal", signum, handler))
        current_handlers[signum] = handler

    monkeypatch.setattr(
        main_module,
        "configure_logger",
        lambda: SimpleNamespace(pid_file="/tmp/yoyopod.pid", error_log_file="/tmp/errors.log"),
    )
    monkeypatch.setattr(
        main_module,
        "get_subsystem_logger",
        lambda _name: SimpleNamespace(
            info=lambda *args: None,
            error=lambda *args: None,
            warning=lambda *args: None,
        ),
    )
    monkeypatch.setattr(main_module, "write_pid_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "log_startup", lambda **_kwargs: None)
    monkeypatch.setattr(main_module, "log_shutdown", lambda **_kwargs: None)
    monkeypatch.setattr(main_module, "remove_pid_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "YoyoPodApp", FakeApp)
    monkeypatch.setattr(main_module.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(main_module.signal, "signal", fake_signal)
    monkeypatch.setattr(
        main_module,
        "_install_traceback_dump_handlers",
        lambda **_kwargs: (None, (signal.SIGUSR1, signal.SIGUSR2)),
    )
    monkeypatch.setattr(
        main_module,
        "_uninstall_traceback_dump_handlers",
        lambda **_kwargs: events.append(("uninstall_traceback_handlers",)),
    )

    assert main_module.main() == 0

    signal_calls = [event for event in events if event[:1] == ("signal",)]
    assert signal_calls[-3:] == [
        ("signal", signal.SIGTERM, previous_handlers[signal.SIGTERM]),
        ("signal", signal.SIGUSR1, previous_handlers[signal.SIGUSR1]),
        ("signal", signal.SIGUSR2, previous_handlers[signal.SIGUSR2]),
    ]
    assert events.index(signal_calls[-1]) < events.index(("stop",))


def test_main_setup_failure_mentions_network_config_file(monkeypatch) -> None:
    """Startup guidance should mention the canonical network config file."""

    error_logs: list[tuple[object, ...]] = []
    stop_calls: list[str] = []
    fake_log = SimpleNamespace(
        info=lambda *args: None,
        error=lambda *args: error_logs.append(args),
        warning=lambda *args: None,
    )

    class FakeApp:
        app_settings = None

        def __init__(self, *, config_dir: str, simulate: bool) -> None:
            assert config_dir == "config"
            assert simulate is False

        def setup(self) -> bool:
            return False

        def stop(self) -> None:
            stop_calls.append("stop")

    monkeypatch.setattr(
        main_module,
        "configure_logger",
        lambda: SimpleNamespace(pid_file="/tmp/yoyopod.pid", error_log_file="/tmp/errors.log"),
    )
    monkeypatch.setattr(main_module, "get_subsystem_logger", lambda _name: fake_log)
    monkeypatch.setattr(main_module, "write_pid_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "log_startup", lambda **_kwargs: None)
    monkeypatch.setattr(main_module, "log_shutdown", lambda **_kwargs: None)
    monkeypatch.setattr(main_module, "remove_pid_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "YoyoPodApp", FakeApp)

    assert main_module.main() == 1
    assert stop_calls == ["stop"]
    assert ("  - config/network/cellular.yaml exists",) in error_logs
