#!/usr/bin/env python3
"""Interactive Whisplay gesture-tuning helper for Raspberry Pi hardware."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from yoyopy.config import YoyoPodConfig, config_to_dict, load_config_model_from_yaml
from yoyopy.ui.display import Display
from yoyopy.ui.input import InputAction, InteractionProfile, get_input_manager


@dataclass
class GestureEvent:
    """One recorded one-button semantic gesture."""

    action: str
    method: str
    at_seconds: float
    duration_ms: int | None = None


def configure_logging(verbose: bool) -> None:
    """Configure readable CLI logging."""
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG" if verbose else "INFO",
    )


def load_app_config(config_dir: Path) -> dict[str, Any]:
    """Load the current app config as a plain dict."""
    config_file = config_dir / "yoyopod_config.yaml"
    return config_to_dict(load_config_model_from_yaml(YoyoPodConfig, config_file))


def apply_timing_overrides(
    app_config: dict[str, Any],
    *,
    debounce_ms: int | None,
    double_tap_ms: int | None,
    long_hold_ms: int | None,
) -> dict[str, Any]:
    """Return a config dict with temporary Whisplay timing overrides applied."""
    merged = dict(app_config)
    input_config = dict(merged.get("input", {}))

    if debounce_ms is not None:
        input_config["whisplay_debounce_ms"] = debounce_ms
    if double_tap_ms is not None:
        input_config["whisplay_double_tap_ms"] = double_tap_ms
    if long_hold_ms is not None:
        input_config["whisplay_long_hold_ms"] = long_hold_ms

    merged["input"] = input_config
    return merged


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run an interactive Whisplay gesture monitor with optional timing "
            "overrides, so button tuning can be validated on-device."
        )
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Configuration directory to use (default: config)",
    )
    parser.add_argument(
        "--debounce-ms",
        type=int,
        help="Override Whisplay debounce timing in milliseconds for this run",
    )
    parser.add_argument(
        "--double-tap-ms",
        type=int,
        help="Override double-tap timing in milliseconds for this run",
    )
    parser.add_argument(
        "--long-hold-ms",
        type=int,
        help="Override long-hold timing in milliseconds for this run",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=30.0,
        help="How long to monitor gestures before exiting (default: 30)",
    )
    parser.add_argument(
        "--hardware",
        default="whisplay",
        help="Display hardware to open (default: whisplay)",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Skip drawing tuning hints on the display and log to the terminal only",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def summarize_timings(app_config: dict[str, Any]) -> str:
    """Return one short timing summary for logs and display."""
    input_config = app_config.get("input", {})
    debounce_ms = int(input_config.get("whisplay_debounce_ms", 50))
    double_tap_ms = int(input_config.get("whisplay_double_tap_ms", 300))
    long_hold_ms = int(input_config.get("whisplay_long_hold_ms", 800))
    return (
        f"debounce={debounce_ms}ms, "
        f"double={double_tap_ms}ms, "
        f"hold={long_hold_ms}ms"
    )


def record_event(events: list[GestureEvent], start_time: float, action: InputAction, data: Any) -> None:
    """Store one semantic gesture and log it for the operator."""
    payload = data if isinstance(data, dict) else {}
    duration_ms = None
    duration = payload.get("duration")
    if duration is not None:
        duration_ms = int(float(duration) * 1000)

    event = GestureEvent(
        action=action.value,
        method=str(payload.get("method", "unknown")),
        at_seconds=time.monotonic() - start_time,
        duration_ms=duration_ms,
    )
    events.append(event)

    if duration_ms is None:
        logger.info(
            "Gesture {} via {} at {:.2f}s",
            event.action,
            event.method,
            event.at_seconds,
        )
    else:
        logger.info(
            "Gesture {} via {} at {:.2f}s ({}ms)",
            event.action,
            event.method,
            event.at_seconds,
            event.duration_ms,
        )


def render_status_screen(
    display: Display,
    timing_summary: str,
    events: list[GestureEvent],
    ends_at: float,
) -> None:
    """Render the current tuning status on the Whisplay display."""
    now = time.time()
    countdown = max(0, int(ends_at - now))
    last_event = events[-1] if events else None

    display.clear(display.COLOR_BLACK)
    display.text("Whisplay Tune", 18, 20, color=display.COLOR_WHITE, font_size=18)
    display.text(timing_summary, 18, 48, color=display.COLOR_GRAY, font_size=11)
    display.text("Tap next", 18, 86, color=display.COLOR_CYAN, font_size=16)
    display.text("Double select", 18, 112, color=display.COLOR_WHITE, font_size=16)
    display.text("Hold back", 18, 138, color=display.COLOR_YELLOW, font_size=16)
    display.text(f"Left: {countdown}s", 18, 176, color=display.COLOR_GRAY, font_size=12)

    if last_event is None:
        display.text("Waiting for input", 18, 206, color=display.COLOR_GRAY, font_size=13)
    else:
        display.text(
            f"Last: {last_event.action.upper()}",
            18,
            206,
            color=display.COLOR_GREEN,
            font_size=13,
        )
        detail = last_event.method
        if last_event.duration_ms is not None:
            detail = f"{detail} {last_event.duration_ms}ms"
        display.text(detail, 18, 228, color=display.COLOR_GRAY, font_size=11)

    display.update()


def main() -> int:
    """Run the interactive tuning helper."""
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)

    config_dir = Path(args.config_dir)
    if not config_dir.is_absolute():
        config_dir = REPO_ROOT / config_dir

    app_config = load_app_config(config_dir)
    app_config = apply_timing_overrides(
        app_config,
        debounce_ms=args.debounce_ms,
        double_tap_ms=args.double_tap_ms,
        long_hold_ms=args.long_hold_ms,
    )
    timing_summary = summarize_timings(app_config)
    logger.info("Whisplay tuning session using {}", timing_summary)

    display = None
    input_manager = None
    events: list[GestureEvent] = []
    start_time = time.monotonic()
    ends_at = time.time() + args.duration_seconds

    try:
        display = Display(hardware=args.hardware, simulate=False)

        input_manager = get_input_manager(
            display.get_adapter(),
            config=app_config,
            simulate=False,
        )
        if input_manager is None:
            logger.error("No input adapter available for the detected hardware")
            return 1

        if input_manager.interaction_profile != InteractionProfile.ONE_BUTTON:
            logger.error(
                "Detected interaction profile {} instead of one_button",
                input_manager.interaction_profile.value,
            )
            return 1

        for action in (InputAction.ADVANCE, InputAction.SELECT, InputAction.BACK):
            input_manager.on_action(
                action,
                lambda data=None, action=action: record_event(events, start_time, action, data),
            )

        input_manager.start()
        logger.info("Monitoring Whisplay gestures for %.1fs", args.duration_seconds)

        while time.time() < ends_at:
            if display is not None and not args.no_display:
                render_status_screen(display, timing_summary, events, ends_at)
            time.sleep(0.1)

        logger.info("Whisplay tuning session complete")
        logger.info(
            "Summary: advance={}, select={}, back={}",
            sum(1 for event in events if event.action == InputAction.ADVANCE.value),
            sum(1 for event in events if event.action == InputAction.SELECT.value),
            sum(1 for event in events if event.action == InputAction.BACK.value),
        )
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    finally:
        if input_manager is not None:
            try:
                input_manager.stop()
            except Exception as exc:
                logger.warning("Input cleanup failed: {}", exc)
        if display is not None:
            try:
                display.cleanup()
            except Exception as exc:
                logger.warning("Display cleanup failed: {}", exc)


if __name__ == "__main__":
    raise SystemExit(main())
