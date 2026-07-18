---
title: Device Overview & Specs
description: The whole machine on one page, plus the spec table.
---

*One page that names every hardware subsystem and links its deep dive.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- What YoYoPod is at the hardware level: a screen-light, single-button audio companion for kids ages 7-14
- The physical shape of the device: one small calm screen, one side button, speaker, microphone — no camera, no browser, no app store
- The design stance: everything the hardware includes (and excludes) follows from "before the smartphone", not from feature ambition
- How this page relates to the deep dives: one paragraph per subsystem, each linking to its own page
- Spec TABLE: screen (~240x280 portrait), battery capacity (TBD), radios (4G + GPS; Wi-Fi/Bluetooth role TBD), audio (speaker + microphone, codec TBD), enclosure dimensions and weight (TBD)

## Key components

- The glass and the button — see [The Glass: Display & Input](/builders/hardware/display/)
- Speaker, microphone, and the signal chain — see [Audio Path](/builders/hardware/audio/)
- Battery, charging, and power management — see [Power & Battery](/builders/hardware/power/)
- 4G modem, SIM, and GPS — see [Connectivity: 4G & GPS](/builders/hardware/connectivity/)
- Compute: Raspberry Pi Zero 2W in the prototype; product board (TBD) — see [From Prototype to Product](/builders/hardware/roadmap/)

## Interfaces & contracts

- How each subsystem is exposed to software: buses, kernel interfaces, and the worker process that owns it (per-subsystem detail on the deep-dive pages)
- The boundary rule: hardware details stay behind worker processes so the rest of the Rust runtime never talks to a bus directly
- Where the as-built engineering docs (`website/` in the repository) document the current wiring in depth
- What a hardware abstraction contract for the product board would need to preserve (TBD)

## Today vs. target

- Today: Raspberry Pi Zero 2W + PiSugar Whisplay HAT — explicitly a prototype path
- Target: a product board that may integrate its own display, audio, power, and modem choices
- Which specs are fixed by product intent (one button, small portrait screen, no camera) vs. open for the product board (TBD)
- Pointer to [From Prototype to Product](/builders/hardware/roadmap/) for the migration story

## Open questions

- TODO: Which spec-table values can we commit to publicly now, and which stay TBD until a product board is selected?
- TODO: Do Wi-Fi and Bluetooth appear in the product spec at all, or is 4G the only radio we promise?
- TODO: What enclosure durability targets (drop, water resistance) does a kids-carry-it-daily device need to state?
- TODO: Should the spec table describe the prototype, the target product, or both side by side?
