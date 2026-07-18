---
title: "Connectivity: 4G & GPS"
description: The modem, the SIM, and location hardware.
---

*The 4G modem, SIM provisioning, and GPS — the hardware behind Locate and Talk.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## Overview

Connectivity exists for a short list: whitelist calls, voice messages,
live-ish location, and the cloud link — nothing else, because there is no
browser or app store to feed. The modem is an off-the-shelf part of the V0
“Dawn” rig ([From Prototype to Product](/builders/hardware/roadmap/)). The device still works offline: local-first
music and stories do not depend on the modem. The honesty rule for location
stands: GPS gives **live-ish** position, and we never call it real-time. As
built today, the radio is a **SIM7600-family 4G modem**, owned end to end
by the network worker: serial AT-command bring-up (SIM, registration,
signal, carrier, GPS), the pppd process that turns a registered modem into
an IP link, and link health monitoring.

## Key components

- **The modem** — a SIM7600 over a serial port. Config names the modem
  *function*: port aliases like `sim7600:if02` resolve through
  `/dev/serial/by-id`, not a device node that renumbers.
- **The data link** — a spawned `pppd` (dialed with `ATD*99#`, run via
  `sudo -n` when not root); link health is probed through
  `/sys/class/net/ppp0`.
- **GPS access** — the prototype uses the modem's own GPS; the worker can
  query fixes and converts raw `ddmm.mmmm` coordinates to clean decimal
  degrees for consumers.

### SIM and antenna

*Placeholder — no as-built content yet.*

- SIM: physical SIM vs. eSIM, and how a family gets a provisioned SIM in the box (TBD)
- GPS receiver and antenna path (shared with or separate from the modem — product TBD)
- Antenna design and placement in a small kid-carried enclosure (TBD)

## Interfaces & contracts

The network worker runs the richest state machine in the system, because
radio reality demands it: `Off` → `Probing` (first AT contact) → `Ready`
(SIM checked) → `Registering` → `Registered` (signal and carrier read) →
`PppStarting` → **`Online`**, with `Recovering` and `Degraded` on the side.
Recovery is exponential backoff, 1 second doubling to a 30-second cap, and
faults are classified: transport hiccups, registration timeouts, and PPP
failures are retryable; SIM PIN required-but-missing, PUK, and no-SIM are
fatal — retrying a locked SIM helps nobody. This is the one worker with
real internal recovery: the process never dies to recover; it walks its own
state machine back to `Online`. If config fails to load, it boots
`Degraded` and never attempts bring-up — visible, not silent. The command
surface is the smallest in the system (health, GPS query, modem reset,
shutdown), and snapshot events are deduplicated so a steady-state radio
doesn't flood the runtime.

### From GPS fix to a location feature

*Placeholder — no as-built content yet.*

- How GPS fixes flow from hardware to the Locate experience — see [Locate](/apps/locate/); the worker can query fixes today, but no location feature is built on top yet
- The contract a different product modem must satisfy (AT/QMI surface, GPS access, power states) so workers survive the swap (TBD)

## Today vs. target

Today: a SIM7600-family modem on the prototype path, supervised by the
network worker as described above. Target: a product-board modem and
antenna design chosen for cost, power draw, and regional band coverage —
still to be decided, along with carrier/MVNO strategy, roaming behavior,
and modem power management for battery life. Fixed by intent: 4G + GPS
serve Talk and Locate only. GPS today is hardware-capable but feature-idle:
fixes are queryable, and nothing user-facing consumes them yet.

## Open questions

- TODO: Physical SIM or eSIM — and who provisions it, the family or us as part of the product?
- TODO: Which regional 4G band sets must the product modem cover for the launch markets?
- TODO: What is the modem's power budget, and how aggressively can it sleep without missing incoming calls?
- TODO: Does the product keep using modem-integrated GPS, or move to a dedicated receiver?

:::note[Sources]
Condensed from the as-built docs site (`website/` in the repository): the
Runtime & Workers Guide's network worker profile ("The Radio Room").
:::
