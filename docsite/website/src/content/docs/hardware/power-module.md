---
title: Power Module
description: The PiSugar 3 subsystem — telemetry, the safety-driven shutdown, the hardware watchdog, RTC, and troubleshooting.
---

The PiSugar 3 HAT owns power truth: battery telemetry, charging state,
the RTC, and a hardware watchdog. The runtime side is documented in the
runtime guide ([the boiler room](/runtime/workers/power/) and the
[low-battery house rule](/runtime/routing-and-policies/#low-battery-ends-the-show--safely));
this page carries the hardware-level contract and field troubleshooting.

## Responsibilities

UPS telemetry · low-battery warning · graceful delayed shutdown with
persisted shutdown state · screen timeout and wake-on-activity ·
uptime/screen-on tracking · RTC read/sync/alarm · the software-fed
hardware watchdog · the Power Status UI.

## Transports

`pisugar-server` over the Unix socket `/tmp/pisugar-server.sock` or TCP
`127.0.0.1:8423`; `power.transport: auto` tries the socket first. The
watchdog bypasses the server entirely — raw I²C via `i2cget`/`i2cset`
(bus 1, address `0x57` on the Zero 2W).

## The data model

A power snapshot carries: **battery** (level %, voltage, charging,
power-plugged, allow-charging, output-enabled, temperature), **RTC**
(time, alarm enabled/time/repeat-mask, adjust-ppm), and **shutdown**
(safe-shutdown level + delay), plus availability and error fields.

## Config (`config/power/backend.yaml`, defaults)

| Group | Keys (defaults) |
| --- | --- |
| Backend | `enabled`, `backend: pisugar`, `transport: auto`, socket/TCP endpoints, `timeout_seconds` |
| Polling | `poll_interval_seconds: 30` |
| Safety | `low_battery_warning_percent: 20`, `warning_cooldown: 300 s`, `auto_shutdown_enabled`, `critical_shutdown_percent: 10`, `shutdown_delay_seconds: 15`, `shutdown_command`, `shutdown_state_file` |
| Watchdog | `watchdog_enabled` (default off), `timeout_seconds`, `feed_interval_seconds`, I²C bus/address |

:::caution[This file has two readers]
The runtime reads the safety thresholds from this same file for its
shutdown policy — see the
[dual-reader callout](/runtime/configuration/#the-worker--config-map).
:::

## The safety policy, in rules

No decision is made if PiSugar (or the battery %) is unavailable —
absence of data never triggers a shutdown. External power restoration
cancels a pending shutdown. Below warning → a cooldown-protected
warning. Below critical with auto-shutdown enabled → **one** delayed
shutdown: overlay shown, watchdog *suppressed* (not disabled — it stays
a recovery backstop), state file written, system shutdown command run.

## Field troubleshooting

- Query PiSugar directly: `pisugar-shell` → `get battery`, `get model`,
  `get rtc_time`.
- `i2cdetect -y 1` should show `0x57` and `0x68`. **If `0x57` drops but
  `0x68` responds, suspect pogo-pin contact** under the GPIO header —
  clean the pads, reseat, power-cycle, restart `pisugar-server`.
- Watchdog failures → confirm `i2c-tools` installed and the bus/address
  match config.
- Shutdowns too aggressive → raise `critical_shutdown_percent` or the
  delay, and verify charging/external-power reporting first.

Dependencies on the Pi: `pisugar-server`, `i2c-tools`. The runtime's
systemd unit orders itself `After=pisugar-server.service`.

:::note[Canonical source — with a caveat]
Condensed from
[`docs/hardware/POWER_MODULE.md`](https://github.com/attmous/yoyopod/blob/main/docs/hardware/POWER_MODULE.md).
Parts of the canonical doc still reference the retired Python module
paths and deleted `yoyopod pi power` commands (returning in Round 4 —
see the [Roadmap](/product/roadmap/)); the current implementation lives
in `device/power/`. The config keys, safety policy, and troubleshooting
above are verified against the Rust code.
:::
