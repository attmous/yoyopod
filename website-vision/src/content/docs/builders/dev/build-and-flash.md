---
title: Build & Flash a Device
description: From checkout to a running device.
---

*The path from source checkout to a device running your build.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- The promise of this page: checkout, build, deploy, and see the Hub wheel on the glass
- Prerequisites: a working host setup from [Dev Environment](/builders/dev/environment/)
- Target hardware today: the prototype path — Raspberry Pi Zero 2W + PiSugar Whisplay HAT
- What "running" means: the Rust runtime up under systemd, workers supervised, UI on screen

## Build

- Building the device workspace under `device/` for the host vs. for the device target
- Cross-compiling for the Pi Zero 2W — toolchain target and any helper tooling (TBD)
- Building the LVGL-based UI and its assets as part of the workspace build
- What a release-style build adds over a dev build (TBD)
- Where build artifacts land and how they are versioned (TBD)

## Deploy to hardware

- Preparing a prototype device: base OS image and one-time provisioning steps (TBD)
- Getting a build onto the device and restarting the runtime under systemd
- First-boot sanity checks: the Hub appears, the one side button responds to tap / double-tap / hold
- Iteration loop: how fast can edit-build-deploy be, and what shortcuts exist (TBD)
- Note: a product board with its own display may replace the prototype path — deploy steps will change with it

## Today vs. target

- Today: deployment targets the Pi-based prototype only
- Target: a single documented command path from checkout to running device
- Target: deploy story for the future product board, once that hardware exists (see [Hardware Roadmap](/builders/hardware/roadmap/))
- Open dependency: how much of this page survives the prototype-to-product transition

## Open questions

- TODO: Do we document a golden base image for the prototype, or a from-scratch provisioning script?
- TODO: What is the supported transfer mechanism for pushing builds to a device, and is it the same for all contributors?
- TODO: How do we version deployed builds on-device so a tester can report exactly what they are running?
