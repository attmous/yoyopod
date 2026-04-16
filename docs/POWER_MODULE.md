# Power Module

This document is the dedicated source of truth for YoyoPod's PiSugar-backed power subsystem.

Current target hardware:
- Raspberry Pi Zero 2W
- PiSugar 3 battery HAT

Board-specific overrides can now live under `config/boards/<board>/`.
Known hardware boards:
- `rpi-zero-2w` -> PiSugar watchdog on `i2c-1`
- `radxa-cubie-a7z` -> PiSugar watchdog on `i2c-7`

This module is responsible for:
- UPS-style telemetry
- low-battery warning
- graceful delayed shutdown
- shutdown-state persistence
- screen timeout and wake-on-activity
- app uptime and screen-on tracking
- PiSugar RTC read/sync/alarm control
- PiSugar software watchdog support
- user-facing power status UI

## Architecture

Main files:
- `src/yoyopod/power/models.py`
- `src/yoyopod/power/backend.py`
- `src/yoyopod/power/manager.py`
- `src/yoyopod/power/policies.py`
- `src/yoyopod/power/watchdog.py`
- `src/yoyopod/power/events.py`
- `src/yoyopod/coordinators/power.py`
- `src/yoyopod/ui/screens/system/power.py`
- `src/yoyopod/cli/pi/power.py` (`yoyoctl pi power battery`, `yoyoctl pi power rtc`)

Runtime flow:

```text
YoyoPodApp
  -> PowerManager
     -> PiSugarBackend
        -> Unix socket or TCP PiSugar server transport
     -> PiSugarWatchdog
        -> i2cget / i2cset
  -> PowerCoordinator
     -> EventBus
     -> PowerSafetyPolicy
     -> AppContext / CoordinatorRuntime
     -> current screen refresh
```

The app polls PiSugar on the coordinator thread, publishes typed power events, updates shared runtime state, and then applies safety or UI behavior from those events.

## Backends And Transports

`PowerManager` is the app-facing facade.

`PiSugarBackend` currently supports:
- automatic transport selection
- Unix socket transport via `/tmp/pisugar-server.sock`
- local TCP transport via `127.0.0.1:8423`
- model and firmware reads
- battery and charger telemetry
- RTC reads
- RTC sync and alarm control
- safe-shutdown configuration reads

Transport selection is controlled by:
- `power.transport: auto`
- `power.transport: socket`
- `power.transport: tcp`

`auto` tries the Unix socket first and then local TCP.

## Typed Data Model

The main snapshot type is `PowerSnapshot`.

It contains:
- `available`
- `checked_at`
- `source`
- `device`
- `battery`
- `rtc`
- `shutdown`
- `error`

Important nested fields:

`BatteryState`
- `level_percent`
- `voltage_volts`
- `charging`
- `power_plugged`
- `allow_charging`
- `output_enabled`
- `temperature_celsius`

`RTCState`
- `time`
- `alarm_enabled`
- `alarm_time`
- `alarm_repeat_mask`
- `adjust_ppm`

`ShutdownState`
- `safe_shutdown_level_percent`
- `safe_shutdown_delay_seconds`

## Configuration

Power configuration lives in `config/yoyopod_config.yaml` under `power:`.

Current keys:
- `enabled`
- `backend`
- `transport`
- `socket_path`
- `tcp_host`
- `tcp_port`
- `timeout_seconds`
- `poll_interval_seconds`
- `low_battery_warning_percent`
- `low_battery_warning_cooldown_seconds`
- `auto_shutdown_enabled`
- `critical_shutdown_percent`
- `shutdown_delay_seconds`
- `shutdown_command`
- `shutdown_state_file`
- `watchdog_enabled`
- `watchdog_timeout_seconds`
- `watchdog_feed_interval_seconds`
- `watchdog_i2c_bus`
- `watchdog_i2c_address`
- `watchdog_command_timeout_seconds`

Current defaults on `main`:
- poll interval: `30s`
- low-battery warning: `20%`
- critical shutdown: `10%`
- shutdown delay: `15s`
- watchdog: disabled by default

## Safety Policy

`PowerSafetyPolicy` is the rule layer for battery-driven behavior.

Current behavior:
- if PiSugar is unavailable, no safety decision is made
- if battery percentage is unavailable, no safety decision is made
- if external power is restored, a pending critical shutdown is cancelled
- if battery is below the warning threshold, a warning event is emitted with cooldown protection
- if battery is below the critical threshold and auto-shutdown is enabled, a delayed shutdown event is emitted once

Current typed safety events:
- `LowBatteryWarningRaised`
- `GracefulShutdownRequested`
- `GracefulShutdownCancelled`

## Graceful Shutdown Flow

When the critical threshold is crossed:
1. the app schedules a delayed shutdown
2. a fullscreen power overlay is shown
3. registered shutdown hooks run
4. the app stops
5. the configured system shutdown command is executed

The current persisted shutdown-state file is controlled by:
- `power.shutdown_state_file`

