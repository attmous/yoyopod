"""src/yoyopod/cli/pi/smoke.py — Pi hardware smoke validation command."""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Optional

import typer

from yoyopod.audio.test_music import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod.cli.common import configure_logging, resolve_config_dir

if TYPE_CHECKING:
    from yoyopod.audio.test_music import ProvisionedTestMusicLibrary
    from yoyopod.config import MediaConfig

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
    """Load the composed app config if present."""
    from loguru import logger

    from yoyopod.config import config_to_dict, load_composed_app_settings

    if not any(
        path.exists()
        for path in (
            config_dir / "app" / "core.yaml",
            config_dir / "device" / "hardware.yaml",
        )
    ):
        logger.warning("Composed app config not found under {}", config_dir)
    return config_to_dict(load_composed_app_settings(config_dir))


def _load_media_config(config_dir: Path) -> MediaConfig:
    """Load the typed composed media config if present."""
    from yoyopod.config import ConfigManager

    return ConfigManager(config_dir=str(config_dir)).get_media_settings()


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
            details="power backend disabled in config/app/core.yaml",
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
            details="power backend disabled in config/app/core.yaml",
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


def _prepare_music_validation_library(
    media_settings: MediaConfig,
    *,
    provision_test_music: bool,
    test_music_dir: str,
) -> ProvisionedTestMusicLibrary | None:
    """Provision the deterministic validation music library and point smoke at it."""
    from yoyopod.audio.test_music import provision_test_music_library

    if not provision_test_music:
        return None

    library = provision_test_music_library(Path(test_music_dir))
    media_settings.music.music_dir = str(library.target_dir)
    return library


def _music_check(
    media_settings: MediaConfig,
    timeout_seconds: int,
    *,
    expected_library: ProvisionedTestMusicLibrary | None = None,
) -> CheckResult:
    """Validate music-backend startup and basic state queries."""
    from yoyopod.audio import LocalMusicService, MpvBackend, MusicConfig

    config = MusicConfig.from_media_settings(media_settings)
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

        if expected_library is not None:
            missing_assets = [
                path
                for path in expected_library.expected_asset_paths
                if not path.exists()
            ]
            if missing_assets:
                missing_list = ", ".join(str(path) for path in missing_assets)
                return CheckResult(
                    name="music",
                    status="fail",
                    details=f"missing provisioned test assets: {missing_list}",
                )

            music_service = LocalMusicService(backend, music_dir=expected_library.target_dir)
            playlist_path = expected_library.default_playlist_path
            playlists = music_service.list_playlists()
            if str(playlist_path) not in {playlist.uri for playlist in playlists}:
                return CheckResult(
                    name="music",
                    status="fail",
                    details=f"provisioned playlist not discoverable under {expected_library.target_dir}",
                )

            if not music_service.load_playlist(str(playlist_path)):
                return CheckResult(
                    name="music",
                    status="fail",
                    details=f"mpv could not load the provisioned playlist {playlist_path}",
                )

            expected_track_uris = {str(path) for path in expected_library.track_paths}
            loaded_track = None
            while (time.monotonic() - started_at) < timeout_seconds:
                loaded_track = backend.get_current_track()
                if loaded_track is not None and loaded_track.uri in expected_track_uris:
                    break
                time.sleep(0.1)

            if loaded_track is None or loaded_track.uri not in expected_track_uris:
                current_uri = loaded_track.uri if loaded_track is not None else "none"
                return CheckResult(
                    name="music",
                    status="fail",
                    details=(
                        "music backend started, but it did not load one of the "
                        f"provisioned validation tracks from {expected_library.target_dir}; "
                        f"current_track={current_uri}"
                    ),
                )

            playback_state = backend.get_playback_state()
            return CheckResult(
                name="music",
                status="pass",
                details=(
                    f"binary={config.mpv_binary}, socket={config.mpv_socket}, "
                    f"music_dir={expected_library.target_dir}, "
                    f"playlist={playlist_path.name}, state={playback_state}, "
                    f"track={loaded_track.name}"
                ),
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
    from yoyopod.communication import VoIPConfig, VoIPManager
    from yoyopod.communication.integrations.liblinphone_binding import LiblinphoneBinding

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
            details="sip_identity is empty in config/communication/calling.yaml",
        )

    manager = VoIPManager(
        voip_config,
        people_directory=None,
    )
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


def _lvgl_soak_check(
    config_dir: Path,
    *,
    with_music: bool = False,
    provision_test_music: bool = True,
    test_music_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR,
) -> CheckResult:
    """Run the target navigation and idle soak on the active LVGL app path."""
    from yoyopod.cli.pi.stability import NavigationSoakError, run_navigation_idle_soak

    try:
        report = run_navigation_idle_soak(
            config_dir=str(config_dir),
            simulate=False,
            cycles=1,
            hold_seconds=0.15,
            idle_seconds=0.5,
            with_music=with_music,
            provision_test_music=provision_test_music,
            test_music_dir=test_music_dir,
        )
    except NavigationSoakError as exc:
        return CheckResult(name="lvgl_soak", status="fail", details=str(exc))

    return CheckResult(
        name="lvgl_soak",
        status="pass",
        details=report.summary(),
    )


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
    provision_test_music: Annotated[
        bool,
        typer.Option(
            "--provision-test-music/--no-provision-test-music",
            help="Seed the deterministic validation music library before music checks.",
        ),
    ] = True,
    test_music_dir: Annotated[
        str,
        typer.Option(
            "--test-music-dir",
            help="Dedicated target directory for validation-only test music assets.",
        ),
    ] = DEFAULT_TEST_MUSIC_TARGET_DIR,
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
    media_config = _load_media_config(config_path)
    expected_music_library = None
    if with_music:
        expected_music_library = _prepare_music_validation_library(
            media_config,
            provision_test_music=provision_test_music,
            test_music_dir=test_music_dir,
        )
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
            results.append(
                _music_check(
                    media_config,
                    music_timeout,
                    expected_library=expected_music_library,
                )
            )

        if with_voip:
            results.append(_voip_check(config_path, voip_timeout))

        if with_lvgl_soak:
            results.append(
                _lvgl_soak_check(
                    config_path,
                    with_music=with_music,
                    provision_test_music=provision_test_music,
                    test_music_dir=test_music_dir,
                )
            )
    finally:
        if display is not None:
            try:
                display.cleanup()
            except Exception as exc:
                logger.warning(f"Display cleanup failed: {exc}")

    _print_summary(results)
    if any(result.status == "fail" for result in results):
        raise typer.Exit(code=1)
