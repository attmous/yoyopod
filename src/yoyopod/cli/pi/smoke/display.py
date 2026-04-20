"""Display smoke checks."""

from __future__ import annotations

import time
from typing import Any

from .types import CheckResult


def _display_check(
    app_config: dict[str, Any],
    hold_seconds: float,
) -> tuple[CheckResult, object]:
    """Validate the display initialization on target hardware."""
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