This is intended to save enough information for later debugging and future restore/recovery features.

## Screen Timeout And Runtime Tracking

The power module also owns inactivity-based display power behavior.

Current app behavior:
- track app uptime
- track screen-on time
- track idle time
- sleep the backlight after the configured timeout
- wake the screen on user activity
- suppress sleep while a critical-battery overlay or shutdown countdown is active

Relevant config:
- `display.backlight_timeout_seconds`
- fallback: `ui.screen_timeout_seconds`

Runtime state exposed today includes:
- `screen_awake`
- `screen_idle_seconds`
- `screen_on_seconds`
- `app_uptime_seconds`

## RTC Support

Supported RTC operations:
- read current RTC time
- sync Pi system time to RTC
- sync RTC time back to Pi
- set a wake alarm
- disable the wake alarm

Primary helper:

```bash
yoyoctl pi power rtc status
yoyoctl pi power rtc sync-to
yoyoctl pi power rtc sync-from
yoyoctl pi power rtc set-alarm --time 2026-04-06T07:30:00+02:00
yoyoctl pi power rtc disable-alarm
```

Remote helper:

```bash
yoyoctl remote rtc status --host rpi-zero
```

## Watchdog Support

The watchdog implementation is intentionally app-centric.

Current model:
- the app loop enables the PiSugar software watchdog
- the app feeds it at a configured interval while healthy
- ordinary app shutdown disables the watchdog
- battery-driven emergency shutdown suppresses feeding without disabling it

That means the watchdog remains a recovery backstop if graceful shutdown hangs.

The current implementation uses:
- `i2cget`
- `i2cset`

Required system package:
- `i2c-tools`

Important expectation:
- YoyoPod should be started by `systemd` on boot when watchdog mode is used

Current production unit:
- `deploy/systemd/yoyopod@.service`

## User-Facing UI

There is now a dedicated `Power Status` screen in the standard menu flow.

Implementation:
- `src/yoyopod/ui/screens/system/power.py`

Current screen design:
- page 1: battery / charging / external power / voltage / RTC / alarm
- page 2: uptime / screen activity / timeout / warning and critical thresholds / shutdown state / watchdog state

Current controls:
- standard mode:
  - `X/Y` or `left/right`: change page
  - `A`: next page
  - `B`: back
- one-button mode:
  - `tap`: next page
  - `double tap`: next page
  - `hold`: back

Note:
- the Whisplay root hub now includes `Power` as a 4th card beside `Now Playing`, `Playlists`, and `Calls`
- the same `Power Status` screen is still available from the standard menu flow on multi-button devices

## Diagnostics And Validation

Focused power helper:

```bash
yoyoctl pi power battery
```

This prints:
- availability
- model
- battery percent
- voltage
- temperature
- charging state
- external power state
- RTC state
- safe-shutdown values
- watchdog configuration

Remote power helper:

```bash
yoyoctl remote power --host rpi-zero
```

Smoke validation:

```bash
yoyoctl pi validate smoke --with-power
yoyoctl pi validate smoke --with-power --with-rtc
```

Recommended hardware sequence:
1. `uv run pytest -q`
2. `yoyoctl pi validate smoke --with-power --with-rtc`
3. `yoyoctl pi power battery`
4. `yoyoctl pi power rtc status`

## Dependencies On The Pi

Expected packages or services:
- `pisugar-server`
- `i2c-tools`

The PiSugar server should expose at least one of:
- `/tmp/pisugar-server.sock`
- `127.0.0.1:8423`

## Troubleshooting

If power telemetry fails:
- check `pisugar-server` is running
- check `/tmp/pisugar-server.sock` exists or TCP `8423` is listening
- run `yoyoctl pi power battery`
- run `i2cdetect -y 1` on Raspberry Pi Zero 2W hardware
- run `i2cdetect -y 7` on Radxa Cubie A7Z hardware

Expected PiSugar 3 visibility usually includes:
- `0x57`
- `0x68`

If watchdog commands fail:
- confirm `i2c-tools` is installed
- confirm the configured bus/address matches the HAT
- confirm passwordless `sudo` is not required for your chosen flow, because the watchdog uses direct I2C tools

If RTC sync behaves strangely:
- validate with `yoyoctl pi power rtc status`
- check whether the distro image has a working `hwclock` path

If the app shuts down too aggressively:
- raise `critical_shutdown_percent`
- increase `shutdown_delay_seconds`
- check whether the battery is reporting charging or external power correctly

## Current Boundaries

Supported today:
- telemetry
- warnings
- graceful shutdown
- runtime tracking
- RTC tooling
- watchdog tooling
- user-facing power status UI

Not yet productized:
- power settings UI
- RTC alarm scheduling from inside the app UI
- battery-history graphs
- adaptive brightness or battery-aware performance modes
- resume/restore flow based on saved shutdown state

## Related Documents

- `README.md`
- `docs/RPI_SMOKE_VALIDATION.md`
- `docs/PI_DEV_WORKFLOW.md`
- `deploy/systemd/yoyopod@.service`
