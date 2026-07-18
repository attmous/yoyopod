---
title: Testing & Validation
description: What green means, on host and on hardware.
---

*The testing story: host tests, on-device validation stages, and CI.*

:::caution[Vision stub]
Placeholder in the vision docs — the structure is decided, the content is
not written yet. As-built engineering docs live in the main docs site
(`website/` in the repository).
:::

## Overview

- The layered testing model: fast host tests first, on-device validation last
- What "green" is allowed to mean at each layer — and what it deliberately does not prove
- Why a device for kids raises the bar: calls, location, and battery behavior must be validated, not assumed
- How CI fits in: what runs automatically vs. what a human runs on hardware

## On the host

- Unit and integration tests across the Rust workspace under `device/`
- Testing workers in isolation vs. testing the runtime supervising them together
- Simulating what the host cannot have: 4G modem, GPS, the physical button, audio hardware (approach TBD)
- Running the UI on the host for fast iteration without a device (extent TBD)
- The pre-push gate: which checks a contributor runs locally before CI sees the change

## On the device

- Smoke stage: boots, Hub appears, button input works, audio plays
- Domain validation: a whitelisted call connects, a voice message round-trips, location updates arrive (live-ish, not real-time)
- Offline validation: music and stories still play with no internet — the local-first promise, exercised
- Soak concerns: battery drain, long-running stability under systemd supervision (TBD how measured)
- Who runs on-device stages and when: per-PR, per-release, or on a cadence (TBD)

## Today vs. target

- Today: host tests plus manual validation on the Pi-based prototype
- Target: a written on-device checklist with named stages and pass criteria
- Target: automated on-device testing on real hardware — feasibility and scope (TBD)
- Target: coverage expectations for the future parent app and SDK packages, once they exist

## Open questions

- TODO: What is the minimal on-device checklist a release must pass, and where does it live?
- TODO: Can any on-device validation be automated on prototype hardware, or is it manual until the product board?
- TODO: How do we test 4G and GPS behavior repeatably — field procedure, lab setup, or simulation?
