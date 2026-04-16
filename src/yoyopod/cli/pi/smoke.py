"""src/yoyopod/cli/pi/smoke.py — Pi hardware smoke validation command."""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from yoyopod.cli.common import configure_logging, resolve_config_dir

smoke_app = typer.Typer(
    name="smoke",
    help="Run the legacy combined Raspberry Pi smoke validator. Prefer `yoyoctl pi validate` for focused target checks.",
    invoke_without_command=True,
    no_args_is_help=False,
)


@dataclass
class CheckResult:
    """Result for one smoke-validation step."""

    name: str
    status: str
    details: str


def _load_app_config(config_dir: Path) -> dict[str, Any]:
    """Load the app-level configuration file if present."""
    from loguru import logger

    from yoyopod.config import YoyoPodConfig, config_to_dict, load_config_model_from_yaml

    config_file = config_dir / "yoyopod_config.yaml"
    if not config_file.exists():
        logger.warning(f"App config not found: {config_file}")
    return config_to_dict(load_config_model_from_yaml(YoyoPodConfig, config_file))


def _environment_check() -> CheckResult:
    """Capture the current execution environment."""
    system = platform.system()
    machine = platform.machine()
    python_version = platform.python_version()

    if system == "Linux" and ("arm" in machine.lower() or "aarch" in machine.lower()):
        status = "pass"
    else:
        status = "warn"

    return CheckResult(
        name="environment",
        status=status,
        details=f"system={system}, machine={machine}, python={python_version}",
    )


