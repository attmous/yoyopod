"""System validation subcommand."""

from __future__ import annotations

import platform
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from yoyopod_cli.pi.validate._common import (
    _CheckResult,
    _load_app_config,
    _print_summary,
)
from yoyopod_cli.common import configure_logging, resolve_config_dir


def _environment_check() -> _CheckResult:
    """Capture the current execution environment."""
    system = platform.system()
    machine = platform.machine()
    python_version = platform.python_version()

    if system == "Linux" and ("arm" in machine.lower() or "aarch" in machine.lower()):
        status = "pass"
    else:
        status = "warn"

    return _CheckResult(
        name="environment",
        status=status,
        details=f"system={system}, machine={machine}, python={python_version}",
    )


def _display_check(
    app_config: dict[str, Any],
    hold_seconds: float,
) -> tuple[_CheckResult, Any]:
    """Validate display initialization on target hardware."""
    from yoyopod.ui.display import Display, detect_hardware
    from yoyopod.ui.lvgl_binding.binding import LvglBinding

    def _render_lvgl_probe(display: Any, ui_backend: Any) -> None:
        if not ui_backend.initialize():
            raise RuntimeError("LVGL backend failed to initialize during smoke validation")

        ui_backend.show_probe_scene(LvglBinding.SCENE_CARD)
        ui_backend.force_refresh()
        ui_backend.pump(16)

        refresh_backend_kind = getattr(display, "refresh_backend_kind", None)
        if callable(refresh_backend_kind):
            refresh_backend_kind()

        if hold_seconds <= 0:
            return

        remaining_seconds = hold_seconds
        while remaining_seconds > 0:
            slice_seconds = min(0.05, remaining_seconds)
            time.sleep(slice_seconds)
            ui_backend.pump(max(1, int(slice_seconds * 1000)))
            remaining_seconds -= slice_seconds

    requested_hardware = str(app_config.get("display", {}).get("hardware", "auto")).lower()
    resolved_hardware = detect_hardware() if requested_hardware == "auto" else requested_hardware

    if resolved_hardware == "simulation":
        return (
            _CheckResult(
                name="display",
                status="fail",
                details=(
                    "hardware detection resolved to simulation; "
                    "no supported Raspberry Pi display hardware was found"
                ),
            ),
            None,
        )

    display = None
    try:
        display = Display(hardware=resolved_hardware, simulate=False)
        adapter = display.get_adapter()
        ui_backend = display.get_ui_backend()

        if ui_backend is not None:
            _render_lvgl_probe(display, ui_backend)
        else:
            display.clear(display.COLOR_BLACK)
            display.text("YoYoPod Pi smoke", 10, 40, color=display.COLOR_WHITE, font_size=18)
            display.text("Display OK", 10, 75, color=display.COLOR_GREEN, font_size=18)
            display.update()

            if hold_seconds > 0:
                time.sleep(hold_seconds)

        if display.simulate:
            return (
                _CheckResult(
                    name="display",
                    status="fail",
                    details=(
                        f"adapter {adapter.__class__.__name__} fell back to simulation "
                        "instead of hardware mode"
                    ),
                ),
                display,
            )

        return (
            _CheckResult(
                name="display",
                status="pass",
                details=(
                    f"adapter={adapter.__class__.__name__}, "
                    f"backend={display.backend_kind}, "
                    f"size={display.WIDTH}x{display.HEIGHT}, "
                    f"orientation={display.ORIENTATION}, "
                    f"requested={requested_hardware}, resolved={resolved_hardware}"
                ),
            ),
            display,
        )
    except Exception as exc:
        if display is not None:
            try:
                display.cleanup()
            except Exception:
                pass
        return _CheckResult(name="display", status="fail", details=str(exc)), None


