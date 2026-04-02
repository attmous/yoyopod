#!/usr/bin/env python3
"""Raspberry Pi smoke validation helper for YoyoPod."""

from __future__ import annotations

import argparse
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from yoyopy.audio.mopidy_client import MopidyClient
from yoyopy.config import ConfigManager, YoyoPodConfig, config_to_dict, load_config_model_from_yaml
from yoyopy.voip import VoIPConfig, VoIPManager
from yoyopy.ui.display import Display, detect_hardware
from yoyopy.ui.input import get_input_manager


@dataclass
class CheckResult:
    """Result for one smoke-validation step."""

    name: str
    status: str
    details: str


def configure_logging(verbose: bool) -> None:
    """Configure human-readable logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG" if verbose else "INFO",
    )


def load_app_config(config_dir: Path) -> dict[str, Any]:
    """Load the app-level configuration file if present."""
    config_file = config_dir / "yoyopod_config.yaml"
    if not config_file.exists():
        logger.warning(f"App config not found: {config_file}")
    return config_to_dict(load_config_model_from_yaml(YoyoPodConfig, config_file))


def environment_check() -> CheckResult:
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


def display_check(
    app_config: dict[str, Any],
    hold_seconds: float,
) -> tuple[CheckResult, Display | None]:
    """Validate display initialization on target hardware."""
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


def input_check(display: Display, app_config: dict[str, Any]) -> CheckResult:
    """Validate that the matching input adapter can be constructed."""
    input_manager = None

    try:
        input_manager = get_input_manager(
            display.get_adapter(),
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


def mopidy_check(app_config: dict[str, Any], timeout_seconds: int) -> CheckResult:
    """Validate Mopidy reachability and basic state queries."""
    audio_config = app_config.get("audio", {})
    host = audio_config.get("mopidy_host", "localhost")
    port = int(audio_config.get("mopidy_port", 6680))

    client = MopidyClient(host=host, port=port, timeout=timeout_seconds)
    try:
        if not client.connect():
            return CheckResult(
                name="mopidy",
                status="fail",
                details=f"could not connect to Mopidy at {host}:{port}",
            )

        playback_state = client.get_playback_state()
        track = client.get_current_track()
        track_name = track.name if track else "none"

        return CheckResult(
            name="mopidy",
            status="pass",
            details=f"host={host}:{port}, state={playback_state}, track={track_name}",
        )
    except Exception as exc:
        return CheckResult(name="mopidy", status="fail", details=str(exc))
    finally:
        client.cleanup()


def voip_check(config_dir: Path, registration_timeout: float) -> CheckResult:
    """Validate linphone startup and SIP registration."""
    config_manager = ConfigManager(config_dir=str(config_dir))
    voip_config = VoIPConfig.from_config_manager(config_manager)
    linphonec_path = Path(voip_config.linphonec_path)

    if not linphonec_path.exists():
        return CheckResult(
            name="voip",
            status="fail",
            details=f"linphonec path does not exist: {linphonec_path}",
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


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run Raspberry Pi smoke validation for YoyoPod hardware, "
            "with optional Mopidy and SIP registration checks."
        )
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Configuration directory to use (default: config)",
    )
    parser.add_argument(
        "--with-mopidy",
        action="store_true",
        help="Also validate Mopidy connectivity from yoyopod_config.yaml",
    )
    parser.add_argument(
        "--with-voip",
        action="store_true",
        help="Also validate linphone startup and SIP registration",
    )
    parser.add_argument(
        "--mopidy-timeout",
        type=int,
        default=5,
        help="Request timeout in seconds for Mopidy checks (default: 5)",
    )
    parser.add_argument(
        "--voip-timeout",
        type=float,
        default=10.0,
        help="Registration timeout in seconds for VoIP checks (default: 10)",
    )
    parser.add_argument(
        "--display-hold-seconds",
        type=float,
        default=0.5,
        help="How long to keep the display confirmation text visible (default: 0.5)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def print_summary(results: list[CheckResult]) -> None:
    """Print a compact summary table."""
    print("")
    print("YoyoPod Raspberry Pi smoke summary")
    print("=" * 40)
    for result in results:
        print(f"[{result.status.upper():4}] {result.name}: {result.details}")


def main() -> int:
    """Run the requested smoke checks."""
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)

    config_dir = Path(args.config_dir)
    if not config_dir.is_absolute():
        config_dir = REPO_ROOT / config_dir

    logger.info("Starting Raspberry Pi smoke validation")
    logger.info(f"Using config directory: {config_dir}")

    app_config = load_app_config(config_dir)
    results: list[CheckResult] = [environment_check()]
    display: Display | None = None

    try:
        display_result, display = display_check(app_config, args.display_hold_seconds)
        results.append(display_result)

        if display_result.status == "pass" and display is not None:
            results.append(input_check(display, app_config))

        if args.with_mopidy:
            results.append(mopidy_check(app_config, args.mopidy_timeout))

        if args.with_voip:
            results.append(voip_check(config_dir, args.voip_timeout))
    finally:
        if display is not None:
            try:
                display.cleanup()
            except Exception as exc:
                logger.warning(f"Display cleanup failed: {exc}")

    print_summary(results)
    return 1 if any(result.status == "fail" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
