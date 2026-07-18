---
title: From Prototype to Product
description: "Hardware V0 “Dawn” today — off-the-shelf boards wired together; V1 “Daylight” is the designed PCB."
---

*The honest hardware trajectory: V0 “Dawn” today, V1 “Daylight” ahead.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## Overview

The hardware generations carry names from the brand's Sunrise & Midnight
story:

| Generation | What it is |
| --- | --- |
| **V0 “Dawn”** — today | The prototype rig: boards and kits **available on the market, wired together** to realize the kid's device fast. The Raspberry Pi Zero 2W, the Whisplay HAT, the PiSugar 3, and the SIM7600 modem were picked because they are **off the shelf** — chosen for speed of prototyping, not designed for this product. |
| **V1 “Daylight”** — next | The **designed PCB**: components picked per the product design and soldered onto one purpose-built board — its own display, audio, power, and modem choices. V1 matures through the industry build stages: **EVT** (engineering validation — does the board work), **DVT** (design validation — does the *product* work, enclosure and all), **PVT** (production validation — can the line build it at quality). |

V0 is explicitly a **prototype path, not a permanent promise**. What stays
constant across the V0 → V1 transition is set by intent, not by the
prototype: one button, a small calm screen, speaker + microphone, 4G + GPS,
no camera.

The project keeps a living **honesty doc** — the roadmap — that tracks
what works, what is broken, and when it gets fixed. Its current subject is
the staged Rust rebuild of the operator tooling around the hardware, done
in business-need-sized rounds rather than a line-by-line port, because a
port would rebuild assumptions that no longer hold.

## Key components

*Placeholder — no as-built content yet.*

- Compute: Pi Zero 2W in V0; V1 SoC/module selection criteria (cost, power, Linux support) (TBD)
- Display: V0's SPI panel today; V1 may ship its own display and driver — see [The Canvas: Display & Input](/builders/hardware/display/)
- Peripherals bundled on the Whisplay HAT in V0 (display, audio) that the V1 board would integrate directly
- Enclosure and industrial design: from bare V0 rig to a kid-proof V1 shell (TBD)

## Interfaces & contracts

*Placeholder — no as-built content yet.*

- The software bet that makes the V0 → V1 swap survivable: hardware sits behind Rust runtime worker processes, so board changes land in drivers and workers, not in every feature
- Which contracts must hold across the swap: button events, display surface, audio in/out, modem and GPS access, power telemetry
- Where per-board detail belongs: the as-built engineering docs (`website/` in the repository) describe the V0 wiring in depth
- How we would validate a candidate V1 board against the existing runtime (EVT bring-up checklist TBD)

## Today vs. target

Today, everything runs on the V0 “Dawn” rig, and that path stays the
reference while it earns its keep. Where the rebuild rounds stand (as of
2026-07-12):

| Round | Scope | State |
| --- | --- | --- |
| 0 | Demolition + scaffolding | merged |
| 1 | Daily dev loop (deploy, status, logs against the device) | merged |
| 2 | Restore **hardware validation** on the device | in progress |
| 3 | Restore the prod release pipeline | not started |
| 4+ | Diagnostics (voip / power / network / UI host) | not started |

Carried honestly from the as-built roadmap: prod slot builds are disabled
(no new release tarballs until Round 3 lands), on-device diagnostics are
gone until Round 4+ (SSH manually until then), and two validation stages
(voip, cloud-voice) are stubs pending the Round 2 follow-up. The target
remains V1 “Daylight”: a purpose-built board in a kid-proof enclosure
running the same Rust runtime and UI, earned through EVT → DVT → PVT.
What we will not do: chase hardware features — camera, bigger screen, app
store — that break the "before the smartphone" position. The explicit
decision gates for starting V1 are not yet defined (see the open questions
below).

## Open questions

- TODO: What are the explicit decision gates (units, cost, battery data) that trigger the start of V1 “Daylight”?
- TODO: Do we design our own board or build on an existing compute module family?
- TODO: How long do we keep the V0 Pi + HAT path alive as a community/dev target after V1 exists?
- TODO: Which certifications (CE, FCC, kids-product safety) shape the product-board timeline and budget?

:::note[Sources]
Condensed from
[`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md)
and the as-built docs site (`website/` in the repository): the product
Roadmap page.
:::
