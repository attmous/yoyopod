---
title: Power & Battery
description: Battery, charging, and power management.
---

*Battery, charging, the power worker, and safe-shutdown behavior.*

## Overview

The **PiSugar 3 HAT owns power truth**: battery telemetry, charging state,
the real-time clock, and a hardware watchdog that power-cycles the board if
software stops feeding it. Like the rest of the V0 “Dawn” rig it is an
off-the-shelf board ([From Prototype to Product](/builders/hardware/roadmap/)). On the software side, the power worker is the
single owner of that truth — it polls telemetry (every 30 seconds by
default), applies the low-battery safety policy, and brings the device down
cleanly before the battery does it uncleanly.

## Key components

- **Battery + telemetry** — the PiSugar 3 reports level, voltage, charging
  and external-power state, and temperature through `pisugar-server` (Unix
  socket first, TCP fallback).
- **RTC** — time sync in both directions plus alarms, owned by the same
  worker.
- **Hardware watchdog** — bypasses the server entirely: raw I²C on bus 1,
  address `0x57`, fed on a timer (default every 15 seconds).
- **The power worker** — the Rust runtime process that wraps all of the
  above. When the backend is disabled in config, the domain reports
  unavailable rather than faking numbers.

## Interfaces & contracts

The safety policy, in rules (defaults from the power config):

| Rule | Behavior |
| --- | --- |
| No data | absence of telemetry **never** triggers a shutdown |
| Below warning (20%) | a cooldown-protected warning (5-minute cooldown) |
| Below critical (10%) | **one** delayed shutdown (15 s): overlay shown, state file written, system shutdown run |
| Power restored | a pending shutdown is cancelled |

The watchdog has two distinct off-switches, and the difference matters:
`watchdog_suppress` stops feeding *without* disabling — used before an
intentional low-battery shutdown so the board powers down cleanly while the
watchdog stays a recovery backstop — while `watchdog_disable` turns it off
entirely on worker stop. The power config file has **two readers**: the
power worker and, independently, the runtime's shutdown policy read the
same safety thresholds. The systemd unit orders the runtime after
`pisugar-server` — an ordering preference, not a hard requirement; without
it, boot proceeds and power simply reports unavailable.

### The pogo-pin lesson

The PiSugar connects through pogo pins under the GPIO header. If I²C
address `0x57` drops off the bus while `0x68` still responds, suspect
pogo-pin contact: clean the pads, reseat, power-cycle, restart
`pisugar-server`. This is the first field check before blaming software.

## Today vs. target

Today: the prototype power path on the Pi Zero 2W + PiSugar, with
low-battery safe shutdown implemented (power worker + watchdog) and the
config keys and safety policy verified against the Rust code. One honesty
flag carried from the as-built docs: parts of the canonical power doc still
reference retired Python-era diagnostic commands, which return in a later
rebuild round — the current implementation is the Rust worker. Target: a
product board with an integrated charge controller and fuel gauge chosen
for the battery-day goal — still to be decided. Fixed by intent: fail
calm — warn early, shut down cleanly, never corrupt state.

## Open questions

- TODO: What battery-life number do we commit to publicly, and under which usage profile is it measured?
- TODO: Which charging connector does the product use, and is charging-dock hardware in or out of scope?
- TODO: At what battery threshold should the device notify the parent app before it shuts down?
- TODO: Is the battery user-replaceable or service-only, and what does that mean for the enclosure?

:::note[Sources]
Condensed from
[`docs/hardware/POWER_MODULE.md`](https://github.com/attmous/yoyopod/blob/main/docs/hardware/POWER_MODULE.md)
and the as-built docs site (`website/` in the repository): the Power Module
page and the power worker profile ("The Boiler Room").
:::
