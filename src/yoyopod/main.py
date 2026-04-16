"""
Package entry point for YoyoPod.

This module provides the console-script target used by `pyproject.toml`
and keeps the installed entry point aligned with the top-level launcher.
"""

from __future__ import annotations

import faulthandler
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any, TextIO

from loguru import logger

from yoyopod import __version__
from yoyopod.app import YoyoPodApp
from yoyopod.config.models import YoyoPodConfig, load_config_model_from_yaml
from yoyopod.utils.logger import (
    LoggingRuntimeConfig,
    build_logging_runtime_config,
    get_subsystem_logger,
    init_logger,
    log_shutdown,
    log_startup,
    remove_pid_file,
    write_pid_file,
)


def _capture_screenshot(
    *,
    adapter: object | None,
    screenshot_path: str,
    app_log: Any,
    prefer_readback: bool,
) -> bool:
    """Capture a screenshot using readback-first or shadow-first fallback order."""

    if adapter is None:
        app_log.warning("Screenshot not available — no active display adapter")
        return False

    ordered_methods = (
        (
            ("save_screenshot_readback", "LVGL readback"),
            ("save_screenshot", "shadow buffer"),
        )
        if prefer_readback
        else (
            ("save_screenshot", "shadow buffer"),
            ("save_screenshot_readback", "LVGL readback"),
        )
    )

    for method_name, label in ordered_methods:
        save_fn = getattr(adapter, method_name, None)
        if not callable(save_fn):
            continue
        try:
            if save_fn(screenshot_path):
                app_log.info("Saved screenshot via {} -> {}", label, screenshot_path)
                return True
        except Exception:
            logger.exception("Screenshot capture failed via {}", label)
            return False

    app_log.warning("Screenshot not available — adapter does not expose a usable capture method")
    return False


def _request_screenshot_capture(
    *,
    app: object,
    screenshot_path: str,
    app_log: Any,
    prefer_readback: bool,
) -> None:
    """Queue screenshot capture onto the app loop when possible."""

    def capture_on_app_loop() -> None:
        display = getattr(app, "display", None)
        adapter = None
        if display is not None:
            get_adapter = getattr(display, "get_adapter", None)
            if callable(get_adapter):
                adapter = get_adapter()
            else:
                adapter = getattr(display, "_adapter", None)

        should_reset_shadow_sync = False
        if adapter is not None and hasattr(adapter, "_force_shadow_buffer_sync"):
            setattr(adapter, "_force_shadow_buffer_sync", True)
            should_reset_shadow_sync = True

        try:
            screen_manager = getattr(app, "screen_manager", None)
            refresh_current_screen = (
                getattr(screen_manager, "refresh_current_screen", None)
                if screen_manager is not None
                else None
            )
            if callable(refresh_current_screen):
                refresh_current_screen()

            get_ui_backend = getattr(display, "get_ui_backend", None)
            if callable(get_ui_backend):
                ui_backend = get_ui_backend()
                force_refresh = (
                    getattr(ui_backend, "force_refresh", None) if ui_backend is not None else None
                )
                if callable(force_refresh):
                    force_refresh()

            _capture_screenshot(
                adapter=adapter,
                screenshot_path=screenshot_path,
                app_log=app_log,
                prefer_readback=prefer_readback,
            )
        finally:
            if should_reset_shadow_sync:
                setattr(adapter, "_force_shadow_buffer_sync", False)

    queue_callback = getattr(app, "_queue_main_thread_callback", None)
    if callable(queue_callback):
        queue_callback(capture_on_app_loop)
        app_log.info(
            "Queued screenshot capture request ({})",
            "readback-first" if prefer_readback else "shadow-first",
        )
        return

    capture_on_app_loop()


def load_app_settings(config_dir: str = "config") -> YoyoPodConfig:
    """Load app settings early enough to configure logging before app setup."""

    config_path = Path(config_dir) / "yoyopod_config.yaml"
    try:
        return load_config_model_from_yaml(YoyoPodConfig, config_path)
    except Exception:
        return YoyoPodConfig()


