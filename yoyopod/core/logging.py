"""Centralized Loguru configuration and runtime logging helpers for YoyoPod."""

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, TextIO

from loguru import logger

if TYPE_CHECKING:
    from yoyopod.config.models import AppLoggingConfig


DEFAULT_SUBSYSTEM = "app"
STARTUP_MARKER = "YoyoPod starting"
SHUTDOWN_MARKER = "YoyoPod shutting down"
CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{extra[subsystem]:<6}</cyan> | "
    "<level>{name}:{function}:{line}</level> | "
    "<level>{message}</level>"
)
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level:<8} | "
    "{extra[subsystem]:<6} | "
    "{name}:{function}:{line} | "
    "{message}"
)
_SUBSYSTEM_OVERRIDES = {
    "yoyopod.integrations.call": "comm",
    "yoyopod.backends.voip": "comm",
    "yoyopod.integrations.music": "music",
    "yoyopod.backends.music": "music",
    "yoyopod.core.audio_volume": "music",
    "yoyopod.core.app_state": "coord",
    "yoyopod.integrations.call.runtime": "coord",
    "yoyopod.integrations.music.runtime": "coord",
    "yoyopod.integrations.voice.runtime": "coord",
    "yoyopod.integrations.voice.executor": "coord",
    "yoyopod.integrations.voice.settings": "coord",
    "yoyopod.ui": "ui",
    "yoyopod.integrations.power": "power",
    "yoyopod.backends.power": "power",
    "yoyopod.config": "config",
}


@dataclass(slots=True)
class LoggingRuntimeConfig:
    """Resolved runtime logging settings used by the entrypoint."""

    level: str = "INFO"
    log_file: Path = Path("logs/yoyopod.log")
    error_log_file: Path = Path("logs/yoyopod_errors.log")
    pid_file: Path = Path("/tmp/yoyopod.pid")
    rotation: str = "5 MB"
    retention: str = "3 days"
    compression: str = "gz"
    error_rotation: str = "2 MB"
    error_retention: str = "7 days"
    encoding: str = "utf-8"
    enqueue: bool = False
    backtrace: bool = True
    diagnose: bool = True


