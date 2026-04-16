"""Tests for the app-facing power manager facade."""

from __future__ import annotations

from datetime import datetime, timezone
from yoyopod.config import ConfigManager
from yoyopod.power.manager import PowerManager
from yoyopod.power.models import BatteryState, PowerConfig, PowerSnapshot, RTCState


class FakeBackend:
    """Minimal power backend double for manager tests."""

    def __init__(self, snapshot: PowerSnapshot, probe_result: bool = True) -> None:
        self.snapshot = snapshot
        self.probe_result = probe_result
        self.refresh_calls = 0
        self.sync_to_rtc_calls = 0
        self.sync_from_rtc_calls = 0
        self.set_alarm_calls: list[tuple[datetime, int]] = []
        self.disable_alarm_calls = 0

    def probe(self) -> bool:
        return self.probe_result

    def get_snapshot(self) -> PowerSnapshot:
        self.refresh_calls += 1
        return self.snapshot

    def sync_time_to_rtc(self) -> None:
        self.sync_to_rtc_calls += 1

    def sync_time_from_rtc(self) -> None:
        self.sync_from_rtc_calls += 1

    def set_rtc_alarm(self, when: datetime, repeat_mask: int = 127) -> None:
        self.set_alarm_calls.append((when, repeat_mask))

    def disable_rtc_alarm(self) -> None:
        self.disable_alarm_calls += 1


class ExplodingBackend:
    """Backend double that raises on refresh."""

    def probe(self) -> bool:
        return False

    def get_snapshot(self) -> PowerSnapshot:
        raise RuntimeError("backend boom")


class FakeWatchdog:
    """Minimal watchdog double for power-manager tests."""

    def __init__(self) -> None:
        self.enable_calls = 0
        self.feed_calls = 0
        self.disable_calls = 0

    def enable(self, timeout_seconds: int | None = None) -> None:
        self.enable_calls += 1

    def feed(self) -> None:
        self.feed_calls += 1

    def disable(self) -> None:
        self.disable_calls += 1


def test_power_manager_refresh_caches_latest_snapshot() -> None:
    """Refreshing through the manager should retain the latest backend snapshot."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 4, 12, 0, 0),
        battery=BatteryState(level_percent=83.0),
    )
    backend = FakeBackend(snapshot)
    manager = PowerManager(PowerConfig(), backend=backend)

    result = manager.refresh()

    assert result is snapshot
    assert manager.get_snapshot() is snapshot
    assert manager.get_battery_percentage() == 83.0
    assert backend.refresh_calls == 1


def test_power_manager_returns_unavailable_snapshot_when_backend_refresh_fails() -> None:
    """Refresh failures should be captured as an unavailable snapshot instead of bubbling up."""

    manager = PowerManager(PowerConfig(), backend=ExplodingBackend())

    snapshot = manager.refresh()

    assert snapshot.available is False
    assert snapshot.error == "backend boom"


def test_power_manager_reads_power_config_from_config_manager(tmp_path) -> None:
    """Typed application settings should feed the power manager configuration."""

    config_dir = tmp_path
    hardware_file = config_dir / "device" / "hardware.yaml"
    hardware_file.parent.mkdir(parents=True, exist_ok=True)
    hardware_file.write_text(
        """
power:
  enabled: true
  transport: tcp
  tcp_host: "192.168.1.10"
  tcp_port: 9000
  timeout_seconds: 5.0
  low_battery_warning_percent: 18.0
  critical_shutdown_percent: 7.5
  shutdown_delay_seconds: 20.0
  shutdown_command: "sudo -n poweroff"
  watchdog_enabled: true
  watchdog_timeout_seconds: 90
  watchdog_feed_interval_seconds: 30.0
  watchdog_i2c_address: 0x58
""".strip(),
        encoding="utf-8",
    )

    config_manager = ConfigManager(config_dir=str(config_dir))
    manager = PowerManager.from_config_manager(config_manager)

    assert manager.config.enabled is True
    assert manager.config.transport == "tcp"
    assert manager.config.tcp_host == "192.168.1.10"
    assert manager.config.tcp_port == 9000
    assert manager.config.timeout_seconds == 5.0
    assert manager.config.low_battery_warning_percent == 18.0
    assert manager.config.critical_shutdown_percent == 7.5
    assert manager.config.shutdown_delay_seconds == 20.0
    assert manager.config.shutdown_command == "sudo -n poweroff"
    assert manager.config.watchdog_enabled is True
    assert manager.config.watchdog_timeout_seconds == 90
    assert manager.config.watchdog_feed_interval_seconds == 30.0
    assert manager.config.watchdog_i2c_address == 0x58


def test_power_manager_runs_shutdown_hooks_and_reports_failures() -> None:
    """Shutdown hooks should all run while reporting the ones that fail."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 4, 12, 0, 0),
    )
    manager = PowerManager(PowerConfig(), backend=FakeBackend(snapshot))
    calls: list[str] = []

    manager.register_shutdown_hook("save", lambda: calls.append("save"))

    def failing_hook() -> None:
        calls.append("failing")
        raise RuntimeError("hook boom")

    manager.register_shutdown_hook("failing", failing_hook)

    failed_hooks = manager.run_shutdown_hooks()

    assert calls == ["save", "failing"]
    assert failed_hooks == ["failing"]


def test_power_manager_request_system_shutdown_uses_configured_command() -> None:
    """The configured shutdown command should be split and passed to the runner."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 4, 12, 0, 0),
    )
    commands: list[list[str]] = []

    manager = PowerManager(
        PowerConfig(shutdown_command="sudo -n shutdown -h now"),
        backend=FakeBackend(snapshot),
        shutdown_runner=lambda command: commands.append(command) or 0,
    )

    assert manager.request_system_shutdown() is True
    assert commands == [["sudo", "-n", "shutdown", "-h", "now"]]


def test_power_manager_exposes_rtc_sync_and_alarm_helpers() -> None:
    """RTC sync and alarm operations should delegate to the backend and return fresh state."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 4, 12, 0, 0),
        rtc=RTCState(time=datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)),
    )
    backend = FakeBackend(snapshot)
    manager = PowerManager(PowerConfig(), backend=backend)
    alarm_time = datetime(2026, 4, 6, 7, 30, tzinfo=timezone.utc)

    rtc_state = manager.sync_time_to_rtc()
    rtc_state = manager.sync_time_from_rtc()
    rtc_state = manager.set_rtc_alarm(alarm_time, repeat_mask=31)
    rtc_state = manager.disable_rtc_alarm()

    assert backend.sync_to_rtc_calls == 1
    assert backend.sync_from_rtc_calls == 1
    assert backend.set_alarm_calls == [(alarm_time, 31)]
    assert backend.disable_alarm_calls == 1
    assert backend.refresh_calls == 4
    assert rtc_state.time == datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)


def test_power_manager_wraps_watchdog_lifecycle() -> None:
    """Watchdog enable/feed/disable should delegate to the configured controller."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 4, 12, 0, 0),
    )
    watchdog = FakeWatchdog()
    manager = PowerManager(
        PowerConfig(watchdog_enabled=True),
        backend=FakeBackend(snapshot),
        watchdog=watchdog,
    )

    assert manager.enable_watchdog() is True
    assert manager.feed_watchdog() is True
    assert manager.disable_watchdog() is True
    assert watchdog.enable_calls == 1
    assert watchdog.feed_calls == 1
    assert watchdog.disable_calls == 1