def configure_logger(config_dir: str = "config") -> LoggingRuntimeConfig:
    """Configure the shared logger using typed logging settings."""

    settings = load_app_settings(config_dir)
    logging_config = build_logging_runtime_config(
        settings.logging,
        base_dir=Path.cwd(),
    )
    return init_logger(
        config=logging_config,
        console=True,
        file_logging=True,
        console_stream=sys.stderr,
        announce=False,
    )


def _signal_name(signum: int) -> str:
    """Return a stable signal name for diagnostics."""

    try:
        return signal.Signals(signum).name
    except ValueError:
        return str(signum)


def _json_safe(value: object) -> object:
    """Normalize runtime state into JSON-safe values for log snapshots."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            pass
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _log_signal_snapshot(
    *,
    app: object,
    app_log: Any,
    signal_name: str,
    prefer_readback: bool,
) -> None:
    """Emit one structured runtime snapshot to the error log on demand."""

    payload: dict[str, object] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_mode": "readback-first" if prefer_readback else "shadow-first",
        "signal": signal_name,
    }
    get_status = getattr(app, "get_status", None)
    if callable(get_status):
        try:
            payload["status"] = _json_safe(get_status())
        except Exception as exc:
            payload["status_error"] = str(exc)
    else:
        payload["status_error"] = "app does not expose get_status()"

    app_log.error("Freeze diagnostics snapshot: {}", json.dumps(payload, sort_keys=True))


def _install_traceback_dump_handlers(
    *,
    signals: tuple[int, ...],
    dump_path: Path,
    app_log: Any,
) -> tuple[TextIO | None, tuple[int, ...]]:
    """Chain all-thread traceback dumps onto the screenshot signals."""

    if not signals:
        return None, ()

    dump_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        dump_stream = dump_path.open("a", encoding="utf-8", buffering=1)
    except OSError as exc:
        app_log.warning("Failed to open traceback dump log {}: {}", dump_path, exc)
        return None, ()

    installed: list[int] = []
    for signum in signals:
        try:
            faulthandler.register(signum, file=dump_stream, all_threads=True, chain=True)
        except (OSError, RuntimeError, ValueError) as exc:
            app_log.warning(
                "Failed to arm traceback dump for {}: {}",
                _signal_name(signum),
                exc,
            )
            continue
        installed.append(signum)

    if not installed:
        dump_stream.close()
        return None, ()

    app_log.info(
        "Freeze traceback dumps armed for {} -> {}",
        ", ".join(_signal_name(signum) for signum in installed),
        dump_path,
    )
    return dump_stream, tuple(installed)


def _uninstall_traceback_dump_handlers(
    *,
    signals: tuple[int, ...],
    dump_stream: TextIO | None,
) -> None:
    """Best-effort faulthandler cleanup on process exit."""

    for signum in signals:
        try:
            faulthandler.unregister(signum)
        except (OSError, RuntimeError, ValueError):
            continue

    if dump_stream is not None:
        dump_stream.close()


def main() -> int:
    """Run the integrated YoyoPod application."""
    logging_config = configure_logger()
    app_log = get_subsystem_logger("app")

    simulate = "--simulate" in sys.argv
    pid = os.getpid()
    startup_logged = False
    traceback_dump_stream: TextIO | None = None
    registered_traceback_signals: tuple[int, ...] = ()

    write_pid_file(logging_config.pid_file, pid)

    try:
        log_startup(version=__version__, pid=pid, runtime=logging_config)
        startup_logged = True

        if simulate:
            app_log.info("=" * 60)
            app_log.info("SIMULATION MODE")
            app_log.info("Running without physical hardware")
            app_log.info("Web server will start on http://localhost:5000")
            app_log.info("Open the URL in your browser to view the display")
            app_log.info("Use keyboard (Arrow keys, Enter, Esc) or web buttons for input")
            app_log.info("=" * 60)

        app_log.info("Initializing YoyoPod...")
        app = YoyoPodApp(config_dir="config", simulate=simulate)

        if not app.setup():
            app_log.error("Failed to setup application")
            app_log.error("Check that:")
            app_log.error("  - config/voip_config.yaml exists")
            app_log.error("  - config/contacts.yaml exists")
            app_log.error("  - liblinphone is installed and the native shim is built")
            app_log.error("  - mpv is installed and the configured music backend can start")
            app.stop()
            return 1

        app_log.info("")
        app_log.info("=" * 60)
        app_log.info("YoyoPod Ready!")
        app_log.info("=" * 60)
        app_log.info("")
        app_log.info("Available Features:")
        app_log.info("  - Local music playback (mpv)")
        app_log.info("  - VoIP calling and messaging (Liblinphone)")
        app_log.info("  - Auto-pause music on calls")
        app_log.info("  - Auto-resume after calls")
        app_log.info("  - Voice-note recording and delivery")
        app_log.info("  - Full UI navigation")
        app_log.info("")
        app_log.info("Current Configuration:")
        status = app.get_status()
        app_log.info(f"  Auto-resume: {status['auto_resume']}")
        app_log.info(f"  VoIP available: {status['voip_available']}")
        app_log.info(f"  Music available: {status['music_available']}")
        app_log.info("")
        app_log.info("Press Ctrl+C to exit")
        app_log.info("=" * 60)
        app_log.info("")

        def handle_shutdown_signal(signum: int, _frame: FrameType | None) -> None:
            signal_name = signal.Signals(signum).name
            app_log.info(f"Received {signal_name}, shutting down...")
            raise KeyboardInterrupt

        previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, handle_shutdown_signal)

        # Screenshot signal handlers (Unix only — SIGUSR1/SIGUSR2 unavailable on Windows).
        screenshot_path = "/tmp/yoyopod_screenshot.png"
        sigusr1 = getattr(signal, "SIGUSR1", None)
        sigusr2 = getattr(signal, "SIGUSR2", None)
        if sigusr1 is not None and sigusr2 is not None:

            def handle_screenshot_default(_signum: int, _frame: FrameType | None) -> None:
                """SIGUSR1: save a screenshot using readback-first capture."""
                _log_signal_snapshot(
                    app=app,
                    app_log=app_log,
                    signal_name=_signal_name(sigusr1),
                    prefer_readback=True,
                )
                _request_screenshot_capture(
                    app=app,
                    screenshot_path=screenshot_path,
                    app_log=app_log,
                    prefer_readback=True,
                )

            def handle_screenshot_legacy_shadow(_signum: int, _frame: FrameType | None) -> None:
                """SIGUSR2: save a screenshot using shadow-first capture for debugging."""
                _log_signal_snapshot(
                    app=app,
                    app_log=app_log,
                    signal_name=_signal_name(sigusr2),
                    prefer_readback=False,
                )
                _request_screenshot_capture(
                    app=app,
                    screenshot_path=screenshot_path,
                    app_log=app_log,
                    prefer_readback=False,
                )

            signal.signal(sigusr1, handle_screenshot_default)
            signal.signal(sigusr2, handle_screenshot_legacy_shadow)
            traceback_dump_stream, registered_traceback_signals = _install_traceback_dump_handlers(
                signals=(sigusr1, sigusr2),
                dump_path=logging_config.error_log_file,
                app_log=app_log,
            )
            app_log.info(
                "Screenshot handlers installed (SIGUSR1=default/readback-first, SIGUSR2=legacy shadow-first) -> {}",
                screenshot_path,
            )

        exit_code = 0
        try:
            app.run()
        except KeyboardInterrupt:
            app_log.info("Shutdown requested by signal or keyboard interrupt")
        except Exception:
            logger.exception("Unhandled exception escaped the YoyoPod main loop")
            exit_code = 1
        finally:
            _uninstall_traceback_dump_handlers(
                signals=registered_traceback_signals,
                dump_stream=traceback_dump_stream,
            )
            signal.signal(signal.SIGTERM, previous_sigterm)
            app.stop()

        app_log.info("Goodbye!")
        return exit_code
    finally:
        if startup_logged:
            log_shutdown(pid=pid)
        remove_pid_file(logging_config.pid_file)
