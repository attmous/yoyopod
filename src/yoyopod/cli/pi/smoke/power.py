"""Power-backend smoke checks."""

from __future__ import annotations

from pathlib import Path

from .types import CheckResult


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
            details="power backend disabled in config/power/backend.yaml",
        )

    snapshot = manager.refresh()
    if not snapshot.available:
        details = snapshot.error or "power backend unavailable"
        return CheckResult(name="power", status="fail", details=details)

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
    return CheckResult(name="power", status="pass", details=details)
