---
title: From Prototype to Product
description: Pi Zero 2W + HAT today; what a product board changes.
---

*The honest hardware trajectory: prototype path today, product board decisions ahead.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- The honest framing: Raspberry Pi Zero 2W + PiSugar Whisplay HAT is a prototype path, not a permanent promise
- Why we prototype on off-the-shelf hardware: iterate on the experience before committing to a board spin
- What "product board" means here: purpose-built hardware that may ship its own display, audio, power, and modem choices
- What stays constant across the transition: one button, small calm screen, speaker + mic, 4G + GPS, no camera

## Key components

- Compute: Pi Zero 2W today; product SoC/module selection criteria (cost, power, Linux support) (TBD)
- Display: prototype SPI panel today; the product device may ship its own display and driver — see [The Glass: Display & Input](/builders/hardware/display/)
- Peripherals bundled on the Whisplay HAT today (display, audio, power) that a product board would integrate directly
- Enclosure and industrial design: from bare prototype to a kid-proof product shell (TBD)

## Interfaces & contracts

- The software bet that makes the swap survivable: hardware sits behind Rust runtime worker processes, so board changes land in drivers and workers, not in every feature
- Which contracts must hold across the swap: button events, display surface, audio in/out, modem and GPS access, power telemetry
- Where per-board detail belongs: the as-built engineering docs (`website/` in the repository) describe the prototype wiring in depth
- How we would validate a candidate product board against the existing runtime (bring-up checklist TBD)

## Today vs. target

- Today: everything runs on the Pi Zero 2W + Whisplay HAT prototype, and that path stays the reference while it earns its keep
- Next: decision gates for a product board — cost targets, battery-day power budget, display choice, modem selection (all TBD)
- Target: a purpose-built board in a kid-proof enclosure, running the same Rust runtime and LVGL UI
- What we will not do: chase hardware features (camera, bigger screen, app store) that break the "before the smartphone" position

## Open questions

- TODO: What are the explicit decision gates (units, cost, battery data) that trigger the move from prototype to product board?
- TODO: Do we design our own board or build on an existing compute module family?
- TODO: How long do we keep the Pi + HAT path alive as a community/dev target after a product board exists?
- TODO: Which certifications (CE, FCC, kids-product safety) shape the product-board timeline and budget?
