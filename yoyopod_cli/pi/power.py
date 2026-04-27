"""yoyopod_cli/pi_power.py — PiSugar power and RTC commands."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from yoyopod_cli.common import configure_logging, resolve_config_dir

app = typer.Typer(name="power", help="PiSugar power and RTC commands.", no_args_is_help=True)
rtc_app = typer.Typer(name="rtc", help="PiSugar RTC operations.", no_args_is_help=True)
app.add_typer(rtc_app)


@app.command()
def battery(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Inspect PiSugar power telemetry through YoYoPod's power module."""
    from loguru import logger

    from yoyopod.config import ConfigManager
    from yoyopod.integrations.power import PowerManager

    configure_logging(verbose)

    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = PowerManager.from_config_manager(config_manager)
    if not manager.config.enabled:
        logger.error("power backend disabled in config/power/backend.yaml")
        raise typer.Exit(code=1)

    snapshot = manager.refresh()
    if not snapshot.available:
        logger.error(snapshot.error or "power backend unavailable")
        raise typer.Exit(code=1)

    print("")
    print("PiSugar power status")
    print("====================")
    lines = [
        f"available={snapshot.available}",
        f"source={snapshot.source}",
        f"error={snapshot.error or 'none'}",
        f"model={snapshot.device.model or 'unknown'}",
        f"battery_percent={snapshot.battery.level_percent if snapshot.battery.level_percent is not None else 'unknown'}",
        f"battery_voltage={snapshot.battery.voltage_volts if snapshot.battery.voltage_volts is not None else 'unknown'}",
        f"temperature_celsius={snapshot.battery.temperature_celsius if snapshot.battery.temperature_celsius is not None else 'unknown'}",
        f"charging={snapshot.battery.charging if snapshot.battery.charging is not None else 'unknown'}",
        f"external_power={snapshot.battery.power_plugged if snapshot.battery.power_plugged is not None else 'unknown'}",
        f"allow_charging={snapshot.battery.allow_charging if snapshot.battery.allow_charging is not None else 'unknown'}",
        f"output_enabled={snapshot.battery.output_enabled if snapshot.battery.output_enabled is not None else 'unknown'}",
        f"rtc_time={snapshot.rtc.time.isoformat() if snapshot.rtc.time is not None else 'unknown'}",
        f"rtc_alarm_enabled={snapshot.rtc.alarm_enabled if snapshot.rtc.alarm_enabled is not None else 'unknown'}",
        f"rtc_alarm_time={snapshot.rtc.alarm_time.isoformat() if snapshot.rtc.alarm_time is not None else 'none'}",
        f"safe_shutdown_level={snapshot.shutdown.safe_shutdown_level_percent if snapshot.shutdown.safe_shutdown_level_percent is not None else 'unknown'}",
        f"safe_shutdown_delay={snapshot.shutdown.safe_shutdown_delay_seconds if snapshot.shutdown.safe_shutdown_delay_seconds is not None else 'unknown'}",
        f"warning_threshold={manager.config.low_battery_warning_percent}",
        f"critical_threshold={manager.config.critical_shutdown_percent}",
        f"shutdown_delay_seconds={manager.config.shutdown_delay_seconds}",
        f"watchdog_enabled={manager.config.watchdog_enabled}",
        f"watchdog_timeout_seconds={manager.config.watchdog_timeout_seconds}",
        f"watchdog_feed_interval_seconds={manager.config.watchdog_feed_interval_seconds}",
    ]
    for line in lines:
        print(line)


def _format_rtc_state(state: Any) -> list[str]:
    """Return a human-readable summary of RTC state."""
    return [
        f"rtc_time={state.time.isoformat() if state.time is not None else 'unknown'}",
        f"alarm_enabled={state.alarm_enabled}",
        f"alarm_time={state.alarm_time.isoformat() if state.alarm_time is not None else 'none'}",
        f"alarm_repeat_mask={state.alarm_repeat_mask if state.alarm_repeat_mask is not None else 'unknown'}",
        f"adjust_ppm={state.adjust_ppm if state.adjust_ppm is not None else 'unknown'}",
    ]


def _build_power_manager(config_dir: str) -> Any:
    """Build and return a PowerManager, exiting on error."""
    from loguru import logger

    from yoyopod.config import ConfigManager
    from yoyopod.integrations.power import PowerManager

    config_path = resolve_config_dir(config_dir)
    config_manager = ConfigManager(config_dir=str(config_path))
    manager = PowerManager.from_config_manager(config_manager)
    if not manager.config.enabled:
        logger.error("power backend disabled in config/power/backend.yaml")
        raise typer.Exit(code=1)
    return manager


@rtc_app.command()
def status(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Show current RTC and alarm state."""
    from loguru import logger

    configure_logging(verbose)
    manager = _build_power_manager(config_dir)

    snapshot = manager.refresh()
    if not snapshot.available:
        logger.error(snapshot.error or "power backend unavailable")
        raise typer.Exit(code=1)

    heading = "PiSugar RTC status"
    print("")
    print(heading)
    print("=" * len(heading))
    print(f"model={snapshot.device.model or 'unknown'}")
    for line in _format_rtc_state(snapshot.rtc):
        print(line)


@rtc_app.command(name="sync-to")
def sync_to(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Sync Raspberry Pi system time to the PiSugar RTC."""
    configure_logging(verbose)
    manager = _build_power_manager(config_dir)

    state = manager.sync_time_to_rtc()
    print("")
    print("PiSugar RTC synced from Raspberry Pi system time")
    print("==============================================")
    for line in _format_rtc_state(state):
        print(line)


@rtc_app.command(name="sync-from")
def sync_from(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Sync PiSugar RTC time to the Raspberry Pi system clock."""
    configure_logging(verbose)
    manager = _build_power_manager(config_dir)

    state = manager.sync_time_from_rtc()
    print("")
    print("Raspberry Pi system time synced from PiSugar RTC")
    print("===============================================")
    for line in _format_rtc_state(state):
        print(line)


@rtc_app.command(name="set-alarm")
def set_alarm(
    time: Annotated[str, typer.Option("--time", help="Alarm time as ISO 8601 timestamp.")],
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
    repeat_mask: Annotated[
        int,
        typer.Option("--repeat-mask", help="Weekday repeat bitmask (default: 127 for every day)."),
    ] = 127,
) -> None:
    """Set the PiSugar RTC wake alarm."""
    from datetime import datetime

    configure_logging(verbose)
    manager = _build_power_manager(config_dir)

    normalized = time.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    alarm_time = datetime.fromisoformat(normalized)

    state = manager.set_rtc_alarm(alarm_time, repeat_mask=repeat_mask)
    print("")
    print("PiSugar RTC alarm updated")
    print("=========================")
    for line in _format_rtc_state(state):
        print(line)


@rtc_app.command(name="disable-alarm")
def disable_alarm(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Disable the PiSugar RTC wake alarm."""
    configure_logging(verbose)
    manager = _build_power_manager(config_dir)

    state = manager.disable_rtc_alarm()
    print("")
    print("PiSugar RTC alarm disabled")
    print("==========================")
    for line in _format_rtc_state(state):
        print(line)
