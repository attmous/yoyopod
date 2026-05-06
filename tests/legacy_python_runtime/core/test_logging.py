"""Tests for the centralized YoYoPod logging helpers."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from yoyopod.config.models import AppLoggingConfig
from yoyopod.core.logging import (
    LoggingRuntimeConfig,
    build_logging_runtime_config,
    get_subsystem_logger,
    infer_subsystem,
    init_logger,
    remove_pid_file,
    write_pid_file,
)


def test_build_logging_runtime_config_resolves_relative_paths(tmp_path: Path) -> None:
    """Relative logging paths should resolve against the project root."""

    config = AppLoggingConfig(
        file="logs/main.log",
        error_file="logs/errors.log",
        pid_file="run/yoyopod.pid",
    )

    runtime = build_logging_runtime_config(config, base_dir=tmp_path)

    assert runtime.log_file == (tmp_path / "logs" / "main.log").resolve()
    assert runtime.error_log_file == (tmp_path / "logs" / "errors.log").resolve()
    assert runtime.pid_file == (tmp_path / "run" / "yoyopod.pid").resolve()


def test_init_logger_writes_structured_main_and_error_logs(tmp_path: Path) -> None:
    """Main and error log sinks should receive immediate structured output."""

    runtime = LoggingRuntimeConfig(
        level="DEBUG",
        log_file=tmp_path / "yoyopod.log",
        error_log_file=tmp_path / "yoyopod_errors.log",
        pid_file=tmp_path / "yoyopod.pid",
        diagnose=False,
    )

    init_logger(config=runtime, console=False, file_logging=True, announce=False)

    get_subsystem_logger("voip").info("Placed test call")
    logger.error("Simulated failure")

    main_log = runtime.log_file.read_text(encoding="utf-8")
    error_log = runtime.error_log_file.read_text(encoding="utf-8")

    assert "voip" in main_log
    assert "Placed test call" in main_log
    assert "ERROR" in main_log
    assert "Simulated failure" in error_log


def test_pid_file_helpers_create_and_cleanup_file(tmp_path: Path) -> None:
    """PID helpers should support deterministic process bookkeeping."""

    pid_file = tmp_path / "yoyopod.pid"

    write_pid_file(pid_file, pid=4242)

    assert pid_file.read_text(encoding="utf-8").strip() == "4242"

    remove_pid_file(pid_file)

    assert not pid_file.exists()


def test_infer_subsystem_maps_core_packages() -> None:
    """Subsystem inference should keep logs grep-friendly by package area."""

    assert infer_subsystem("yoyopod.integrations.call.manager") == "comm"
    assert infer_subsystem("yoyopod.ui.screens.manager") == "ui"
    assert infer_subsystem("yoyopod.core.bus") == "core"
    assert infer_subsystem("yoyopod.main") == "app"
