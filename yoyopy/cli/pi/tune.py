"""yoyopy/cli/pi/tune.py — Interactive Whisplay gesture-tuning command."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from yoyopy.cli.common import configure_logging, resolve_config_dir

tune_app = typer.Typer(
    name="tune",
    help="Interactive Whisplay gesture-tuning helper.",
    invoke_without_command=True,
    no_args_is_help=False,
)


@dataclass
class GestureEvent:
    """One recorded one-button semantic gesture."""

    action: str
    method: str
    at_seconds: float
    duration_ms: int | None = None


def _load_app_config(config_dir: Path) -> dict[str, Any]:
    """Load the current app config as a plain dict."""
    from yoyopy.config import YoyoPodConfig, config_to_dict, load_config_model_from_yaml

    config_file = config_dir / "yoyopod_config.yaml"
    return config_to_dict(load_config_model_from_yaml(YoyoPodConfig, config_file))


def _apply_timing_overrides(
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


def _summarize_timings(app_config: dict[str, Any]) -> str:
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


def _record_event(events: list[GestureEvent], start_time: float, action: object, data: Any) -> None:
    """Store one semantic gesture and log it for the operator."""
    from loguru import logger

    payload = data if isinstance(data, dict) else {}
    duration_ms = None
    duration = payload.get("duration")
    if duration is not None:
        duration_ms = int(float(duration) * 1000)

    event = GestureEvent(
        action=action.value,  # type: ignore[union-attr]
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


def _render_status_screen(
    display: object,
    timing_summary: str,
    events: list[GestureEvent],
    ends_at: float,
) -> None:
    """Render the current tuning status on the Whisplay display."""
    from yoyopy.ui.display import Display

    d: Display = display  # type: ignore[assignment]
    now = time.time()
    countdown = max(0, int(ends_at - now))
    last_event = events[-1] if events else None

    d.clear(d.COLOR_BLACK)
    d.text("Whisplay Tune", 18, 20, color=d.COLOR_WHITE, font_size=18)
    d.text(timing_summary, 18, 48, color=d.COLOR_GRAY, font_size=11)
    d.text("Tap next", 18, 86, color=d.COLOR_CYAN, font_size=16)
    d.text("Double select", 18, 112, color=d.COLOR_WHITE, font_size=16)
    d.text("Hold back", 18, 138, color=d.COLOR_YELLOW, font_size=16)
    d.text(f"Left: {countdown}s", 18, 176, color=d.COLOR_GRAY, font_size=12)

    if last_event is None:
        d.text("Waiting for input", 18, 206, color=d.COLOR_GRAY, font_size=13)
    else:
        d.text(
            f"Last: {last_event.action.upper()}",
            18,
            206,
            color=d.COLOR_GREEN,
            font_size=13,
        )
        detail = last_event.method
        if last_event.duration_ms is not None:
            detail = f"{detail} {last_event.duration_ms}ms"
        d.text(detail, 18, 228, color=d.COLOR_GRAY, font_size=11)

    d.update()


@tune_app.callback(invoke_without_command=True)
def tune(
    config_dir: Annotated[str, typer.Option("--config-dir", help="Configuration directory to use.")] = "config",
    debounce_ms: Annotated[Optional[int], typer.Option("--debounce-ms", help="Override Whisplay debounce timing in milliseconds.")] = None,
    double_tap_ms: Annotated[Optional[int], typer.Option("--double-tap-ms", help="Override double-tap timing in milliseconds.")] = None,
    long_hold_ms: Annotated[Optional[int], typer.Option("--long-hold-ms", help="Override long-hold timing in milliseconds.")] = None,
    duration_seconds: Annotated[float, typer.Option("--duration-seconds", help="How long to monitor gestures before exiting.")] = 30.0,
    hardware: Annotated[str, typer.Option("--hardware", help="Display hardware to open.")] = "whisplay",
    no_display: Annotated[bool, typer.Option("--no-display", help="Skip drawing tuning hints on the display.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Run an interactive Whisplay gesture monitor with optional timing overrides."""
    from loguru import logger

    from yoyopy.ui.display import Display
    from yoyopy.ui.input import InputAction, InteractionProfile, get_input_manager

    configure_logging(verbose)
    config_path = resolve_config_dir(config_dir)

    app_config = _load_app_config(config_path)
    app_config = _apply_timing_overrides(
        app_config,
        debounce_ms=debounce_ms,
        double_tap_ms=double_tap_ms,
        long_hold_ms=long_hold_ms,
    )
    timing_summary = _summarize_timings(app_config)
    logger.info("Whisplay tuning session using {}", timing_summary)

    display = None
    input_manager = None
    events: list[GestureEvent] = []
    start_time = time.monotonic()
    ends_at = time.time() + duration_seconds

    try:
        display = Display(hardware=hardware, simulate=False)

        input_manager = get_input_manager(
            display.get_adapter(),
            config=app_config,
            simulate=False,
        )
        if input_manager is None:
            logger.error("No input adapter available for the detected hardware")
            raise typer.Exit(code=1)

        if input_manager.interaction_profile != InteractionProfile.ONE_BUTTON:
            logger.error(
                "Detected interaction profile {} instead of one_button",
                input_manager.interaction_profile.value,
            )
            raise typer.Exit(code=1)

        for action in (InputAction.ADVANCE, InputAction.SELECT, InputAction.BACK):
            input_manager.on_action(
                action,
                lambda data=None, action=action: _record_event(events, start_time, action, data),
            )

        input_manager.start()
        logger.info("Monitoring Whisplay gestures for %.1fs", duration_seconds)

        while time.time() < ends_at:
            if display is not None and not no_display:
                _render_status_screen(display, timing_summary, events, ends_at)
            time.sleep(0.1)

        logger.info("Whisplay tuning session complete")
        logger.info(
            "Summary: advance={}, select={}, back={}",
            sum(1 for event in events if event.action == InputAction.ADVANCE.value),
            sum(1 for event in events if event.action == InputAction.SELECT.value),
            sum(1 for event in events if event.action == InputAction.BACK.value),
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        raise typer.Exit(code=130)
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
