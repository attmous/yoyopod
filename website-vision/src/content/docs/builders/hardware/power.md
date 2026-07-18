---
title: Power & Battery
description: Battery, charging, and power management.
---

*Battery, charging, the power worker, and safe-shutdown behavior.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- Why power is a trust feature: a dead device means no calls home and no location, so battery behavior is a parent promise
- The battery-day target: what "lasts the school day" means in hours and duty cycle (values TBD)
- The three power stories: everyday charging, low-battery behavior, and safe shutdown
- How the parent app should surface battery state (planned, part of future parent-app work)

## Key components

- Battery pack: prototype battery on the PiSugar Whisplay HAT path; product cell chemistry and capacity (TBD)
- Charging hardware: connector, charge controller, and charge-state signaling (product parts TBD)
- Fuel gauge / battery telemetry source the software reads (prototype vs. product board TBD)
- The power worker: the Rust runtime process that owns power management today

## Interfaces & contracts

- The power worker as the single owner of battery state, charge state, and shutdown decisions
- Low-battery safe shutdown as it exists today: power worker plus watchdog bring the device down cleanly
- How other workers learn about power events (battery level, charger attach/detach) — contract shape TBD
- What the runtime guarantees on brownout or abrupt power loss, and what filesystem/state protection backs it (TBD)

## Today vs. target

- Today: prototype power path on the Pi Zero 2W + Whisplay HAT; low-battery safe shutdown implemented (power worker + watchdog)
- Target: product board with an integrated charge controller and fuel gauge chosen for the battery-day target (TBD)
- Fixed by intent: the device must fail calm — warn early, shut down cleanly, never corrupt state
- Open: charging connector choice, charge-time target, and battery replaceability/serviceability (TBD)

## Open questions

- TODO: What battery-life number do we commit to publicly, and under which usage profile is it measured?
- TODO: Which charging connector does the product use, and is charging-dock hardware in or out of scope?
- TODO: At what battery threshold should the device notify the parent app before it shuts down?
- TODO: Is the battery user-replaceable or service-only, and what does that mean for the enclosure?
