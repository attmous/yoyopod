"""RTC smoke checks."""

from __future__ import annotations

from pathlib import Path

from .types import CheckResult


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
            details="power backend disabled in config/power/backend.yaml",
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