class InterceptHandler(logging.Handler):
    """Route stdlib logging records into Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.bind(subsystem=infer_subsystem(record.name)).opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, record.getMessage())


def infer_subsystem(module_name: str | None) -> str:
    """Infer a stable subsystem tag from the module/logger name."""

    if not module_name:
        return DEFAULT_SUBSYSTEM

    for prefix, subsystem in _SUBSYSTEM_OVERRIDES.items():
        if module_name.startswith(prefix):
            return subsystem

    if module_name in {"yoyopod.app", "yoyopod.main"}:
        return "app"
    if module_name == "yoyopod.core" or module_name.startswith("yoyopod.core."):
        return "core"
    return DEFAULT_SUBSYSTEM


def get_subsystem_logger(subsystem: str) -> Any:
    """Return a logger bound to the provided subsystem."""

    return logger.bind(subsystem=subsystem)


def build_logging_runtime_config(
    app_logging_config: "AppLoggingConfig | None" = None,
    *,
    base_dir: Path | None = None,
) -> LoggingRuntimeConfig:
    """Resolve typed logging settings into concrete runtime paths."""

    root_dir = (base_dir or Path.cwd()).resolve()

    if app_logging_config is None:
        return LoggingRuntimeConfig(
            log_file=root_dir / "logs" / "yoyopod.log",
            error_log_file=root_dir / "logs" / "yoyopod_errors.log",
            pid_file=Path("/tmp/yoyopod.pid"),
        )

    return LoggingRuntimeConfig(
        level=app_logging_config.level,
        log_file=_resolve_log_path(app_logging_config.file, root_dir),
        error_log_file=_resolve_log_path(app_logging_config.error_file, root_dir),
        pid_file=_resolve_log_path(app_logging_config.pid_file, root_dir),
        rotation=app_logging_config.rotation,
        retention=app_logging_config.retention,
        compression=app_logging_config.compression,
        error_rotation=app_logging_config.error_rotation,
        error_retention=app_logging_config.error_retention,
        encoding=app_logging_config.encoding,
        enqueue=app_logging_config.enqueue,
        backtrace=app_logging_config.backtrace,
        diagnose=app_logging_config.diagnose,
    )


def init_logger(
    *,
    config: LoggingRuntimeConfig | None = None,
    level: str = "INFO",
    console: bool = True,
    file_logging: bool = True,
    console_stream: Optional[TextIO] = None,
    announce: bool = True,
) -> LoggingRuntimeConfig:
    """
    Initialize Loguru for the YoyoPod application.

    Args:
        config: Fully resolved runtime logging configuration.
        level: Console/file threshold used when `config` is omitted.
        console: Enable console output.
        file_logging: Enable file sinks.
        console_stream: Stream for console output.
        announce: Emit a one-line logger readiness message.
    """

    runtime = config or LoggingRuntimeConfig(level=level)
    runtime.level = level if config is None else runtime.level

    logger.remove()
    logger.configure(
        extra={"subsystem": DEFAULT_SUBSYSTEM},
        patcher=_patch_record,
    )

    if console:
        if console_stream is None:
            console_stream = sys.stderr
        logger.add(
            console_stream,
            format=CONSOLE_FORMAT,
            level=runtime.level,
            colorize=True,
            backtrace=runtime.backtrace,
            diagnose=runtime.diagnose,
            enqueue=False,
        )

    if file_logging:
        runtime.log_file.parent.mkdir(parents=True, exist_ok=True)
        runtime.error_log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            runtime.log_file,
            format=FILE_FORMAT,
            level=runtime.level,
            rotation=runtime.rotation,
            retention=runtime.retention,
            compression=runtime.compression,
            encoding=runtime.encoding,
            enqueue=runtime.enqueue,
            backtrace=runtime.backtrace,
            diagnose=runtime.diagnose,
        )
        logger.add(
            runtime.error_log_file,
            format=FILE_FORMAT,
            level="ERROR",
            rotation=runtime.error_rotation,
            retention=runtime.error_retention,
            compression=runtime.compression,
            encoding=runtime.encoding,
            enqueue=runtime.enqueue,
            backtrace=runtime.backtrace,
            diagnose=runtime.diagnose,
        )

    _install_stdlib_logging_intercept()
    _install_exception_hooks()

    if announce:
        get_subsystem_logger("app").info(
            "Logger ready (level={}, main_log={}, error_log={})",
            runtime.level,
            runtime.log_file,
            runtime.error_log_file,
        )

    return runtime


def write_pid_file(pid_file: Path, pid: int | None = None) -> None:
    """Persist the current process ID to the configured PID file."""

    resolved_pid_file = pid_file.expanduser()
    resolved_pid_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_pid_file.write_text(f"{pid or os.getpid()}\n", encoding="utf-8")
    atexit.register(remove_pid_file, resolved_pid_file)


def remove_pid_file(pid_file: Path) -> None:
    """Best-effort cleanup of the PID file on shutdown."""

    pid_file.expanduser().unlink(missing_ok=True)


def log_startup(*, version: str, pid: int, runtime: LoggingRuntimeConfig) -> None:
    """Emit the canonical application startup marker."""

    app_log = get_subsystem_logger("app")
    app_log.info("===== {} (version={}, pid={}) =====", STARTUP_MARKER, version, pid)
    app_log.info(
        "Logging contract active (main_log={}, error_log={}, pid_file={})",
        runtime.log_file,
        runtime.error_log_file,
        runtime.pid_file,
    )


def log_shutdown(*, pid: int) -> None:
    """Emit the canonical application shutdown marker."""

    get_subsystem_logger("app").info("===== {} (pid={}) =====", SHUTDOWN_MARKER, pid)


def get_logger() -> Any:
    """Return the configured Loguru logger instance."""

    return logger


def _resolve_log_path(path_value: str, base_dir: Path) -> Path:
    """Resolve config paths relative to the working tree when needed."""

    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _patch_record(record: dict) -> None:
    """Attach derived context to every emitted log record."""

    extra = record["extra"]
    if not extra.get("subsystem"):
        extra["subsystem"] = infer_subsystem(record["name"])


def _install_stdlib_logging_intercept() -> None:
    """Forward stdlib logging into Loguru's configured sinks."""

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


def _install_exception_hooks() -> None:
    """Ensure uncaught exceptions are logged with a full traceback."""

    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        get_subsystem_logger("app").opt(
            exception=(exc_type, exc_value, exc_traceback)
        ).critical("Unhandled exception reached sys.excepthook")

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is KeyboardInterrupt:
            return
        get_subsystem_logger("app").bind(thread=args.thread.name if args.thread else "unknown").opt(
            exception=(args.exc_type, args.exc_value, args.exc_traceback)
        ).critical("Unhandled exception reached threading.excepthook")

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
