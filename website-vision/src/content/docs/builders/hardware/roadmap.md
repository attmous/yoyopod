---
title: From Prototype to Product
description: Pi Zero 2W + HAT today; what a product board changes.
---

*The honest hardware trajectory: prototype path today, product board decisions ahead.*

:::caution[Partially filled]
Sections marked *Placeholder* have no as-built content yet; everything else is condensed from the repository (see Sources at the bottom).
:::

## Overview

The honest framing first: the Raspberry Pi Zero 2W + PiSugar Whisplay HAT
is a **prototype path, not a permanent promise**. We prototype on
off-the-shelf hardware to iterate on the experience before committing to a
board spin; "product board" means purpose-built hardware that may ship its
own display, audio, power, and modem choices. What stays constant across
the transition is set by intent, not by the prototype: one button, a small
calm screen, speaker + microphone, 4G + GPS, no camera.

The project keeps a living **honesty doc** — the roadmap — that tracks
what works, what is broken, and when it gets fixed. Its current subject is
the staged Rust rebuild of the operator tooling around the hardware, done
in business-need-sized rounds rather than a line-by-line port, because a
port would rebuild assumptions that no longer hold.

## Key components

*Placeholder — no as-built content yet.*

- Compute: Pi Zero 2W today; product SoC/module selection criteria (cost, power, Linux support) (TBD)
- Display: prototype SPI panel today; the product device may ship its own display and driver — see [The Glass: Display & Input](/builders/hardware/display/)
- Peripherals bundled on the Whisplay HAT today (display, audio, power) that a product board would integrate directly
- Enclosure and industrial design: from bare prototype to a kid-proof product shell (TBD)

## Interfaces & contracts

*Placeholder — no as-built content yet.*

- The software bet that makes the swap survivable: hardware sits behind Rust runtime worker processes, so board changes land in drivers and workers, not in every feature
- Which contracts must hold across the swap: button events, display surface, audio in/out, modem and GPS access, power telemetry
- Where per-board detail belongs: the as-built engineering docs (`website/` in the repository) describe the prototype wiring in depth
- How we would validate a candidate product board against the existing runtime (bring-up checklist TBD)

## Today vs. target

Today, everything runs on the Pi Zero 2W + Whisplay HAT prototype, and
that path stays the reference while it earns its keep. Where the rebuild
rounds stand (as of 2026-07-12):

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
remains a purpose-built board in a kid-proof enclosure running the same
Rust runtime and UI. What we will not do: chase hardware features —
camera, bigger screen, app store — that break the "before the smartphone"
position. The explicit decision gates for moving to a product board are
not yet defined (see the open questions below).

## Open questions

- TODO: What are the explicit decision gates (units, cost, battery data) that trigger the move from prototype to product board?
- TODO: Do we design our own board or build on an existing compute module family?
- TODO: How long do we keep the Pi + HAT path alive as a community/dev target after a product board exists?
- TODO: Which certifications (CE, FCC, kids-product safety) shape the product-board timeline and budget?

:::note[Sources]
Condensed from
[`docs/ROADMAP.md`](https://github.com/attmous/yoyopod/blob/main/docs/ROADMAP.md)
and the as-built docs site (`website/` in the repository): the product
Roadmap page.
:::