def _display_check(
    app_config: dict[str, Any],
    hold_seconds: float,
) -> tuple[CheckResult, object]:
    """Validate display initialization on target hardware."""
    from yoyopod.ui.display import Display, detect_hardware

    requested_hardware = str(app_config.get("display", {}).get("hardware", "auto")).lower()
    resolved_hardware = detect_hardware() if requested_hardware == "auto" else requested_hardware

    if resolved_hardware == "simulation":
        return (
            CheckResult(
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

        display.clear(display.COLOR_BLACK)
        display.text("YoyoPod Pi smoke", 10, 40, color=display.COLOR_WHITE, font_size=18)
        display.text("Display OK", 10, 75, color=display.COLOR_GREEN, font_size=18)
        display.update()

        if hold_seconds > 0:
            time.sleep(hold_seconds)

        if display.simulate:
            return (
                CheckResult(
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
            CheckResult(
                name="display",
                status="pass",
                details=(
                    f"adapter={adapter.__class__.__name__}, "
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
        return CheckResult(name="display", status="fail", details=str(exc)), None


def _input_check(display: object, app_config: dict[str, Any]) -> CheckResult:
    """Validate that the matching input adapter can be constructed."""
    from yoyopod.ui.input import get_input_manager

    input_manager = None

    try:
        input_manager = get_input_manager(
            display.get_adapter(),  # type: ignore[union-attr]
            config=app_config,
            simulate=False,
        )
        if input_manager is None:
            return CheckResult(
                name="input",
                status="fail",
                details="no input adapter was created for the detected display hardware",
            )

        capabilities = sorted(action.value for action in input_manager.get_capabilities())
        interaction_profile = input_manager.interaction_profile.value
        input_manager.start()
        time.sleep(0.1)
        input_manager.stop()

        return CheckResult(
            name="input",
            status="pass",
            details=(
                f"profile={interaction_profile}, "
                f"capabilities={', '.join(capabilities)}"
            ),
        )
    except Exception as exc:
        return CheckResult(name="input", status="fail", details=str(exc))
    finally:
        if input_manager is not None:
            try:
                input_manager.stop()
            except Exception:
                pass


def _power_check(config_dir: Path) -> CheckResult:
    """Validate PiSugar reachability and report a live battery snapshot."""
    from yoyopod.config import ConfigManager
    from yoyopod.power import PowerManager

    config_manager = ConfigManager(config_dir=str(config_dir))
    manager = PowerManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        return CheckResult(
            name="power",
            status="warn",
            details="power backend disabled in yoyopod_config.yaml",
        )

    snapshot = manager.refresh()
    if not snapshot.available:
        details = snapshot.error or "power backend unavailable"
        return CheckResult(name="power", status="fail", details=details)

    details = ", ".join(
        [
            f"model={snapshot.device.model or 'unknown'}",
            f"battery={snapshot.battery.level_percent:.1f}%" if snapshot.battery.level_percent is not None else "battery=unknown",
            f"charging={snapshot.battery.charging}",
            f"plugged={snapshot.battery.power_plugged}",
        ]
    )
    return CheckResult(name="power", status="pass", details=details)


def _rtc_check(config_dir: Path) -> CheckResult:
    """Validate PiSugar RTC reachability and report the current RTC state."""
    from yoyopod.config import ConfigManager
    from yoyopod.power import PowerManager

    config_manager = ConfigManager(config_dir=str(config_dir))
    manager = PowerManager.from_config_manager(config_manager)

    if not manager.config.enabled:
        return CheckResult(
            name="rtc",
            status="warn",
            details="power backend disabled in yoyopod_config.yaml",
        )

    snapshot = manager.refresh()
    if not snapshot.available:
        details = snapshot.error or "power backend unavailable"
        return CheckResult(name="rtc", status="fail", details=details)

    if snapshot.rtc.time is None:
        return CheckResult(
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
    return CheckResult(name="rtc", status="pass", details=details)


def _music_check(app_config: dict[str, Any], timeout_seconds: int) -> CheckResult:
    """Validate music-backend startup and basic state queries."""
    from yoyopod.audio.music import MpvBackend, MusicConfig

    audio_config = app_config.get("audio", {})
    config = MusicConfig(
        music_dir=Path(str(audio_config.get("music_dir", "/home/pi/Music"))),
        mpv_socket=str(audio_config.get("mpv_socket", "")),
        mpv_binary=str(audio_config.get("mpv_binary", "mpv")),
        alsa_device=str(audio_config.get("alsa_device", "default")),
    )
    backend = MpvBackend(config)
    try:
        started_at = time.monotonic()
        if not backend.start():
            return CheckResult(
                name="music",
                status="fail",
                details=(
                    "could not start the mpv music backend "
                    f"(binary={config.mpv_binary}, socket={config.mpv_socket})"
                ),
            )

        while not backend.is_connected and (time.monotonic() - started_at) < timeout_seconds:
            time.sleep(0.1)

        if not backend.is_connected:
            return CheckResult(
                name="music",
                status="fail",
                details=f"music backend did not report ready within {timeout_seconds}s",
            )

        playback_state = backend.get_playback_state()
        track = backend.get_current_track()
        track_name = track.name if track else "none"

        return CheckResult(
            name="music",
            status="pass",
            details=(
                f"binary={config.mpv_binary}, socket={config.mpv_socket}, "
                f"state={playback_state}, track={track_name}"
            ),
        )
    except Exception as exc:
        return CheckResult(name="music", status="fail", details=str(exc))
    finally:
        backend.stop()


def _voip_check(config_dir: Path, registration_timeout: float) -> CheckResult:
    """Validate Liblinphone startup and SIP registration."""
    from yoyopod.config import ConfigManager
    from yoyopod.voip import VoIPConfig, VoIPManager
    from yoyopod.voip.liblinphone_binding import LiblinphoneBinding

    config_manager = ConfigManager(config_dir=str(config_dir))
    voip_config = VoIPConfig.from_config_manager(config_manager)
    binding = LiblinphoneBinding.try_load()
    if binding is None:
        return CheckResult(
            name="voip",
            status="fail",
            details="Liblinphone shim is unavailable; run yoyoctl build liblinphone on the Pi",
        )

    if not voip_config.sip_identity:
        return CheckResult(
            name="voip",
            status="fail",
            details="sip_identity is empty in config/voip_config.yaml",
        )

    manager = VoIPManager(voip_config, config_manager=config_manager)
    try:
        if not manager.start():
            return CheckResult(
                name="voip",
                status="fail",
                details="VoIP manager failed to start",
            )

        deadline = time.time() + registration_timeout
        last_status = manager.get_status()

        while time.time() < deadline:
            manager.iterate()
            last_status = manager.get_status()
            if last_status["registered"]:
                return CheckResult(
                    name="voip",
                    status="pass",
                    details=(
                        f"registered={last_status['registered']}, "
                        f"state={last_status['registration_state']}, "
                        f"identity={last_status['sip_identity']}"
                    ),
                )

            if last_status["registration_state"] == "failed":
                break

            time.sleep(0.5)

        return CheckResult(
            name="voip",
            status="fail",
            details=(
                f"registration timed out or failed; "
                f"state={last_status['registration_state']}, "
                f"identity={last_status['sip_identity']}"
            ),
        )
    except Exception as exc:
        return CheckResult(name="voip", status="fail", details=str(exc))
    finally:
        manager.stop()


def _lvgl_soak_check(config_dir: Path) -> CheckResult:
    """Run a small LVGL transition and sleep/wake soak on the active app path."""
    import time as _time

    from yoyopod.app import YoyoPodApp
    from yoyopod.events import UserActivityEvent

    def _pump_app(app: YoyoPodApp, duration_seconds: float) -> None:
        deadline = _time.monotonic() + max(0.0, duration_seconds)
        while _time.monotonic() < deadline:
            app._process_pending_main_thread_actions()
            now = _time.monotonic()
            app._attempt_manager_recovery()
            app._poll_power_status(now=now)
            app._pump_lvgl_backend(now)
            app._feed_watchdog_if_due(now)
            app._update_screen_power(now)
            _time.sleep(0.05)

    def _exercise_sleep_wake(app: YoyoPodApp) -> tuple[bool, str]:
        timeout_seconds = max(1.0, float(app._screen_timeout_seconds or 0.0))
        app._last_user_activity_at = _time.monotonic() - timeout_seconds - 1.0
        _pump_app(app, 0.35)
        if app.context is None or app.context.screen_awake:
            return False, "screen did not enter sleep during soak"
        app.event_bus.publish(UserActivityEvent(action_name="lvgl_soak"))
        _pump_app(app, 0.35)
        if app.context is None or not app.context.screen_awake:
            return False, "screen did not wake after simulated activity"
        return True, "sleep/wake ok"

    app = YoyoPodApp(config_dir=str(config_dir), simulate=False)
    if not app.setup():
        return CheckResult(name="lvgl_soak", status="fail", details="app setup failed")

    try:
        if app.display is None or app.screen_manager is None:
            return CheckResult(name="lvgl_soak", status="fail", details="display or screen manager not initialized")

        if app.display.backend_kind != "lvgl":
            return CheckResult(name="lvgl_soak", status="fail", details=f"backend is {app.display.backend_kind}, expected lvgl")

        screens = [
            "hub", "listen", "playlists", "now_playing",
            "call", "talk_contact", "call_history", "contacts",
            "voice_note", "ask", "power",
        ]

        transitions = 0
        for _cycle in range(1):
            for screen_name in screens:
                if screen_name not in app.screen_manager.screens:
                    continue
                app.screen_manager.replace_screen(screen_name)
                _pump_app(app, 0.15)
                transitions += 1

        sleep_ok, sleep_details = _exercise_sleep_wake(app)
        if not sleep_ok:
            return CheckResult(name="lvgl_soak", status="fail", details=sleep_details)

        return CheckResult(
            name="lvgl_soak",
            status="pass",
            details=f"backend=lvgl, transitions={transitions}, {sleep_details}",
        )
    finally:
        app.stop()


def _print_summary(results: list[CheckResult]) -> None:
    """Print a compact summary table."""
    print("")
    print("YoyoPod Raspberry Pi smoke summary")
    print("=" * 40)
    for result in results:
        print(f"[{result.status.upper():4}] {result.name}: {result.details}")


@smoke_app.callback(invoke_without_command=True)
def smoke(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory to use.")] = "config",
    with_music: Annotated[bool, typer.Option("--with-music", help="Also validate music-backend startup.")] = False,
    with_power: Annotated[bool, typer.Option("--with-power", help="Also validate PiSugar power telemetry.")] = False,
    with_rtc: Annotated[bool, typer.Option("--with-rtc", help="Also validate PiSugar RTC state and alarm.")] = False,
    with_voip: Annotated[bool, typer.Option("--with-voip", help="Also validate Liblinphone startup and SIP registration.")] = False,
    with_lvgl_soak: Annotated[bool, typer.Option("--with-lvgl-soak", help="Also run a short LVGL transition and sleep/wake soak.")] = False,
    music_timeout: Annotated[int, typer.Option("--music-timeout", help="Startup timeout in seconds for music checks.")] = 5,
    voip_timeout: Annotated[float, typer.Option("--voip-timeout", help="Registration timeout in seconds for VoIP checks.")] = 90.0,
    display_hold_seconds: Annotated[float, typer.Option("--display-hold-seconds", help="How long to keep the display confirmation text visible.")] = 0.5,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run the legacy combined Raspberry Pi smoke validation flow for YoyoPod."""
    from loguru import logger

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    logger.info("Starting Raspberry Pi smoke validation")
    logger.info(f"Using config directory: {config_path}")

    app_config = _load_app_config(config_path)
    results: list[CheckResult] = [_environment_check()]
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

        if with_music:
            results.append(_music_check(app_config, music_timeout))

        if with_voip:
            results.append(_voip_check(config_path, voip_timeout))

        if with_lvgl_soak:
            results.append(_lvgl_soak_check(config_path))
    finally:
        if display is not None:
            try:
                display.cleanup()
            except Exception as exc:
                logger.warning(f"Display cleanup failed: {exc}")

    _print_summary(results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
