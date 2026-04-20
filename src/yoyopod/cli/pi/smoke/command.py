"""Legacy Pi smoke validation command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from yoyopod.cli.common import configure_logging, resolve_config_dir
from yoyopod.cli.pi.music_fixtures import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod.cli.pi.smoke.display import _display_check
from yoyopod.cli.pi.smoke.environment import _environment_check
from yoyopod.cli.pi.smoke.input import _input_check
from yoyopod.cli.pi.smoke.lvgl import _lvgl_soak_check
from yoyopod.cli.pi.smoke.music import _music_check, _prepare_music_validation_library
from yoyopod.cli.pi.smoke.power import _power_check
from yoyopod.cli.pi.smoke.report import _print_summary
from yoyopod.cli.pi.smoke.rtc import _rtc_check
from yoyopod.cli.pi.smoke.types import CheckResult
from yoyopod.cli.pi.smoke.voip import _voip_check

if TYPE_CHECKING:
    from yoyopod.config import MediaConfig

smoke_app = typer.Typer(
    name="smoke",
    help="Run the legacy combined Raspberry Pi smoke validator. Prefer `yoyoctl pi validate` for focused target checks.",
    invoke_without_command=True,
    no_args_is_help=False,
)


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


def _load_media_config(config_dir: Path) -> "MediaConfig":
    """Load the typed composed media config if present."""
    from yoyopod.config import ConfigManager

    return ConfigManager(config_dir=str(config_dir)).get_media_settings()


@smoke_app.callback(invoke_without_command=True)
def smoke(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    with_music: Annotated[
        bool, typer.Option("--with-music", help="Also validate music-backend startup.")
    ] = False,
    with_power: Annotated[
        bool, typer.Option("--with-power", help="Also validate PiSugar power telemetry.")
    ] = False,
    with_rtc: Annotated[
        bool, typer.Option("--with-rtc", help="Also validate PiSugar RTC state and alarm.")
    ] = False,
    with_voip: Annotated[
        bool,
        typer.Option("--with-voip", help="Also validate Liblinphone startup and SIP registration."),
    ] = False,
    with_lvgl_soak: Annotated[
        bool,
        typer.Option(
            "--with-lvgl-soak", help="Also run a short LVGL transition and sleep/wake soak."
        ),
    ] = False,
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
    music_timeout: Annotated[
        int, typer.Option("--music-timeout", help="Startup timeout in seconds for music checks.")
    ] = 5,
    voip_timeout: Annotated[
        float,
        typer.Option("--voip-timeout", help="Registration timeout in seconds for VoIP checks."),
    ] = 90.0,
    display_hold_seconds: Annotated[
        float,
        typer.Option(
            "--display-hold-seconds", help="How long to keep the display confirmation text visible."
        ),
    ] = 0.5,
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
