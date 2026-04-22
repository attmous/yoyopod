from __future__ import annotations

from collections.abc import Callable
import os
import signal
import sys
from pathlib import Path
from types import FrameType
from typing import TextIO

from loguru import logger

from yoyopod import __version__
from yoyopod.app import YoyoPodApp
from yoyopod.config import YoyoPodConfig, load_composed_app_settings
from yoyopod.core.diagnostics.watchdog import (
    ResponsivenessWatchdog,
    _capture_responsiveness_watchdog_evidence,
    _install_traceback_dump_handlers,
    _log_setup_failure_guidance,
    _log_signal_snapshot,
    _signal_name,
    _uninstall_traceback_dump_handlers,
)
from yoyopod.ui.display.screenshot import _request_screenshot_capture
from yoyopod.core.logging import (
    LoggingRuntimeConfig,
    build_logging_runtime_config,
    get_subsystem_logger,
    init_logger,
    log_shutdown,
    log_startup,
    remove_pid_file,
    write_pid_file,
)

SignalHandler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None


def load_app_settings(config_dir: str = "config") -> YoyoPodConfig:
    try:
        return load_composed_app_settings(config_dir)
    except Exception:
        return YoyoPodConfig()


def configure_logger(config_dir: str = "config") -> LoggingRuntimeConfig:
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


def main() -> int:
    logging_config = configure_logger()
    app_log = get_subsystem_logger("app")

    simulate = "--simulate" in sys.argv
    pid = os.getpid()
    startup_logged = False
    traceback_dump_stream: TextIO | None = None
    registered_traceback_signals: tuple[int, ...] = ()
    responsiveness_watchdog: ResponsivenessWatchdog | None = None
    previous_screenshot_handlers: dict[int, SignalHandler] = {}

    write_pid_file(logging_config.pid_file, pid)

    try:
        log_startup(version=__version__, pid=pid, runtime=logging_config)
        startup_logged = True

        if simulate:
            app_log.info(
                "\n".join(
                    (
                        "=" * 60,
                        "SIMULATION MODE",
                        "Running without physical hardware",
                        "Web server will start on http://localhost:5000",
                        "Open the URL in your browser to view the display",
                        "Use keyboard (Arrow keys, Enter, Esc) or browser controls for input",
                        "=" * 60,
                    )
                )
            )

        app_log.info("Initializing YoyoPod...")
        app = YoyoPodApp(config_dir="config", simulate=simulate)

        if not app.setup():
            app_log.error("Failed to setup application")
            _log_setup_failure_guidance(app_log)
            app.stop()
            return 1

        app_log.info("")
        app_log.info(
            "\n".join(
                (
                    "=" * 60,
                    "YoyoPod Ready!",
                    "=" * 60,
                    "",
                    "Available Features:",
                    "  - Local music playback (mpv)",
                    "  - VoIP calling and messaging (Liblinphone)",
                    "  - Auto-pause music on calls",
                    "  - Auto-resume after calls",
                    "  - Voice-note recording and delivery",
                    "  - Full UI navigation",
                    "",
                    "Current Configuration:",
                )
            )
        )
        status = app.get_status(refresh_output_volume=True)
        app_log.info(
            "\n".join(
                (
                    f"  Auto-resume: {status['auto_resume']}",
                    f"  VoIP available: {status['voip_available']}",
                    f"  Music available: {status['music_available']}",
                    "",
                    "Press Ctrl+C to exit",
                    "=" * 60,
                    "",
                )
            )
        )

        def handle_shutdown_signal(signum: int, _frame: FrameType | None) -> None:
            signal_name = _signal_name(signum)
            app_log.info(f"Received {signal_name}, shutting down...")
            raise KeyboardInterrupt

        previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, handle_shutdown_signal)

        screenshot_path = "/tmp/yoyopod_screenshot.png"
        sigusr1 = getattr(signal, "SIGUSR1", None)
        sigusr2 = getattr(signal, "SIGUSR2", None)
        if sigusr1 is not None and sigusr2 is not None:
            previous_screenshot_handlers = {
                sigusr1: signal.getsignal(sigusr1),
                sigusr2: signal.getsignal(sigusr2),
            }

            def handle_screenshot_default(_signum: int, _frame: FrameType | None) -> None:
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
                "Screenshot handlers installed (SIGUSR1=default/readback-first, "
                "SIGUSR2=legacy shadow-first) -> {}",
                screenshot_path,
            )

        diagnostics = app.app_settings.diagnostics if app.app_settings is not None else None
        if diagnostics is not None and diagnostics.responsiveness_watchdog_enabled and not simulate:
            responsiveness_watchdog = ResponsivenessWatchdog(
                status_provider=app.get_status,
                capture_callback=lambda decision, status: _capture_responsiveness_watchdog_evidence(
                    app=app,
                    app_log=app_log,
                    error_log_path=logging_config.error_log_file,
                    decision=decision,
                    status=status,
                ),
                stall_threshold_seconds=diagnostics.responsiveness_stall_threshold_seconds,
                recent_input_window_seconds=(
                    diagnostics.responsiveness_recent_input_window_seconds
                ),
                poll_interval_seconds=(diagnostics.responsiveness_watchdog_poll_interval_seconds),
                capture_cooldown_seconds=(diagnostics.responsiveness_capture_cooldown_seconds),
            )
            responsiveness_watchdog.start()

        exit_code = 0
        try:
            app.run()
        except KeyboardInterrupt:
            app_log.info("Shutdown requested by signal or keyboard interrupt")
        except Exception:
            logger.exception("Unhandled exception escaped the YoyoPod main loop")
            exit_code = 1
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
            for signum, previous_handler in previous_screenshot_handlers.items():
                signal.signal(signum, previous_handler)
            if responsiveness_watchdog is not None:
                responsiveness_watchdog.stop()
            _uninstall_traceback_dump_handlers(
                signals=registered_traceback_signals,
                dump_stream=traceback_dump_stream,
            )
            app.stop()

        app_log.info("Goodbye!")
        return exit_code
    finally:
        if startup_logged:
            log_shutdown(pid=pid)
        remove_pid_file(logging_config.pid_file)