def _input_check(display: Any, app_config: dict[str, Any]) -> _CheckResult:
    """Validate that the matching input adapter can be constructed."""
    from yoyopod.ui.input import get_input_manager

    input_manager = None

    try:
        input_manager = get_input_manager(
            display.get_adapter(),
            config=app_config,
            simulate=False,
        )
        if input_manager is None:
            return _CheckResult(
                name="input",
                status="fail",
                details="no input adapter was created for the detected display hardware",
            )

        capabilities = sorted(action.value for action in input_manager.get_capabilities())
        interaction_profile = input_manager.interaction_profile.value
        input_manager.start()
        time.sleep(0.1)
        input_manager.stop()

        return _CheckResult(
            name="input",
            status="pass",
            details=(f"profile={interaction_profile}, " f"capabilities={', '.join(capabilities)}"),
        )
    except Exception as exc:
        return _CheckResult(name="input", status="fail", details=str(exc))
    finally:
        if input_manager is not None:
            try:
                input_manager.stop()
            except Exception:
                pass


def _power_check(config_dir: Path) -> _CheckResult:
    """Validate PiSugar reachability and report a live battery snapshot."""
    from yoyopod_cli.config import ConfigManager
    from yoyopod.integrations.power import PowerManager

    config_manager = ConfigManager(config_dir=str(config_dir))
    manager = PowerManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        return _CheckResult(
            name="power",
            status="warn",
            details="power backend disabled in config/power/backend.yaml",
        )

    snapshot = manager.refresh()
    if not snapshot.available:
        details = snapshot.error or "power backend unavailable"
        return _CheckResult(name="power", status="fail", details=details)

    details = ", ".join(
        [
            f"model={snapshot.device.model or 'unknown'}",
            (
                f"battery={snapshot.battery.level_percent:.1f}%"
                if snapshot.battery.level_percent is not None
                else "battery=unknown"
            ),
            f"charging={snapshot.battery.charging}",
            f"plugged={snapshot.battery.power_plugged}",
        ]
    )
    return _CheckResult(name="power", status="pass", details=details)


def _rtc_check(config_dir: Path) -> _CheckResult:
    """Validate PiSugar RTC reachability and report the current RTC state."""
    from yoyopod_cli.config import ConfigManager
    from yoyopod.integrations.power import PowerManager

    config_manager = ConfigManager(config_dir=str(config_dir))
    manager = PowerManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        return _CheckResult(
            name="rtc",
            status="warn",
            details="power backend disabled in config/power/backend.yaml",
        )

    snapshot = manager.refresh()
    if not snapshot.available:
        details = snapshot.error or "power backend unavailable"
        return _CheckResult(name="rtc", status="fail", details=details)

    if snapshot.rtc.time is None:
        return _CheckResult(
            name="rtc",
            status="fail",
            details="PiSugar backend responded but rtc_time is unavailable",
        )

    details = ", ".join(
        [
            f"time={snapshot.rtc.time.isoformat()}",
            f"alarm_enabled={snapshot.rtc.alarm_enabled}",
            f"alarm_time={snapshot.rtc.alarm_time.isoformat() if snapshot.rtc.alarm_time is not None else 'none'}",
            f"repeat_mask={snapshot.rtc.alarm_repeat_mask if snapshot.rtc.alarm_repeat_mask is not None else 'unknown'}",
        ]
    )
    return _CheckResult(name="rtc", status="pass", details=details)


def smoke(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    with_power: Annotated[
        bool, typer.Option("--with-power", help="Also validate PiSugar power telemetry.")
    ] = False,
    with_rtc: Annotated[
        bool, typer.Option("--with-rtc", help="Also validate PiSugar RTC state and alarm.")
    ] = False,
    display_hold_seconds: Annotated[
        float,
        typer.Option(
            "--display-hold-seconds",
            help="How long to keep the display confirmation text visible.",
        ),
    ] = 0.5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Validate core target hardware paths: environment, display, input, and optional PiSugar state."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Running target smoke validation")

    app_config = _load_app_config(config_path)
    results: list[_CheckResult] = [_environment_check()]
    display = None

    try:
        display_result, display = _display_check(app_config, display_hold_seconds)
        results.append(display_result)

        if display_result.status == "pass" and display is not None:
            results.append(_input_check(display, app_config))

        if with_power:
            results.append(_power_check(config_path))

        if with_rtc:
            results.append(_rtc_check(config_path))
    finally:
        if display is not None:
            try:
                display.cleanup()
            except Exception as exc:
                logger.warning(f"Display cleanup failed: {exc}")

    _print_summary("smoke", results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
